# Copyright: 2006-2011 Brian Harring <ferringb@gmail.com>
# License: GPL2/BSD

__all__ = (
    "ProfileError", "ProfileNode", "EmptyRootNode", "OnDiskProfile",
    "UserProfile",
)

from collections import namedtuple
from functools import partial
from itertools import chain
import os

from snakeoil import caching, klass
from snakeoil.bash import iter_read_bash, read_bash_dict
from snakeoil.compatibility import IGNORED_EXCEPTIONS
from snakeoil.containers import InvertedContains
from snakeoil.demandload import demandload
from snakeoil.fileutils import readlines_utf8
from snakeoil.osutils import abspath, pjoin
from snakeoil.sequences import split_negations, stable_unique

from pkgcore.config import ConfigHint, errors
from pkgcore.ebuild import const, ebuild_src, misc

demandload(
    'collections:defaultdict',
    'snakeoil.data_source:local_source',
    'snakeoil.mappings:ImmutableDict',
    'pkgcore.ebuild:cpv,repo_objs,errors@ebuild_errors',
    'pkgcore.ebuild.atom:atom',
    'pkgcore.ebuild.eapi:get_eapi',
    'pkgcore.fs.livefs:sorted_scan',
    'pkgcore.ebuild.repository:ProvidesRepo',
    'pkgcore.log:logger',
    'pkgcore.restrictions:packages',
)


def package_keywords_splitter(val):
    v = val.split()
    try:
        return atom(v[0]), tuple(stable_unique(v[1:]))
    except ebuild_errors.MalformedAtom as e:
        logger.warning(f'parsing error: {e}')


class ProfileError(errors.ParsingError):

    def __init__(self, path, filename, error):
        self.path, self.filename, self.error = path, filename, error

    def __str__(self):
        if self.filename:
            return f"failed parsing {self.filename!r} in {self.path!r}: {self.error}"
        return f"failed parsing {self.path!r}: {self.error}"


def load_property(filename, handler=iter_read_bash, fallback=(),
                  read_func=readlines_utf8, allow_recurse=False, eapi_optional=None):
    """Decorator simplifying parsing profile files to generate a profile property.

    :param filename: The filename to parse within that profile directory.
    :keyword handler: An invokable that is fed the content returned from read_func.
    :keyword fallback: What to return if the file does not exist for this profile.  Must
        be immutable.
    :keyword read_func: An invokable in the form of :py:`readlines_utf8`.
    :keyword allow_recurse: Controls whether or not this specific content can be a directory
        of files, rather than just a file.  Only is consulted if we're parsing the profile
        in non pms strict mode.
    :keyword eapi_optional: If given, the EAPI for this profile node is checked to see if
        the given optional evaluates to True; if so, then parsing occurs.  If False, then
        the fallback is returned and no ondisk activity occurs.
    :return: A :py:`klass.jit.attr_named` property instance.
    """
    def f(func):
        f2 = klass.jit_attr_named(f'_{func.__name__}')
        return f2(partial(
            _load_and_invoke, func, filename, handler, fallback,
            read_func, allow_recurse, eapi_optional))
    return f

def _load_and_invoke(func, filename, handler, fallback, read_func,
                     allow_recurse, eapi_optional, self):
    profile_path = self.path.rstrip('/')
    if eapi_optional is not None and not getattr(self.eapi.options, eapi_optional, None):
        return fallback
    try:
        base = pjoin(profile_path, filename)
        if self.pms_strict or not allow_recurse:
            try:
                data = read_func(base, True, True, True)
            except IsADirectoryError as e:
                raise ProfileError(self.path, filename,
                    "path is a directory, but this profile is PMS format- "
                    "directories aren't allowed.  See layout.conf profile-formats "
                    "to enable directory support") from e
        else:
            data = []
            profile_len = len(profile_path) + 1
            # Skip hidden files and backup files, those beginning with '.' or
            # ending with '~', respectively.
            files = sorted_scan(base, hidden=False, backup=False)
            if not files:
                data = None
            else:
                for location in sorted(files):
                    filename = location[profile_len:]
                    data.extend(read_func(location, True, True, True))

        if data is None:
            return func(self, fallback)
        if handler:
            data = handler(data)
        return func(self, data)
    except IGNORED_EXCEPTIONS:
        raise
    except ProfileError:
        # no point in wrapping/throwing..
        raise
    except Exception as e:
        raise ProfileError(profile_path, filename, e) from e


