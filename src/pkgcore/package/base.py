# Copyright: 2005-2011 Brian Harring <ferringb@gmail.com>
# License: GPL2/BSD

"""
base package class; instances should derive from this.

Right now, doesn't provide much, need to change that down the line
"""

__all__ = ("base", "wrapper", "dynamic_getattr_dict")

from snakeoil import klass
from snakeoil.compatibility import cmp, IGNORED_EXCEPTIONS

from pkgcore import exceptions as base_errors
from pkgcore.operations import format
from pkgcore.package import errors


class base(object, metaclass=klass.immutable_instance):

    built = False
    configurable = False
    _operations = format.operations

    __slots__ = ("__weakref__",)
    _get_attr = {}

    @property
    def versioned_atom(self):
        raise NotImplementedError(self, "versioned_atom")

    @property
    def unversioned_atom(self):
        raise NotImplementedError(self, "unversioned_atom")

    def operations(self, domain, **kwds):
        return self._operations(domain, self, **kwds)

    @property
    def is_supported(self):
        return True


class wrapper(base):

    __slots__ = ("_raw_pkg", "_domain")

    klass.inject_richcmp_methods_from_cmp(locals())

    def operations(self, domain, **kwds):
        return self._raw_pkg._operations(domain, self, **kwds)

    def __init__(self, raw_pkg):
        object.__setattr__(self, "_raw_pkg", raw_pkg)

    def __cmp__(self, other):
        if isinstance(other, wrapper):
            return cmp(self._raw_pkg, other._raw_pkg)
        return cmp(self._raw_pkg, other)

    def __eq__(self, other):
        if isinstance(other, wrapper):
            return cmp(self._raw_pkg, other._raw_pkg) == 0
        return cmp(self._raw_pkg, other) == 0

    def __ne__(self, other):
        return not self == other

    __getattr__ = klass.GetAttrProxy("_raw_pkg")
    __dir__ = klass.DirProxy("_raw_pkg")

    built = klass.alias_attr("_raw_pkg.built")
    versioned_atom = klass.alias_attr("_raw_pkg.versioned_atom")
    unversioned_atom = klass.alias_attr("_raw_pkg.unversioned_atom")
    is_supported = klass.alias_attr('_raw_pkg.is_supported')

    def __hash__(self):
        return hash(self._raw_pkg)


def dynamic_getattr_dict(self, attr):
    functor = self._get_attr.get(attr)
    if functor is None:
        if attr == '__dict__':
            return self._get_attr
        raise AttributeError(self, attr)
    try:
        val = functor(self)
        object.__setattr__(self, attr, val)
        return val
    except IGNORED_EXCEPTIONS:
        raise
    except errors.MetadataException as e:
        if e.attr == attr:
            raise
        raise errors.MetadataException(self, attr, e.error, e.verbose) from e
    except errors.PackageError as e:
        raise errors.MetadataException(self, attr, str(e)) from e
    except PermissionError as e:
        raise base_errors.PermissionDenied(self.path, write=False) from e
