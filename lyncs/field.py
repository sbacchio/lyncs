__all__ = [
    "Field",
]

from .tunable import Tunable, computable
from .field_methods import FieldMethods
from functools import wraps
from .tunable import visualize, compute, persist

class Field(Tunable, FieldMethods):
    _field_types = {
        "scalar": ["dims"],
        "vector": ["dims", "dofs"],
        "propagator": ["dims", "dofs", "dofs"],
        "gauge_links": ["dims", "n_dims", "gauge_dofs", "gauge_dofs"],
        }
    _default_field_type = "vector"
    _default_dtype = "complex128"
    
    def __init__(
            self,
            field = None,
            lattice = None,
            field_type = None,
            dtype = None,
            coords = {},
            fixed_options = {},
            zeros_init = False,
            **kwargs
    ):
        """
        A field defined on the lattice.
        
        Parameters
        ----------
        field : array_like or Field
            Values for this field. Must be an ``numpy.ndarray``, ndarray like,
            or castable to an ``ndarray``. A view of the array's data is used
            instead of a copy if possible. If instead it is a field object,
            then a copy of the field is made with appropriate transformations
            induced by the given parameters.
            E.g.
            Field(field=field, coords={'x':0}) selects values at x=0
            Field(field=field, axes_order=[...]) changes the axes_order if needed.
            etc...
        lattice: Lattice object.
            The lattice on which the field is defined.
        field_type: str or list(str).
            If str, then must be one of the labeled field types. See Field._field_types.
            If list, then a list of dimensions of lattice.
        dtype: str or numpy dtype compatible
           Data type of the field
        coords: dict, str or list of str
           Coordinates of the field, i.e. range of values for any of the dimensions.
           If dictionary, keys must be dimensions of the field and value can be integer, range, slice.
           Otherwise, it can be a label or a list of labels/dictionaries.
        fixed_options: dict
           Same as tunable options but with a fixed value.
        zeros_init: bool
           Initializes the field with zeros.
        kwargs: dict
           Extra paramters that will be passed to the child classes of the field during initialization.
        """
        from .lattice import default_lattice
        
        self.lattice = lattice if lattice is not None else \
                       field.lattice if isinstance(field, Field) else \
                       default_lattice()
        
        self.field_type = field_type if field_type is not None else \
                          field.field_type if isinstance(field, Field) else \
                          Field._default_field_type

        self.dtype = dtype if dtype is not None else \
                     field.dtype if hasattr(field, "dtype") else \
                     Field._default_dtype

        if isinstance(field, Field):
            for key,val in field.labels.items():
                try: self.label(key, **val)
                except AssertionError: pass
                
        if isinstance(field, Field):
            field_coords = field.coords
            for key in list(field_coords):
                if key not in self.axes:
                    field_coords.pop(key)
            self.coords = field_coords
        self.coords = coords

        from .tunable import Permutation, ChunksOf
        from collections import Counter

        self.add_option("axes_order", Permutation(self.axes), transformer=self._reorder)
        if len(set(self.axes))==1:
            self.axes_order = self.axes

        for key,count in Counter(self.axes).items():
            if count > 1:
                self.add_option(key+"_order", Permutation(list(range(count))))

        from numpy import prod
        chunks = [(key,val) for key, val in self.shape if val>1 and key in self.dims]
        self.add_option("chunks", ChunksOf(chunks), transformer=self._rechunk)
        if prod([val for key,val in chunks])==1:
            self.chunks = chunks

        # Loading dynamically methods and attributed from the field types in fields
        from importlib import import_module
        for name in self.dimensions:
            try:
                module = import_module(".fields.%s"%name, package="lyncs")
                for attr in module.__all__:
                    val = getattr(module, attr)
                    if attr == "__init__":
                        val(self, **kwargs)
                    else:
                        setattr(self, attr, val)
            except ModuleNotFoundError:
                pass

        fixed_options = fixed_options.copy()
        
        # Considering the remaining kwargs as fixed options
        for key, val in kwargs.items():
            assert key not in fixed_options, "Repeated fixed options %s" % key
            fixed_options[key] = val
            
        if "axes_order" in fixed_options:
            fixed_options["axes_order"] = self._expand(fixed_options["axes_order"])
            
        for key, val in fixed_options.items():
            assert key in self.options, "Unknown options %s" % key
            setattr(self, key, val)
            
        if zeros_init or field is None:
            self.zeros()
        else:
            self.field = field
        

    @property
    def lattice(self):
        from copy import copy
        return copy(self.__dict__.get("_lattice", None))
        
    @lattice.setter
    def	lattice(self, value):
        assert self.lattice is None, "Not allowed to change lattice, if needed ask to implement it"
        from .lattice import Lattice
        assert isinstance(value, Lattice)
        
        self._lattice = value


    @property
    def dtype(self):
        from copy import copy
        return copy(self.__dict__.get("_dtype", None))
    
    @dtype.setter
    def dtype(self, value):
        from numpy import dtype
        value = dtype(value)
        assert self.dtype is None or value == self.dtype, "dtype cannob be changed directly. Use astype."
        self._dtype = value


    @property
    def dims(self):
        return [key for key in self.axes if key in self.lattice.dims]

    
    @property
    def dofs(self):
        return [key for key in self.axes if key not in self.lattice.dims]


    def _expand(self, prop):
        "Expands a lattice/field property into the fundamental dimensions"
        def __expand(prop):
            if isinstance(prop,(list,tuple,set)):
                return " ".join([__expand(key) for key in prop])
            elif prop in self.lattice and isinstance(self.lattice[prop], int):
                return prop
            else:
                if prop in ["dims", "dofs"] and self.field_type is not None:
                    return " ".join([__expand(key) for key in getattr(self,prop)])
                elif prop in self.lattice:
                    return " ".join([__expand(key) for key in self.lattice[prop]])
                else:
                    return " ".join([__expand(key) for key in self._field_types[prop]])
                
        return __expand(prop).split()
    
    
    @property
    def dimensions(self):
        """
        Returns all the possible dimensions valid for the field.
        """
        dims = set()
        
        def add(key):
            if isinstance(key, (list, tuple, dict)):
                for k in key: add(k)
            elif isinstance(key, str):
                dims.add(key)
                if key in self.lattice: add(self.lattice[key])
                elif key in self._field_types: add(self._field_types[key])
                    
        add(self.field_type)
        
        for prop in self.lattice.properties:
            names = self._expand(prop)
            if set(names).issubset(dims): dims.add(prop)
            
        dims = list(dims)
        dims.sort()
        return dims


    @property
    def axes(self):
        """
        Returns the list of fundamental dimensions. The order is not significant.
        """
        return list(self.__dict__.get("_axes", []))
    
    
    @property
    def shape(self):
        """
        Returns the list of dimensions with size. The order is not significant.
        """
        def get_size(key):
            if key in self.coords:
                return len(self.coords[key])
            else:
                return self.lattice[key]
                
        return [(key, get_size(key)) for key in self.axes]
    
    
    @property
    def field_type(self):
        from copy import copy
        return copy(self.__dict__.get("_field_type", None))
    

    @field_type.setter
    def	field_type(self, value):
        assert self.field_type is None, "Not allowed to change field_type"
        def is_known(self, key):
            if isinstance(key, (list, tuple)):
                return all(is_known(self,k) for k in key)
            elif isinstance(key, str):
                return key in self.lattice.__dir__() or key in self._field_types
            else:
                assert False, "Got key that is neither list or str, %s" % key
                
        assert is_known(self, value), "Got unknown field type"

        if not isinstance(value, str) or value not in self._field_types:
            target = sorted(self._expand(value))
            for field_type in self._field_types:
                try:
                    if sorted(self._expand(field_type)) == target:
                        value = field_type
                        break
                except:
                    pass

        self._axes = self._expand(value)
        self._field_type = value


    @property
    def coords(self):
        return dict(self.__dict__.get("_coords", {}))

    
    @coords.setter
    def coords(self, coords):
        assert self.field is None, "Not allowed to change coords. Use get."
        _coords = {}
        def unpack(coords):
            if isinstance(coords, (tuple, list)):
                for coord in coords:
                    unpack(coord)
            elif isinstance(coords, str) and coords in self.labels:
                unpack(self.labels[coords])
            elif isinstance(coords, dict):
                _coords.update(coords)
            else:
                assert False, "Not implemented"
        unpack(coords)

        coords = _coords
        _coords = {}
        for key, val in coords.items():
            assert key in self.dimensions, "Unknown dimesion %s" % key
            dims = self._expand(key)
            for dim in dims:
                assert dim not in _coords or _coords[dim]==val, "Setting multiple time the same dimension not allowed"
                
                try:
                    assert len(list(val)) > 0, "Empty list not allowed"
                except TypeError:
                    from .utils import to_list
                    val = to_list(val)
                    
                _coords[dim]=val
                
        for key, val in self.coords.items():
            assert key not in _coords or _coords[key]==val, "Cannot change value of fixed coordinate %s" % key
            _coords[key] = val
            
        self._coords = _coords


    @property
    def field(self):
        try:
            from dask.array import Array
            from .tunable import LyncsMethodsMixin
            if not isinstance(self._field, Array):
                self._field = self._field.compute(tune=False)
            elif isinstance(self._field, Array):
                import warnings
                if self._field.shape != self.field_shape:
                    warnings.warn("Mistmatch between computed and real field shape")
                if self._field.chunksize != self.field_chunks:
                    warnings.warn("Mistmatch between computed and real field chunks")
                if self._field.dtype != self.dtype:
                    warnings.warn("Mistmatch between computed %s and real field %s" % (self.dtype, self._field.dtype))
            return self._field
        except AttributeError:
            return None

    @field.setter
    def field(self, value):
        from .tunable import Delayed, delayed, computable
        from dask.array import Array
        
        if isinstance(value, Field):
            field = value.field
            
            if self.coords != value.coords:
                field = self._getitem(field, self.coords, value.coords, value.axes_order)

            from collections import Counter
            if Counter(self.axes) != Counter(value.axes):
                field = self._squeeze(field, self.axes, value.axes_order, value.field_shape)

            if self.dtype != value.dtype:
                field = field.astype(value)
                
            for key,val in value.options.items():
                if key in self.tunable_options:
                    setattr(self, key, val)
                elif key in self.fixed_options:
                    field = self.transform(key, field, val)
                
            self.field = field
            
        elif isinstance(value, Delayed):
            self._field = value

        elif isinstance(value, Array):
            assert type(self.field_shape) is tuple, "Field order not defined yet"
            assert self.field_shape == value.shape, """
            Shape mismatch:
            field_shape = %s
            new_field_shape = %s
            """ % (self.field_shape, value.shape)
            
            if isinstance(self.field_chunks, Delayed):
                self.chunks = {key: val for key, val in zip(self.axes_order, value.chunksize)}
            else:
                value=value.rechunk(self.field_chunks)
                
            self._field = value

        else:
            # TODO specialize
            assert False, "Not implemented yet"

            
    @property
    def field_shape(self):
        @computable
        def field_shape(axes_order):
            shape = []
            keys, vals = zip(*self.shape)
            keys, vals = list(keys), list(vals)
            for key in axes_order:
                idx = keys.index(key)
                shape.append(vals[idx])
                keys.pop(idx)
                vals.pop(idx)
            return tuple(shape)
        
        return field_shape(self.axes_order)


    @property
    def field_chunks(self):
        @computable
        def field_chunks(chunks, axes_order):
            keys, vals = zip(*self.shape)
            Skeys, Svals = list(keys), list(vals)
            keys, vals = zip(*chunks)
            Ckeys, Cvals = list(keys), list(vals)
            chunks = []
            for key in axes_order:
                if key in Ckeys:
                    idx = Ckeys.index(key)
                    chunks.append(Cvals[idx])
                    Ckeys.pop(idx)
                    Cvals.pop(idx)
                    idx = Skeys.index(key)
                    Skeys.pop(idx)
                    Svals.pop(idx)
                else:
                    idx = Skeys.index(key)
                    chunks.append(Svals[idx])
                    Skeys.pop(idx)
                    Svals.pop(idx)
                    
            return tuple(chunks)

        return field_chunks(self.chunks, self.axes_order)
        

    @property
    def size(self):
        """
        Returns the number of elements in the field.
        """
        prod = 1
        for t in self.shape: prod*=t[1]
        return prod


    @property
    def byte_size(self):
        """
        Returns the size of the field in bytes
        """
        return self.size*self.dtype.itemsize
    
    
    @property
    def labels(self):
        return dict(self.__dict__.get("_labels",{}))

    
    def label(self, name, **coords):
        """
        Labels a given set of coordinates.
        Labels are accessible via __getitem__.

        E.g.
        
        field.label("source", x=0, y=0, z=0, t=0)
        dofs = field["source"]
        
        Parameters
        ----------
        name: (str)
           Name of the label.
        coords: (dict)
           The coordinate of a subset of dimensions.
        """
        if not hasattr(self, "_labels"): self._labels={}
        assert all([key in self.dimensions for key in coords]), "Some of the dimensions are not known"
        self._labels[name] = coords


    @property
    def dask(self):
        return self.field.dask

    
    @wraps(persist)
    def compute(self, **kwargs):
        "NOTE: here we follow the dask.delayed convention. I.e. compute=persist and result=compute"
        self.tune(**kwargs.pop("tune_kwargs",{}))
        self.field = self.field.persist(**kwargs)
        
        
    @wraps(compute)
    def result(self, **kwargs):
        "NOTE: here we follow the dask.delayed convention. I.e. compute=persist and result=compute"
        self.compute()
        return self.field.compute()


    @wraps(visualize)
    def visualize(self, **kwargs):
        return self.field.visualize(**kwargs)

        
    def load(
            self,
            filename,
            format = None,
            **info,
    ):
        """
        Loads data from file.
        
        Parameters
        ----------
        filename: (str) path and filename of the data file to read.
        format: (str) format of the file to read (see load for help).
        info: information needed to perform the reading.
        """
        from .io import file_manager
        from .tunable import computable
        from dask.array import from_delayed
        
        io = file_manager(filename, format=format, field=self, **info)

        @computable
        def read_field(shape, chunks):
            from dask.highlevelgraph import HighLevelGraph
            from dask.array.core import normalize_chunks, Array
            from itertools import product
            
            chunks = normalize_chunks(chunks, shape=shape)
            chunks_id = list(product(*[range(len(bd)) for bd in chunks]))

            reads = [io.read(chunk_id) for chunk_id in chunks_id]
            
            keys = [(filename, *chunk_id) for chunk_id in chunks_id]
            vals = [read.key for read in reads]
            dsk = dict(zip(keys, vals))

            graph = HighLevelGraph.from_collections(filename, dsk, dependencies=reads)

            return Array(graph, filename, chunks, dtype=self.dtype)
        
        self.field = read_field(self.field_shape, self.field_chunks)
        

    def save(
            filename,
            format = None,
            **info,
    ):
        """
        Saves data into file.
        
        Parameters
        ----------
        filename: (str) path and filename of the data file to save.
        format: (str) format of the file to save (see load for help).
        info: information needed to perform the writing.
        """
        from .io import save_field
        save(self, filename, format=format, field=overwrite)


    def zeros(self):
        """
        Initialize the field with zeros.
        """
        from .tunable import computable
        from dask.array import zeros

        @computable
        def zero_field(*args, **kwargs):
            return zeros(*args, **kwargs)
        
        self.field = zero_field(
            shape = self.field_shape,
            chunks = self.field_chunks,
            dtype = self.dtype,
        )


    def __repr__(self):
        from .utils import default_repr
        return default_repr(self)
    

    def __dask_tokenize__(self):
        import uuid
        from dask.base import normalize_token
        if not hasattr(self, "_unique_id"): self._unique_id = str(uuid.uuid4())
            
        return normalize_token(
            (type(self), self.lattice, self.field_type, self._unique_id)
        )
    
