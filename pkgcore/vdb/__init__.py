# Copyright: 2005 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.restrictions.packages import OrRestriction
from pkgcore.repository import multiplex, virtual
from pkgcore.vdb.ondisk import tree as vdb_repository
from snakeoil.currying import partial

def _grab_virtuals(parent_repo):
    virtuals = {}
    for pkg in parent_repo:
        for virtualpkg in pkg.provides.evaluate_depset(pkg.use):
            virtuals.setdefault(virtualpkg.package, {}).setdefault(
                pkg.fullver, []).append(pkg)

    for pkg_dict in virtuals.itervalues():
        for full_ver, rdep_atoms in pkg_dict.iteritems():
            if len(rdep_atoms) == 1:
                pkg_dict[full_ver] = rdep_atoms[0].unversioned_atom
            else:
                pkg_dict[full_ver] = OrRestriction(
                    finalize=True, *[x.unversioned_atom for x in rdep_atoms])
    return virtuals

def repository(*args, **kwargs):
    r = vdb_repository(*args, **kwargs)
    return multiplex.tree(
        r, virtual.tree(partial(_grab_virtuals, r), livefs=True))

repository = vdb_repository