_make_incrementals_dict = partial(misc.IncrementalsDict, const.incrementals)

def _open_utf8(path, *args):
    try:
        return open(path, 'r', encoding='utf8')
    except FileNotFoundError:
        return None


class ProfileNode(object, metaclass=caching.WeakInstMeta):

    __inst_caching__ = True
    _repo_map = None

    def __init__(self, path, pms_strict=True):
        if not os.path.isdir(path):
            raise ProfileError(path, "", "profile doesn't exist")
        self.path = path
        self.pms_strict = pms_strict

    def __str__(self):
        return f"profile at {self.path!r}"

    def __repr__(self):
        return '<%s path=%r, @%#8x>' % (self.__class__.__name__, self.path, id(self))

    system = klass.alias_attr("packages.system")
    visibility = klass.alias_attr("packages.visibility")

    _packages_kls = namedtuple("packages", ("system", "visibility"))

    @load_property("packages")
    def packages(self, data):
        repo_config = self.repoconfig
        profile_set = repo_config is not None and 'profile-set' in repo_config.profile_formats
        # sys packages and visibility
        sys, neg_sys, vis, neg_vis = [], [], [], []
        neg_sys_wildcard = False
        for line in data:
            if line[0] == '-':
                if line == '-*':
                    neg_sys_wildcard = True
                elif line[1] == '*':
                    neg_sys.append(self.eapi_atom(line[2:]))
                elif profile_set:
                    neg_sys.append(self.eapi_atom(line[1:]))
                else:
                    neg_vis.append(self.eapi_atom(line[1:], negate_vers=True))
            else:
                if line[0] == '*':
                    sys.append(self.eapi_atom(line[1:]))
                elif profile_set:
                    sys.append(self.eapi_atom(line))
                else:
                    vis.append(self.eapi_atom(line, negate_vers=True))
        system = [tuple(neg_sys), tuple(sys)]
        if neg_sys_wildcard:
            system.append(neg_sys_wildcard)
        return self._packages_kls(
            tuple(system),
            (tuple(neg_vis), tuple(vis)))

    @load_property("parent")
    def parent_paths(self, data):
        repo_config = self.repoconfig
        if repo_config is not None and 'portage-2' in repo_config.profile_formats:
            l = []
            for repo_id, separator, path in (x.partition(':') for x in data):
                if separator:
                    if repo_id:
                        try:
                            location = self._repo_map[repo_id]
                        except KeyError:
                            raise ValueError(f"unknown repository name: {repo_id!r}")
                        except TypeError:
                            raise ValueError("repo mapping is unset")
                    l.append(abspath(pjoin(location, 'profiles', path)))
                else:
                    l.append(abspath(pjoin(self.path, repo_id)))
            return tuple(l)
        return tuple(abspath(pjoin(self.path, x)) for x in data)

    @klass.jit_attr
    def parents(self):
        kls = getattr(self, 'parent_node_kls', self.__class__)
        return tuple(kls(x) for x in self.parent_paths)

    @load_property("package.provided", allow_recurse=True,
                   eapi_optional='profile_pkg_provided')
    def pkg_provided(self, data):
        def _parse_cpv(s):
            try:
                return cpv.versioned_CPV(s)
            except cpv.InvalidCPV:
                logger.warning(f'invalid package.provided entry: {s!r}')
        return split_negations(data, _parse_cpv)

    @load_property("package.mask", allow_recurse=True)
    def masks(self, data):
        return split_negations(data, self.eapi_atom)

    @load_property("package.unmask", allow_recurse=True)
    def unmasks(self, data):
        return split_negations(data, self.eapi_atom)

    @load_property("package.keywords", allow_recurse=True)
    def keywords(self, data):
        return tuple(filter(None, (package_keywords_splitter(x) for x in data)))

    @load_property("package.accept_keywords", allow_recurse=True)
    def accept_keywords(self, data):
        return tuple(filter(None, (package_keywords_splitter(x) for x in data)))

    @load_property("package.use", allow_recurse=True)
    def pkg_use(self, data):
        c = misc.ChunkedDataDict()
        c.update_from_stream(
            chain.from_iterable(self._parse_package_use(data).values()))
        c.freeze()
        return c

    @load_property("deprecated", handler=None, fallback=None)
    def deprecated(self, data):
        if data is not None:
            data = iter(data)
            try:
                replacement = next(data).strip()
                msg = "\n".join(x.lstrip("#").strip() for x in data)
                data = (replacement, msg)
            except StopIteration:
                # only an empty replacement could trigger this; thus
                # formatted badly.
                raise ValueError("didn't specify a replacement profile")
        return data

    def _parse_package_use(self, data):
        d = defaultdict(list)
        # split the data down ordered cat/pkg lines
        for line in data:
            l = line.split()
            try:
                a = self.eapi_atom(l[0])
            except ebuild_errors.MalformedAtom as e:
                logger.warning(e)
                continue
            if len(l) == 1:
                logger.warning(f"malformed line, missing USE flag(s): {line!r}")
                continue
            d[a.key].append(misc.chunked_data(a, *split_negations(l[1:])))

        return ImmutableDict((k, misc._build_cp_atom_payload(v, atom(k)))
                             for k, v in d.items())

    def _parse_use(self, data):
        c = misc.ChunkedDataDict()
        neg, pos = split_negations(data)
        if neg or pos:
            c.add_bare_global(neg, pos)
        c.freeze()
        return c

    @load_property("use.force", allow_recurse=True)
    def use_force(self, data):
        return self._parse_use(data)

    @load_property("use.stable.force", allow_recurse=True,
                   eapi_optional='profile_stable_use')
    def use_stable_force(self, data):
        return self._parse_use(data)

    @load_property("package.use.force", allow_recurse=True)
    def pkg_use_force(self, data):
        return self._parse_package_use(data)

    @load_property("package.use.stable.force", allow_recurse=True,
                   eapi_optional='profile_stable_use')
    def pkg_use_stable_force(self, data):
        return self._parse_package_use(data)

    @load_property("use.mask", allow_recurse=True)
    def use_mask(self, data):
        return self._parse_use(data)

    @load_property("use.stable.mask", allow_recurse=True,
                   eapi_optional='profile_stable_use')
    def use_stable_mask(self, data):
        return self._parse_use(data)

    @load_property("package.use.mask", allow_recurse=True)
    def pkg_use_mask(self, data):
        return self._parse_package_use(data)

    @load_property("package.use.stable.mask", allow_recurse=True,
                   eapi_optional='profile_stable_use')
    def pkg_use_stable_mask(self, data):
        return self._parse_package_use(data)

    @klass.jit_attr
    def masked_use(self):
        c = self.use_mask
        if self.pkg_use_mask:
            c = c.clone(unfreeze=True)
            c.update_from_stream(
                chain.from_iterable(self.pkg_use_mask.values()))
            c.freeze()
        return c

    @klass.jit_attr
    def stable_masked_use(self):
        c = self.use_mask.clone(unfreeze=True)
        if self.use_stable_mask:
            c.merge(self.use_stable_mask)
        if self.pkg_use_mask:
            c.update_from_stream(
                chain.from_iterable(self.pkg_use_mask.values()))
        if self.pkg_use_stable_mask:
            c.update_from_stream(
                chain.from_iterable(self.pkg_use_stable_mask.values()))
        c.freeze()
        return c

    @klass.jit_attr
    def forced_use(self):
        c = self.use_force
        if self.pkg_use_force:
            c = c.clone(unfreeze=True)
            c.update_from_stream(
                chain.from_iterable(self.pkg_use_force.values()))
            c.freeze()
        return c

    @klass.jit_attr
    def stable_forced_use(self):
        c = self.use_force.clone(unfreeze=True)
        if self.use_stable_force:
            c.merge(self.use_stable_force)
        if self.pkg_use_force:
            c.update_from_stream(
                chain.from_iterable(self.pkg_use_force.values()))
        if self.pkg_use_stable_force:
            c.update_from_stream(
                chain.from_iterable(self.pkg_use_stable_force.values()))
        c.freeze()
        return c

    @load_property('make.defaults', fallback=None, read_func=_open_utf8, handler=None)
    def default_env(self, data):
        rendered = _make_incrementals_dict()
        for parent in self.parents:
            rendered.update(parent.default_env.items())

        if data is not None:
            data = read_bash_dict(data, vars_dict=rendered)
            rendered.update(data.items())
        return ImmutableDict(rendered)

    @klass.jit_attr
    def bashrc(self):
        path = pjoin(self.path, "profile.bashrc")
        if os.path.exists(path):
            return local_source(path)
        return None

    @load_property('eapi', fallback=('0',))
    def eapi(self, data):
        data = (x.strip() for x in data)
        data = [x for x in data if x]
        if len(data) != 1:
            raise ProfileError(self.path, 'eapi', "multiple lines detected")
        eapi = get_eapi(data[0])
        if not eapi.is_supported:
            raise ProfileError(self.path, 'eapi', f'unsupported EAPI: {str(eapi)!r}')
        return eapi

    eapi_atom = klass.alias_attr("eapi.atom_kls")

    @klass.jit_attr
    def repoconfig(self):
        return self._load_repoconfig_from_path(self.path)

    @staticmethod
    def _load_repoconfig_from_path(path):
        path = abspath(path)
        # strip '/' so we don't get '/usr/portage' == ('', 'usr', 'portage')
        chunks = path.lstrip('/').split('/')
        try:
            pindex = max(idx for idx, x in enumerate(chunks) if x == 'profiles')
        except ValueError:
            # not in a repo...
            return None
        repo_path = pjoin('/', *chunks[:pindex])
        return repo_objs.RepoConfig(repo_path)

    @classmethod
    def _autodetect_and_create(cls, path):
        repo_config = cls._load_repoconfig_from_path(path)

        # note while this else seems pointless, we do it this
        # way so that we're not passing an arg unless needed- instance
        # caching is a bit overprotective, even if pms_strict defaults to True,
        # cls(path) is not cls(path, pms_strict=True)

        if repo_config is not None and 'pms' not in repo_config.profile_formats:
            profile = cls(path, pms_strict=False)
        else:
            profile = cls(path)

        # optimization to avoid re-parsing what we already did.
        object.__setattr__(profile, '_repoconfig', repo_config)
        return profile


