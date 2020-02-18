"""
Extension of dask delayed with a tunable aware Delayed object.
"""

__all__ = [
    "delayed",
    "Tunable"
]


def to_delayed(obj, **attrs):
    """
    Converts a dask.Delayed object into a lyncs.Delayed object with parent the type of the object.
    """
    from dask.delayed import Delayed as DaskDelayed
    if isinstance(obj, Delayed):
        return obj

    elif isinstance(obj, DaskDelayed):
        from inspect import ismethod
        
        def wrap_func(func):
            def wrapped(*args, **kwargs):
                return to_delayed(func(*args, **kwargs), **attrs)
            return wrapped

        obj_attrs = {}
        for attr in dir(type(obj)):
            if attr not in dir(Delayed):
                if hasattr(obj, attr) and ismethod(getattr(obj, attr)):
                    obj_attrs[attr] = wrap_func(getattr(type(obj), attr))
        obj_attrs["__slots__"] = type(obj).__slots__

        obj_attrs.update(attrs)
        return type(type(obj).__name__, (Delayed, type(obj)), obj_attrs)(obj)

    else:
        return obj
    

    
def delayed(*args, **kwargs):
    """
    Equivalent to dask.delayed, but returns a lyncs.Delayed instead of a dask.Delayed object. 
    For help see dask.delayed.
    """
    from dask import delayed as dask_delayed
    return to_delayed(dask_delayed(*args, pure=True, **kwargs))


def is_tunable(obj):
    "Tells whether an object is tunable"
    if isinstance(obj, (list, tuple)):
        if len(obj) == 0: return False
        else: return is_tunable(obj[0]) or is_tunable(obj[1:])
    else:
        if isinstance(obj, Tunable): return obj.tunable is True
        else: return False

        
class Delayed:
    """
    A lyncs.Delayed object is the same as a dask.Delayed object that also implements a tuning step.
    If in the dask graph there is an object of type Tunable, this will be tuned.
    The tune step is performed before any graph optimization or calculation.
    """
    def __init__(self, obj):
        self.__setstate__(obj.__getstate__())
                          
    
    def tune(self, **kwargs):
        if not self.tunable: return
        
        from dask.delayed import DelayedAttr
        if isinstance(self, DelayedAttr):
            return self._obj.compute().tune(key=self._attr)
        pass


    @property
    def tunable(self):
        return is_tunable(list(self.dask.values()))

    @property
    def tunable_items(self):
        return {key:val for key,val in self.dask.items() if is_tunable(val)}.items()

    
    def compute(self, *args, tune=True, tune_kwargs={}, **kwargs):
        """
        Same as dask.compute but calls tune first. See dask.delayed.compute for help.
        
        Parameters
        ----------
        tune_kwargs: dict
            Kwargs that will be passed to the tune function.
        """
        if tune: self.tune(**tune_kwargs)
        return super().compute(*args, **kwargs)
    

    def visualize(self, mark_tunable="red", **kwargs):
        if mark_tunable:
            kwargs["data_attributes"] = { k: {"color": mark_tunable,
                                              "label": ", ".join(v.tunable_options.keys()),
                                              "fontcolor": mark_tunable,
                                              "fontsize": "12",
                                             }
                                          for k,v in self.tunable_items if isinstance(v,Tunable) }
        return super().visualize(**kwargs)

    
    def __repr__(self):
        ret = super().__repr__()
        if self.tunable: ret = "Tunable"+ret
        return ret


class NotTuned(Exception):
    pass

    
