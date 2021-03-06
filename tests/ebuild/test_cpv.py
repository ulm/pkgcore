# Copyright: 2006-2011 Brian Harring <ferringb@gmail.com>
# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2

from random import shuffle

import pytest
from snakeoil.compatibility import cmp
from snakeoil.test import mk_cpy_loadable_testcase

from pkgcore.ebuild import cpv

def generate_misc_sufs():
    simple_good_sufs = ["_alpha", "_beta", "_pre", "_p"]
    suf_nums = list(range(100))
    shuffle(suf_nums)

    good_sufs = (simple_good_sufs + [f"{x}{suf_nums.pop()}" for x in simple_good_sufs])

    l = len(good_sufs)
    good_sufs = good_sufs + [
        good_sufs[x] + good_sufs[l - x - 1] for x in range(l)]

    bad_sufs  = ["_a", "_9", "_"] + [x+" " for x in simple_good_sufs]
    return good_sufs, bad_sufs


class Test_native_Cpv(object):

    kls = staticmethod(cpv.native_CPV)

    @classmethod
    def vkls(cls, *args):
        return cls.kls(versioned=True, *args)

    def ukls(cls, *args):
        return cls.kls(versioned=False, *args)

    run_cpy_ver_cmp = False

    good_cats = (
        "dev-util", "dev+", "dev-util+", "DEV-UTIL", "aaa0",
        "aaa-0", "multi/depth", "cross-dev_idiot.hacks-suck", "a")
    bad_cats  = (".util", "_dev", "", "dev-util ", "multi//depth")
    good_pkgs = ("diffball", "a9", "a9+", "a-100dpi", "diff-mode-")
    bad_pkgs  = ("diffball ", "diffball-9", "a-3D", "ab--df", "-df", "+dfa")

    good_cp   = (
        "bbb-9/foon", "dev-util/diffball", "dev-util/diffball-a9",
        "dev-ut-asdf/emacs-cvs", "xfce-base/xfce4", "bah/f-100dpi",
        "dev-util/diffball-blah-monkeys")

    good_vers = ("1", "2.3.4", "2.3.4a", "02.3", "2.03", "3d", "3D")
    bad_vers  = ("2.3a.4", "2.a.3", "2.3_", "2.3 ", "2.3.", "cvs.2")

    good_sufs, bad_sufs = generate_misc_sufs()
    good_revs = ("-r1", "-r300", "-r0", "",
        "-r1000000000000000000")
    bad_revs = ("-r", "-ra", "-r", "-R1")

    testing_secondary_args = False

    def make_inst(self, cat, pkg, fullver=""):
        if self.testing_secondary_args:
            return self.kls(cat, pkg, fullver, versioned=bool(fullver))
        if fullver:
            return self.vkls(f"{cat}/{pkg}-{fullver}")
        return self.ukls(f"{cat}/{pkg}")

    def test_simple_key(self):
        with pytest.raises(cpv.InvalidCPV):
            self.make_inst("da", "ba-3", "3.3")
        for src in [[("dev-util", "diffball", "0.7.1"), "dev-util/diffball"],
            ["dev-util/diffball"],
            ["dev-perl/mod_perl"],
            ["dev-perl/mod_p"],
            [("dev-perl", "mod-p", ""), "dev-perl/mod-p"],
            ["dev-perl/mod-p-1", "dev-perl/mod-p"],]:
            if len(src) == 1:
                key = src[0]
            else:
                key = src[1]
            if isinstance(src[0], str):
                cat, pkgver = src[0].rsplit("/", 1)
                vals = pkgver.rsplit("-", 1)
                if len(vals) == 1:
                    pkg = pkgver
                    ver = ''
                else:
                    pkg, ver = vals
            else:
                cat, pkg, ver = src[0]

            assert self.make_inst(cat, pkg, ver).key == key

    def test_init(self):
        self.kls("dev-util", "diffball", "0.7.1")
        self.kls("dev-util/diffball-0.7.1", versioned=True)
        with pytest.raises(TypeError):
            self.kls("dev-util", "diffball")
        with pytest.raises(TypeError):
            self.vkls("dev-util", "diffball", None)

    def test_parsing(self):
        # check for gentoo bug 263787
        self.process_pkg(False, 'app-text', 'foo-123-bar')
        self.process_ver(False, 'app-text', 'foo-123-bar', '2.0017a_p', '-r5')
        with pytest.raises(cpv.InvalidCPV):
            self.ukls('app-text/foo-123')
        for cat_ret, cats in [[False, self.good_cats], [True, self.bad_cats]]:
            for cat in cats:
                for pkg_ret, pkgs in [[False, self.good_pkgs],
                                      [True, self.bad_pkgs]]:
                    for pkg in pkgs:
                        self.process_pkg(cat_ret or pkg_ret, cat, pkg)

        for cp in self.good_cp:
            cat, pkg = cp.rsplit("/", 1)
            for rev_ret, revs in [[False, self.good_revs],
                                  [True, self.bad_revs]]:
                for rev in revs:
                    for ver_ret, vers in [[False, self.good_vers],
                                          [True, self.bad_vers]]:
                        for ver in vers:
                            self.process_ver(ver_ret or rev_ret, cat, pkg,
                                             ver, rev)

        for x in (10, 18, 19, 36, 100):
            assert self.kls("da", "ba", f"1-r0{'0' * x}").revision == 0
            assert \
                int(self.kls("da", "ba", f"1-r1{'0' * x}1").revision) == int(f"1{'0' * x}1")

    def process_pkg(self, ret, cat, pkg):
        if ret:
            with pytest.raises(cpv.InvalidCPV):
                self.make_inst(cat, pkg)
        else:
            c = self.make_inst(cat, pkg)
            assert c.cpvstr == f"{cat}/{pkg}"
            assert c.category == cat
            assert c.package == pkg
            assert c.key == f"{cat}/{pkg}"
            assert c.revision is None
            assert c.version is None
            assert c.fullver is None

    def process_ver(self, ret, cat, pkg, ver, rev):
        if ret:
            with pytest.raises(cpv.InvalidCPV):
                self.make_inst(cat, pkg, f"{ver}{rev}")
        else:
            c = self.make_inst(cat, pkg, ver + rev)
            if rev == "" or rev == "-r0":
                assert c.cpvstr == f"{cat}/{pkg}-{ver}"
                if rev:
                    assert c.revision == 0
                else:
                    assert c.revision is None
                assert c.fullver == ver
            else:
                assert c.revision == int(rev.lstrip("-r"))
                assert c.cpvstr == f"{cat}/{pkg}-{ver}{rev}"
                assert c.fullver == ver+rev
            assert c.category == cat
            assert c.package == pkg
            assert c.key == f"{cat}/{pkg}"
            assert c.version == ver

        for suf in self.good_sufs:
            self.process_suf(ret, cat, pkg, ver + suf, rev)
            for bad_suf in self.bad_sufs:
                # double process, front and back.
                self.process_suf(True, cat, pkg, suf + bad_suf, rev)
                self.process_suf(True, cat, pkg, bad_suf + suf, rev)

        for suf in self.bad_sufs:
            # check standalone.
            self.process_suf(True, cat, pkg, ver+suf, rev)

    def process_suf(self, ret, cat, pkg, ver, rev):
        if ret:
            with pytest.raises(cpv.InvalidCPV):
                self.make_inst(cat, pkg, ver+rev)
        else:
            # redundant in light of process_ver... combine these somehow.
            c = self.make_inst(cat, pkg, ver + rev)
            if rev == '' or rev == '-r0':
                assert c.cpvstr == f"{cat}/{pkg}-{ver}"
                if rev:
                    assert c.revision == 0
                else:
                    assert c.revision is None
                assert c.fullver == ver
            else:
                assert c.cpvstr == f"{cat}/{pkg}-{ver}{rev}"
                assert c.revision == int(rev.lstrip("-r"))
                assert c.fullver == ver + rev
            assert c.category == cat
            assert c.package == pkg
            assert c.key == f"{cat}/{pkg}"
            assert c.version == ver

    def assertGT(self, obj1, obj2):
        assert obj1 > obj2, f'{obj1!r} must be > {obj2!r}'
        # swap the ordering, so that it's no longer obj1.__cmp__, but obj2s
        assert obj2 < obj1, f'{obj2!r} must be < {obj1!r}'

        if self.run_cpy_ver_cmp and obj1.fullver and obj2.fullver:
            assert cpv.cpy_ver_cmp(
                obj1.version, obj1.revision, obj2.version, obj2.revision) > 0, \
                    f'cpy_ver_cmp, {obj1!r} > {obj2!r}'
            assert cpv.cpy_ver_cmp(
                obj2.version, obj2.revision, obj1.version, obj1.revision) < 0, \
                    f'cpy_ver_cmp, {obj2!r} < {obj1!r}'

    def test_cmp(self):
        ukls, vkls = self.ukls, self.vkls
        assert cmp(vkls("dev-util/diffball-0.1"), vkls("dev-util/diffball-0.2")) < 0
        base = "dev-util/diffball-0.7.1"
        assert not cmp(vkls(base), vkls(base))
        for rev in ("", "-r1"):
            last = None
            for suf in ["_alpha", "_beta", "_pre", "", "_p"]:
                if suf == "":
                    sufs = [suf]
                else:
                    sufs = [suf, suf+"4"]
                for x in sufs:
                    cur = vkls(base+x+rev)
                    assert cur == vkls(base+x+rev)
                    if last is not None:
                        assert cur > last

        assert vkls("da/ba-6a") > vkls("da/ba-6")
        assert vkls("da/ba-6a-r1") > vkls("da/ba-6a")
        assert vkls("da/ba-6.0") > vkls("da/ba-6")
        assert vkls("da/ba-6.0.0") > vkls("da/ba-6.0b")
        assert vkls("da/ba-6.02") > vkls("da/ba-6.0.0")
        # float comparison rules.
        assert vkls("da/ba-6.2") > vkls("da/ba-6.054")
        assert vkls("da/ba-6") == vkls("da/ba-6")
        assert ukls("db/ba") > ukls("da/ba")
        assert ukls("da/bb") > ukls("da/ba")
        assert vkls("da/ba-6.0_alpha0_p1") > vkls("da/ba-6.0_alpha")
        assert vkls("da/ba-6.0_alpha") == vkls("da/ba-6.0_alpha0")
        assert vkls("da/ba-6.1") > vkls("da/ba-6.09")
        assert vkls("da/ba-6.0.1") > vkls("da/ba-6.0")
        assert vkls("da/ba-12.2.5") > vkls("da/ba-12.2b")

        # test for gentoo bug 287848
        assert vkls("dev-lang/erlang-12.2.5") > vkls("dev-lang/erlang-12.2b")
        assert vkls("dev-lang/erlang-12.2.5-r1") > vkls("dev-lang/erlang-12.2b")

        assert vkls("da/ba-6.01.0") == vkls("da/ba-6.010.0")

        for v1, v2 in (("1.001000000000000000001", "1.001000000000000000002"),
            ("1.00100000000", "1.0010000000000000001"),
            ("1.01", "1.1")):
            assert vkls(f"da/ba-{v2}") > vkls(f"da/ba-{v1}")

        for x in (18, 36, 100):
            s = "0" * x
            assert vkls(f"da/ba-10{s}1") > vkls(f"da/ba-1{s}1")

        for x in (18, 36, 100):
            s = "0" * x
            assert vkls(f"da/ba-1-r10{s}1") > vkls(f"da/ba-1-r1{s}1")

        assert vkls('sys-apps/net-tools-1.60_p2010081516093') > \
            vkls('sys-apps/net-tools-1.60_p2009072801401')

        assert vkls('sys-apps/net-tools-1.60_p20100815160931') > \
            vkls('sys-apps/net-tools-1.60_p20090728014017')

        assert vkls('sys-apps/net-tools-1.60_p20100815160931') > \
            vkls('sys-apps/net-tools-1.60_p20090728014017-r1')

        # Regression test: python does comparison slightly differently
        # if the classes do not match exactly (it prefers rich
        # comparison over __cmp__).
        class DummySubclass(self.kls):
            pass

        assert DummySubclass("da/ba-6.0_alpha0_p1", versioned=True) != vkls("da/ba-6.0_alpha")
        assert DummySubclass("da/ba-6.0_alpha0", versioned=True) == vkls("da/ba-6.0_alpha")

        assert DummySubclass("da/ba-6.0", versioned=True) != "foon"
        assert DummySubclass("da/ba-6.0", versioned=True) == \
            DummySubclass("da/ba-6.0-r0", versioned=True)

    def test_no_init(self):
        """Test if the cpv is in a somewhat sane state if __init__ fails.

        IPython used to segfault when showing a verbose traceback for
        a subclass of CPV which raised cpv.InvalidCPV. This checks
        if such uninitialized objects survive some basic poking.
        """
        uninited = self.kls.__new__(self.kls)
        broken = self.kls.__new__(self.kls)
        with pytest.raises(cpv.InvalidCPV):
            broken.__init__('broken', versioned=True)
        for thing in (uninited, broken):
            # the c version returns None, the py version does not have the attr
            getattr(thing, 'cpvstr', None)
            repr(thing)
            str(thing)
            # The c version returns a constant, the py version raises
            try:
                hash(thing)
            except AttributeError:
                pass

    def test_r0_removal(self):
        obj = self.kls("dev-util/diffball-1.0-r0", versioned=True)
        assert obj.fullver == "1.0"
        assert obj.revision == 0
        assert str(obj) == "dev-util/diffball-1.0"


@pytest.mark.skipif(not cpv.cpy_builtin, reason="cpython cpv extension not available")
class Test_CPY_Cpv(Test_native_Cpv):
    if cpv.cpy_builtin:
        kls = staticmethod(cpv.cpy_CPV)
        run_cpy_ver_cmp = True


class Test_CPY_Cpv_OptionalArgs(Test_CPY_Cpv):

    testing_secondary_args = True


test_cpy_used = mk_cpy_loadable_testcase(
    "pkgcore.ebuild._cpv", "pkgcore.ebuild.cpv", "CPV_base", "CPV")