class EmptyRootNode(ProfileNode):

    __inst_caching__ = True

    parents = ()
    deprecated = None
    pkg_use = masked_use = stable_masked_use = forced_use = stable_forced_use = misc.ChunkedDataDict()
    forced_use.freeze()
    pkg_use_force = pkg_use_mask = ImmutableDict()
    pkg_provided = visibility = system = ((), ())


class ProfileStack(object):

    _node_kls = ProfileNode

    def __init__(self, profile):
        self.profile = profile
        self.node = self._node_kls._autodetect_and_create(profile)

    @property
    def arch(self):
        return self.default_env.get("ARCH")

    deprecated = klass.alias_attr("node.deprecated")

    @klass.jit_attr
    def stack(self):
        def f(node):
            for x in node.parent_paths:
                x = self._node_kls._autodetect_and_create(x)
                for y in f(x):
                    yield y
            yield node
        return tuple(f(self.node))

    @klass.jit_attr
    def _system_profile(self):
        """User-selected system profile.

        This should map directly to the profile linked to /etc/portage/make.profile.
        """
        # prefer main system profile; otherwise, fallback to custom user profile
        for profile in reversed(self.stack):
            if not isinstance(profile, UserProfileNode):
                break
        return profile

    def _collapse_use_dict(self, attr):
        stack = (getattr(x, attr) for x in self.stack)
        d = misc.ChunkedDataDict()
        for mapping in stack:
            d.merge(mapping)
        d.freeze()
        return d

    @klass.jit_attr
    def forced_use(self):
        return self._collapse_use_dict("forced_use")

    @klass.jit_attr
    def masked_use(self):
        return self._collapse_use_dict("masked_use")

    @klass.jit_attr
    def stable_forced_use(self):
        return self._collapse_use_dict("stable_forced_use")

    @klass.jit_attr
    def stable_masked_use(self):
        return self._collapse_use_dict("stable_masked_use")

    @klass.jit_attr
    def pkg_use(self):
        return self._collapse_use_dict("pkg_use")

    def _collapse_generic(self, attr, clear=False):
        s = set()
        for node in self.stack:
            val = getattr(node, attr)
            if clear and len(val) > 2 and val[2]:
                s.clear()
            s.difference_update(val[0])
            s.update(val[1])
        return s

    @klass.jit_attr
    def default_env(self):
        d = dict(self.node.default_env.items())
        for incremental in const.incrementals:
            v = d.pop(incremental, '').split()
            if v:
                if incremental in const.incrementals_unfinalized:
                    d[incremental] = tuple(v)
                else:
                    v = misc.render_incrementals(
                        v,
                        msg_prefix=f"While expanding {incremental}, value {v!r}: ")
                    if v:
                        d[incremental] = tuple(v)
        return ImmutableDict(d.items())

    @property
    def profile_only_variables(self):
        if "PROFILE_ONLY_VARIABLES" in const.incrementals:
            return frozenset(self.default_env.get("PROFILE_ONLY_VARIABLES", ()))
        return frozenset(self.default_env.get("PROFILE_ONLY_VARIABLES", "").split())

    @klass.jit_attr
    def use_expand(self):
        """USE_EXPAND variables defined by the profile."""
        if "USE_EXPAND" in const.incrementals:
            return frozenset(self.default_env.get("USE_EXPAND", ()))
        return frozenset(self.default_env.get("USE_EXPAND", "").split())

    @klass.jit_attr
    def use(self):
        """USE flag settings for the profile."""
        return tuple(list(self.default_env.get('USE', ())) + list(self.expand_use()))

    def expand_use(self, env=None):
        """Expand USE_EXPAND settings to USE flags."""
        if env is None:
            env = self.default_env

        use = []
        for u in self.use_expand:
            value = env.get(u)
            if value is None:
                continue
            u2 = u.lower() + '_'
            use.extend(u2 + x for x in value.split())
        return tuple(use)

    @property
    def use_expand_hidden(self):
        if "USE_EXPAND_HIDDEN" in const.incrementals:
            return frozenset(self.default_env.get("USE_EXPAND_HIDDEN", ()))
        return frozenset(self.default_env.get("USE_EXPAND_HIDDEN", "").split())

    @property
    def iuse_implicit(self):
        if "IUSE_IMPLICIT" in const.incrementals:
            return frozenset(self.default_env.get("IUSE_IMPLICIT", ()))
        return frozenset(self.default_env.get("IUSE_IMPLICIT", "").split())

    @property
    def use_expand_implicit(self):
        if "USE_EXPAND_IMPLICIT" in const.incrementals:
            return frozenset(self.default_env.get("USE_EXPAND_IMPLICIT", ()))
        return frozenset(self.default_env.get("USE_EXPAND_IMPLICIT", "").split())

    @property
    def use_expand_unprefixed(self):
        if "USE_EXPAND_UNPREFIXED" in const.incrementals:
            return frozenset(self.default_env.get("USE_EXPAND_UNPREFIXED", ()))
        return frozenset(self.default_env.get("USE_EXPAND_UNPREFIXED", "").split())

    @klass.jit_attr
    def iuse_effective(self):
        iuse_effective = []

        # EAPI 5 and above allow profile defined IUSE injection (see PMS)
        if self._system_profile.eapi.options.profile_iuse_injection:
            iuse_effective.extend(self.iuse_implicit)
            for v in self.use_expand_implicit.intersection(self.use_expand_unprefixed):
                iuse_effective.extend(self.default_env.get("USE_EXPAND_VALUES_" + v, "").split())
            for v in self.use_expand.intersection(self.use_expand_implicit):
                for x in self.default_env.get("USE_EXPAND_VALUES_" + v, "").split():
                    iuse_effective.append(v.lower() + "_" + x)
        else:
            iuse_effective.extend(self._system_profile.repoconfig.known_arches)
            for v in self.use_expand:
                for x in self.default_env.get("USE_EXPAND_VALUES_" + v, "").split():
                    iuse_effective.append(v.lower() + "_" + x)

        return frozenset(iuse_effective)

    @klass.jit_attr
    def provides_repo(self):
        return ProvidesRepo(pkgs=self._collapse_generic("pkg_provided"))

    @klass.jit_attr
    def masks(self):
        return frozenset(chain(
            self._collapse_generic("masks"),
            self._collapse_generic("visibility")))

    @klass.jit_attr
    def unmasks(self):
        return frozenset(self._collapse_generic('unmasks'))

    @klass.jit_attr
    def keywords(self):
        return tuple(chain.from_iterable(x.keywords for x in self.stack))

    @klass.jit_attr
    def accept_keywords(self):
        return tuple(chain.from_iterable(x.accept_keywords for x in self.stack))

    def _incremental_masks(self, stack_override=None):
        if stack_override is None:
            stack_override = self.stack
        return tuple(node.masks for node in stack_override if any(node.masks))

    def _incremental_unmasks(self, stack_override=None):
        if stack_override is None:
            stack_override = self.stack
        return tuple(node.unmasks for node in stack_override if any(node.unmasks))

    @klass.jit_attr
    def bashrcs(self):
        return tuple(x.bashrc for x in self.stack if x.bashrc is not None)

    bashrc = klass.alias_attr("bashrcs")
    path = klass.alias_attr("node.path")

    @klass.jit_attr
    def system(self):
        return frozenset(self._collapse_generic('system', clear=True))


