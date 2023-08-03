"""Define the ParallelGroup class."""

from openmdao.core.group import Group
from openmdao.utils.om_warnings import issue_warning


class ParallelGroup(Group):
    """
    Class used to group systems together to be executed in parallel.

    Parameters
    ----------
    **kwargs : dict
        Dict of arguments available here and in all descendants of this Group.
    """

    def __init__(self, **kwargs):
        """
        Set the mpi_proc_allocator option to 'parallel'.
        """
        super().__init__(**kwargs)
        self._mpi_proc_allocator.parallel = True

    def _configure(self):
        """
        Configure our model recursively to assign any children settings.

        Highest system's settings take precedence.
        """
        super()._configure()
        if self.comm.size > 1:
            self._has_guess = any(self.comm.allgather(self._has_guess))

    def _get_sys_promotion_tree(self, tree):
        tree = super()._get_sys_promotion_tree(tree)

        if self.comm.size > 1:
            prefix = self.pathname + '.' if self.pathname else ''
            subtree = {n: data for n, data in tree.items() if n.startswith(prefix)}
            for sub in self.comm.allgather(subtree):  # TODO: make this more efficient
                for n, data in sub.items():
                    if n not in tree:
                        tree[n] = data

        return tree

    def _ordered_comp_name_iter(self):
        """
        Yield contained component pathnames in order of execution.

        For components within ParallelGroups, true execution order is unknown so components
        will be ordered by rank within a ParallelGroup.
        """
        if self.comm.size > 1:
            names = []
            for s in self._subsystems_myproc:
                if isinstance(s, Group):
                    names.extend(s._ordered_comp_name_iter())
                else:
                    names.append(s.pathname)
            seen = set()
            for ranknames in self.comm.allgather(names):
                for name in ranknames:
                    if name not in seen:
                        yield name
                        seen.add(name)
        else:
            yield from super()._ordered_comp_name_iter()

    def _check_order(self, reorder=True, recurse=True, out_of_order=None):
        """
        Check if auto ordering is needed and if so, set the order appropriately.

        Parameters
        ----------
        reorder : bool
            If True, reorder the subsystems based on the new order.  Otherwise
            just return the out-of-order connections.
        recurse : bool
            If True, call this method on all subgroups.
        out_of_order : dict
            Lists of out-of-order connections keyed by group pathname.

        Returns
        -------
        dict
            Lists of out-of-order connections keyed by group pathname.
        """
        if self.options['auto_order']:
            issue_warning("auto_order is not supported in ParallelGroup. "
                          "Ignoring auto_order option.", prefix=self.msginfo)

        if out_of_order is None:
            out_of_order = {}

        if recurse:
            for s in self._subgroups_myproc:
                s._check_order(reorder, recurse, out_of_order)

        return out_of_order

    def _declared_partials_iter(self):
        """
        Iterate over all declared partials.

        Yields
        ------
        (key, meta) : (key, dict)
            key: a tuple of the form (of, wrt)
            meta: a dict containing the partial metadata
        """
        if self.comm.size > 1:
            if self._gather_full_data():
                gathered = self.comm.allgather(self._subjacs_info)
            else:
                gathered = self.comm.allgather({})
            seen = set()
            for rankdict in gathered:
                for key, meta in rankdict.items():
                    if key not in seen:
                        yield key, meta
                        seen.add(key)
        else:
            yield from super()._declared_partials_iter()

    def _get_missing_partials(self, missing):
        """
        Return a list of (of, wrt) tuples for which derivatives have not been declared.

        Parameters
        ----------
        missing : dict
            Dictionary containing list of missing derivatives keyed by system pathname.
        """
        if self.comm.size > 1:
            msng = {}
            super()._get_missing_partials(msng)
            if self._gather_full_data():
                gathered = self.comm.allgather(msng)
            else:
                gathered = self.comm.allgather({})
            seen = set()
            for rankdict in gathered:
                for sysname, mset in rankdict.items():
                    if sysname not in seen:
                        missing[sysname] = mset
                        seen.add(sysname)
        else:
            super()._get_missing_partials(missing)