class Tunable:
    """
    A base class for tunable objects.
    """
    
    __slots__ = [
        "_tunable_options",
        "_tuned_options",
        "_tuning",
        "_raise_not_tuned",
    ]
    
    def __init__(
            self,
            tunable_options = {},
            tuned_options = {},
            **kwargs
    ):
        self._tunable_options = {}
        self._tuned_options = {}
        self._tuning = False
        
        for key,val in tunable_options.items():
            self.add_tunable_option(key,val)

        for key,val in kwargs.items():
            if isinstance(val,TunableOption):
                self.add_tunable_option(key,val)
            else:
                self.add_tuned_option(key,val)
                
        for key,val in tuned_options.items():
            self.add_tuned_option(key,val)

            
    @property
    def tunable(self):
        return bool(self.tunable_options)

    
    @property
    def tuned(self):
        return not self.tunable


    @property
    def tuning(self):
        return self._tuning

    
    @property
    def tunable_options(self):
        if hasattr(self, "_tunable_options"):
            return self._tunable_options.copy()
        else:
            return {}

    
    @property
    def tuned_options(self):
        if hasattr(self, "_tuned_options"):
            return self._tuned_options.copy()
        else:
            return {}


    def add_tunable_option(self, key, val):
        "Adds a tunable option where key is the name and val is the default value."
        assert key not in self.tunable_options, "A tunable options with the given name already exist."
        assert key not in self.tuned_options, "A tuned options with the given name already exist."
            
        self._tunable_options[key] = val if isinstance(val, TunableOption) else TunableOption(val)


    def add_tuned_option(self, key, val):
        "Adds a tunde option where key is the name and val is the value."
        assert key not in self.tuned_options, "A tuned options with the given name already exist."
        
        if key in self.tunable_options:
            setattr(self,key,val)
        else:
            self._tuned_options[key] = val

        

    def tune(self, key=None, **kwargs):
        """
        Tunes a tunable option.
        
        Parameters
        ----------
        key: the name of the tunable option to tune.
           If key is None then all the tunable options are tuned.
        callback: a function to call for the tuning. 
           The function will be called as (key=key, value=value, **kwargs)

        """
        if key is None:
            for key in self.tunable_options:
                self.tune(key, **kwargs)
            return
        
        elif key in self.tuned_options:
            return self.tuned_options[key]

        assert key in self.tunable_options, "Option %s not found" % key

        self._tuning = True
        try:
            callback = kwargs.get("callback", None)
            if callback is not None:
                setattr(self, key, callback(key=key,value=value,**kwargs))
            else:
                setattr(self, key, self.tunable_options[key].get())
            
        except:
            self._tuning = False
            raise
        return self.tuned_options[key]

        
    def __getattr__(self, key):
        if key not in Tunable.__slots__ and (key in self.tunable_options or key in self.tuned_options):
            if key in self.tunable_options:
                if self._raise_not_tuned:
                    raise NotTuned
                else:
                    return delayed(self).__getattr__(key)
                
            if key in self.tuned_options:
                return self._tuned_options[key]
        else:
            raise AttributeError("Not a tunable option %s"%key)


    def __setattr__(self, key, value):
        if key not in Tunable.__slots__ and (key in self.tunable_options or key in self.tuned_options):
            if key in self.tunable_options:
                assert self.tunable_options[key].compatible(value), """
                Value not compatible with %s""" % self.tunable_options[key]
                del self._tunable_options[key]
                self._tuned_options[key] = value
            else:
                assert False, "The value of a tuned option cannot be changed."
        else:
            super().__setattr__(key, value)

            
    def __repr__(self):
        from .utils import default_repr
        return default_repr(self)
        


class tunable_property(property):
    def __init__(self,func):
        def getter(cls):
            cls._raise_not_tuned = True
            try:
                return func(cls)
            except NotTuned:
                return delayed(getter)(delayed(cls))
            finally:
                cls._raise_not_tuned = False
        getter.__name__=func.__name__
        super().__init__(getter)
            

class TunableOption:
    "Base class for tunable options"
    def __init__(self, value):
        self._value = value

    @property
    def value(self):
        return self.get()
            
    def get(self):
        return self._value

    def compatible(self, value):
        return value == self.get()

    def __repr__(self):
        from .utils import default_repr
        return default_repr(self)


class Permutation(TunableOption):
    "A permutation of the given list/tuple"
    def __init__(self, value):
        assert isinstance(value, (tuple,list)), "A permutation must be initialized with a list/tuple"
        super().__init__(value)
    
    def compatible(self, value):
        from collections import Counter
        return len(self.get()) == len(value) and Counter(self.get()) == Counter(value)


class Choice(TunableOption):
    "One element of list/tuple"
    def __init__(self, value):
        assert isinstance(value, (tuple,list)), "A choice must be initialized with a list/tuple"
        assert len(value) > 0, "List cannot be empty"
        super().__init__(value)
    
    def compatible(self, value):
        return value in self.get()

    def get(self):
        return self._value[0]

class ChunksOf(TunableOption):
    "Chunks of a given shape"
    def __init__(self, value):
        if isinstance(value, (tuple,list)):
            assert all(isinstance(v, tuple) and len(v)==2 for v in value)
            shape = {key:val for key,val in value}
        elif isinstance(value, dict):
            shape = value
        super().__init__(shape)
    
    def compatible(self, value):
        chunks = ChunksOf(value)
        shape = self.get()
        # Here we ask for uniform distribution. Consider to allow for not uniform
        return all(key in shape and val<=shape[key] and shape[key]%val == 0 for key,val in chunks.get().items())
    