class OnDiskProfile(ProfileStack):

    pkgcore_config_type = ConfigHint(
        {'basepath': 'str', 'profile': 'str'},
        required=('basepath', 'profile'),
        typename='profile',
    )

    def __init__(self, basepath, profile, load_profile_base=True):
        super().__init__(pjoin(basepath, profile))
        self.basepath = basepath
        self.load_profile_base = load_profile_base

    @staticmethod
    def split_abspath(path):
        path = abspath(path)
        # filter's heavy, but it handles '/' while also
        # suppressing the leading '/'
        chunks = [x for x in path.split("/") if x]
        try:
            # poor mans rindex.
            pbase = max(x for x in enumerate(chunks) if x[1] == 'profiles')[0]
        except ValueError:
            # no base found.
            return None
        return pjoin("/", *chunks[:pbase+1]), '/'.join(chunks[pbase+1:])

    @classmethod
    def from_abspath(cls, path):
        vals = cls.split_abspath(path)
        if vals is not None:
            vals = cls(load_profile_base=True, *vals)
        return vals

    @klass.jit_attr
    def stack(self):
        l = ProfileStack.stack.function(self)
        if self.load_profile_base:
            l = (EmptyRootNode._autodetect_and_create(self.basepath),) + l
        return l

    @klass.jit_attr
    def _incremental_masks(self):
        stack = self.stack
        if self.load_profile_base:
            stack = stack[1:]
        return ProfileStack._incremental_masks(self, stack_override=stack)

    @klass.jit_attr
    def _incremental_unmasks(self):
        stack = self.stack
        if self.load_profile_base:
            stack = stack[1:]
        return ProfileStack._incremental_unmasks(self, stack_override=stack)


class UserProfileNode(ProfileNode):

    parent_node_kls = ProfileNode

    def __init__(self, path, parent_path):
        self.override_path = pjoin(path, parent_path)
        super().__init__(path, pms_strict=False)

    @klass.jit_attr
    def parents(self):
        return (ProfileNode(self.override_path),)

    @klass.jit_attr
    def parent_paths(self):
        return (self.override_path,)


class UserProfile(OnDiskProfile):

    pkgcore_config_type = ConfigHint(
        {'user_path': 'str', 'parent_path': 'str', 'parent_profile': 'str'},
        required=('user_path', 'parent_path', 'parent_profile'),
        typename='profile',
    )

    def __init__(self, user_path, parent_path, parent_profile, load_profile_base=True):
        super().__init__(parent_path, parent_profile, load_profile_base)
        self.node = UserProfileNode(user_path, pjoin(parent_path, parent_profile))
