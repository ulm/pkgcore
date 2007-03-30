# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

"""
implementation of the standard PORTDIR + PORTDIR_OVERLAY repository stacking
"""

from pkgcore.repository import multiplex
from pkgcore.config import ConfigHint, errors
from pkgcore.ebuild import repository
from pkgcore.restrictions import packages

from snakeoil.lists import unstable_unique

class OverlayRepo(multiplex.tree):

    """
    Collapse multiple trees into one.

    Eclass dir is shared, the first package leftmost returned.
    """

    pkgcore_config_type = ConfigHint({'trees': 'refs:repo'}, typename='repo')

    configured = False
    configurables = ("domain", "settings",)
    configure = repository.ConfiguredTree

    # sucks a bit, need to work something better out here
    format_magic = "ebuild_src"

    def __init__(self, trees, **kwds):
        """
        @param trees: L{pkgcore.ebuild.repository.UnconfiguredTree} instances
            to combine.
        """

        if not trees or len(trees) < 2:
            raise errors.InstantiationError(
                "Must specify at least two pathes to ebuild trees to overlay")

        multiplex.tree.__init__(self, *trees)

    def _get_categories(self, *category):
        return tuple(
            unstable_unique(multiplex.tree._get_categories(self, *category)))

    def _get_packages(self, category):
        return tuple(unstable_unique(multiplex.tree._get_packages(self,
                                                                  category)))

    def _get_versions(self, catpkg):
        return tuple(unstable_unique(multiplex.tree._get_versions(self,
                                                                  catpkg)))

    def itermatch(self, *a, **kwds):
        s = set()
        for pkg in multiplex.tree.itermatch(self, *a, **kwds):
            if pkg.cpvstr not in s:
                yield pkg
                s.add(pkg.cpvstr)

    def __iter__(self):
        return self.itermatch(packages.AlwaysTrue)
