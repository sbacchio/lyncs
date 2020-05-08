"""
Base class of the Field type that implements
the interface to the Lattice class.
"""
# pylint: disable=C0303,C0330

__all__ = [
    "BaseField",
]

import re
from collections import Counter
from numpy import arange
from .types.base import FieldType
from ..utils import default_repr, compute_property


class BaseField:
    """
    Base class of the Field type that implements
    the interface to the Lattice class and deduce
    the list of Field types from the field axes.
    
    The list of types are accessible via field.types
    """

    __repr__ = default_repr

    def __init__(self, field=None, axes=None, lattice=None, coords=None, **kwargs):
        """
        Initializes the field class.
        
        Parameters
        ----------
        field: Field
            If given, then the missing parameters are deduced from it.
        axes: list(str)
            List of axes of the field.
        lattice: Lattice
            The lattice on which the field is defined.
        kwargs: dict
            Extra parameters that will be passed to the field types.
        """

        from ..lattice import Lattice, default_lattice

        assert lattice is None or isinstance(
            lattice, Lattice
        ), "lattice must be of Lattice type"

        coords = coords or ()

        if isinstance(field, BaseField):
            self._lattice = (lattice or field.lattice).freeze()
            self._axes = self.lattice.expand(axes or field.axes)
            self._coords = self.lattice.coordinates.resolve(
                *coords, **dict(field.coords)
            )
        else:
            self._lattice = (lattice or default_lattice()).freeze()
            self._axes = self.lattice.expand(axes or ())
            self._coords = self.lattice.coordinates.resolve(*coords)

        self._types = tuple(
            (name, ftype)
            for name, ftype in FieldType.s.items()
            if isinstance(self, ftype)
        )

        for _, ftype in self.types:
            try:
                ftype.__init__(self, **kwargs)
            except AttributeError:
                continue

        # ordering types by relevance
        self._types = tuple(
            (name, ftype)
            for name, ftype in sorted(
                self.types,
                key=lambda item: len(self.lattice.expand(item[1].axes.expand)),
                reverse=True,
            )
        )

    @property
    def lattice(self):
        "The lattice on which the field is defined."
        return self._lattice

    @property
    def axes(self):
        "List of axes of the field. Order is not significant. See field.axes_order."
        return self._axes

    @compute_property
    def dims(self):
        "List of dims in the field axes"
        return tuple(key for key in self.axes if key in self.lattice.dims)

    @compute_property
    def dofs(self):
        "List of dofs in the field axes"
        return tuple(key for key in self.axes if key in self.lattice.dofs)

    @compute_property
    def indeces(self):
        """
        List of indeces of the field. Similar to .axes but repeted axis are numerated.
        Order is not significant. See field.indeces_order.
        """
        counts = Counter(self.axes)
        idxs = {axis: 0 for axis in counts}
        indeces = []
        for axis in self.axes:
            if counts[axis] > 1:
                indeces.append(axis + "_" + str(idxs[axis]))
                idxs[axis] += 1
            else:
                indeces.append(axis)
        assert len(set(indeces)) == len(indeces), "Trivial assertion"

        return tuple(indeces)

    @compute_property
    def types(self):
        "List of field types that the field is instance of ordered per relevance"
        return self._types

    @property
    def coords(self):
        "List of coordinates of the field."
        return self._coords

    @compute_property
    def shape(self):
        "Returns the list of indeces with size. Order is not significant."

        def get_size(key):
            axis = re.sub("_[0-9]+$", "", key)
            if key in self.coords:
                return len(arange(self.lattice[axis])[self.coords[key]])
            return self.lattice[axis]

        return tuple((key, get_size(key)) for key in self.indeces)

    def __dir__(self):
        attrs = set(super().__dir__())
        for _, ftype in self.types:
            attrs.update((key for key in dir(ftype) if not key.startswith("_")))
        return sorted(attrs)

    def __getattr__(self, key):
        "Looks up for methods in the field types"
        for _, ftype in self.types:
            if isinstance(self, ftype):
                try:
                    return getattr(ftype, key).__get__(self)
                except AttributeError:
                    continue

        raise AttributeError

    @property
    def type(self):
        "Name of the Field. Equivalent to the most relevant field type."
        return self.types[0][0]


FieldType.Field = BaseField
