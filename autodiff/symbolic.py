import copy
import numpy as np
import theano
import theano.tensor as tt
from inspect import getargspec

from autodiff.context import Context
from autodiff.compat import OrderedDict
import autodiff.constant
import autodiff.utils as utils


class Symbolic(object):
    def __init__(self, pyfn, borrow=None, force_floatX=False):
        """
        Arguments
        ---------

        pyfn : Python function
            The function that will be traced. The will attempt to build
            symbolic representations of any variables referenced in or created
            by this function.

        borrow : tuple of objects
            If an object in this tuple is encountered while tracing the
            function, then its symbolic representation will alias that object's
            memory location. This means that *inplace* operations on the Python
            (likely NumPy) object will affect the symbolic function.

        force_floatX : bool
            If True, floats and float NumPy ndarrays will be cast to the dtype
            specified at theano.config.floatX when forming symbolic shared
            variables, if they do not have it already. Objects in `borrowable`
            are never cast.

        """
        # make deepcopy of pyfn because we might change its defaults
        self._pyfn = copy.deepcopy(pyfn)

        self.s_vars = OrderedDict()
        self.s_args = OrderedDict()
        self.s_results = OrderedDict()
        self._cache = dict()
        self.force_floatX = force_floatX
        self.borrow = utils.as_seq(borrow, tuple)
        self.argspec = getargspec(self._pyfn)

        # replace integer defaults in pyfn to avoid tracing problems
        if self._pyfn.func_defaults:
            a = getargspec(self._pyfn)
            new_defaults = []
            for n, d in zip(reversed(a.args), reversed(a.defaults)):
                if type(d) is int and -5 <= d <= 256:
                    new_defaults.append(np.int_(d))
                else:
                    new_defaults.append(d)
            self._pyfn.func_defaults = tuple(new_defaults)

    def __call__(self, *args, **kwargs):
        return self.get_theano_vars(args, kwargs)

    def reset(self):
        self.s_vars.clear()
        self.s_args.clear()
        self.s_results.clear()
        self.cache.clear()

    @property
    def pyfn(self):
        return self._pyfn

    @property
    def cache(self):
        return self._cache

    def cache_id(self, args, kwargs):
        """
        Generates a unique id for caching a function
        """
        raise NotImplementedError

    def trace(self, args=None, kwargs=None):
        """
        Given args and kwargs, call the Python function and get its
        symbolic representation.

        Three ordered dictionaries are maintained:
            self.s_vars   : {id(obj) : sym_var}
                            Contains all symbolic variables traced during
                            function execution, indexed by the id of the
                            corresponding Python object.

            self.s_args   : {arg name : sym_var}
                            Contains all symbolic inputs to the function,
                            indexed by the argument name.

            self.s_results : {id(obj) : sym_var}
                            Contains the symbolic function results, indexed by
                            the id of the corresponding Python object.

            The dictionaries are cleared every time this method is run.

        """
        if args is None:
            args = ()
        elif not isinstance(args, tuple):
            raise TypeError('args must be a tuple')

        if kwargs is None:
            kwargs = dict()
        elif not isinstance(kwargs, dict):
            raise TypeError('args must be a dict')

        def check(name, i):
            if type(i) is int and -5 <= i <= 256:
                i = np.int_(i)
            elif isinstance(i, (list, tuple, dict)):
                raise TypeError(
                    'Function arguments can not be containers (received '
                    '{0} for argument \'{1}\').'.format(i, name))
            return i

        args = list(args)

        for i, (n, a) in enumerate(zip(self.argspec.args, args)):
            args[i] = check(n, a)

        for i, a in enumerate(args[len(self.argspec.args):]):
            args[len(self.argspec.args) + i] = check(self.argspec.varargs, a)

        for k, v in kwargs.iteritems():
            kwargs[k] = check(k, v)

        args = tuple(args)

        # clear symbolic dictionaries
        self.s_vars.clear()
        self.s_args.clear()
        self.s_results.clear()

        # trace the function
        autodiff.constant.clear_constants()
        c = Context(borrowable=self.borrow, force_floatX=self.force_floatX)
        results = c.call(self.pyfn, args, kwargs)

        # collect symbolic variables in s_vars
        self.s_vars.update(c.svars)

        # collect symbolic arguments in s_args
        callargs = utils.orderedcallargs(self.pyfn, *args, **kwargs)

        for name, arg in callargs.iteritems():

            # collect variable args
            if name == self.argspec.varargs:
                self.s_args[name] = ()
                for i, a in enumerate(arg):
                    try:
                        self.s_args[name] += (self.s_vars[id(a)],)
                        self.s_args[name][-1].name = '{0}_{1}'.format(name, i)
                    except KeyError:
                        raise KeyError('Unable to trace item {0} of variable '
                                       'argument \'{1}\'.'.format(i, name))
                    except:
                        raise

            # collect variable kwargs
            elif name == self.argspec.keywords:
                for n, a in arg.iteritems():
                    try:
                        self.s_args[n] = self.s_vars[id(a)]
                        self.s_args[n].name = n
                    except KeyError:
                        raise KeyError('Unable to trace argument '
                                       '\'{0}\'.'.format(n))
                    except:
                        raise

            # collect positional args
            else:
                try:
                    self.s_args[name] = self.s_vars[id(arg)]
                    self.s_args[name].name = name
                except KeyError:
                    raise KeyError('Unable to trace argument '
                                   '\'{0}\'.'.format(name))
                except:
                    raise

        # collect symbolic results in s_results
        if not isinstance(results, tuple):
            results = [results]
        for i, r in enumerate(results):
            try:
                self.s_results[id(r)] = self.s_vars[id(r)]
            except KeyError:
                raise KeyError('Unable to trace result #{0} '
                               '(indexed from 1).'.format(i + 1))
            except:
                raise

    def get_theano_vars(self, args, kwargs):
        """
        Returns a dict containing inputs, outputs and givens corresponding to
        the Theano version of the pyfn.

        """

        # trace the function
        self.trace(args, kwargs)

        # get symbolic inputs corresponding to shared inputs in s_args
        s_memo = OrderedDict(
            (arg, arg.type(name=arg.name))
            for arg in utils.flat_from_doc(self.s_args.values()))

        # get new graph, replacing shared inputs with symbolic ones
        graph = theano.gof.graph.clone_get_equiv(
            theano.gof.graph.inputs(self.s_results.values()),
            self.s_results.values(),
            memo=s_memo.copy())

        # get symbolic outputs
        outputs = tuple([graph[o] for o in self.s_results.values()])

        defaults = dict()
        if self.argspec.defaults:
            defaults.update(zip(reversed(self.argspec.args),
                                reversed(self.argspec.defaults)))
        inputs = tuple([theano.Param(variable=i,
                                     default=defaults.get(i.name, None),
                                     name=i.name)
                        for i in s_memo.values()])

        theano_vars = {'inputs': inputs,
                       'outputs': outputs,
                       'graph': graph}

        return theano_vars

    def get_theano_args(self, args, kwargs):
        """
        Theano can't accept variable arguments; if varargs are present, expand
        them.
        """
        if self.argspec.varargs:
            callargs = utils.orderedcallargs(self.pyfn, *args, **kwargs)
            pos_args = [callargs[arg] for arg in self.argspec.args]
            pos_args.extend(callargs.get(self.argspec.varargs, ()))
            # kw_args = callargs.get(self.argspec.keywords, {})
        else:
            pos_args = args
        return pos_args, kwargs

    def get_symbolic_arg(self, x):
        """
        Retrieve the symbolic version of x.

        x : python object or string

        If x is a string, it is matched to the names of the function arguments.
        If x is an object, it must have been traced by the Symbolic class.
        If x is a small int, raises an error.
        """
        if type(x) is int and -5 <= x <= 256:
            raise ValueError(
                'Small integer arguments can not be traced selectively. '
                'Either recast or redesign your function.')
        elif isinstance(x, basestring):
            if x in self.s_args:
                return self.s_args[x]
            else:
                raise ValueError(
                    'Requested the symbolic variable shadowing object {0}'
                    ', but it was not traced.'.format(repr(x)))
        else:
            if id(x) in self.s_vars:
                return self.s_vars[id(x)]
            else:
                raise ValueError(
                    'Requested the symbolic variable shadowing object {0}'
                    ', but it was not traced.'.format(repr(x)))


class Function(Symbolic):

    def __call__(self, *args, **kwargs):
        return self.call(*args, **kwargs)

    def cache_id(self, args=None, kwargs=None):
        if args is None:
            args = ()
        if kwargs is None:
            kwargs = {}
        callargs = utils.orderedcallargs(self.pyfn, *args, **kwargs)
        return len(callargs.get(self.argspec.varargs, ()))

    def compile_function(self, args, kwargs):
        theano_vars = self.get_theano_vars(args, kwargs)

        inputs = theano_vars['inputs']
        outputs = theano_vars['outputs']

        if len(outputs) == 1:
            outputs = outputs[0]

        # compile function
        fn = theano.function(inputs=inputs,
                             outputs=outputs,
                             on_unused_input='ignore')

        # store in cache
        self.cache[self.cache_id(args, kwargs)] = fn

        return fn

    def call(self, *args, **kwargs):
        # try to retrieve function from cache; otherwise compile
        fn = self.cache.get(self.cache_id(args, kwargs))
        if not fn:
            fn = self.compile_function(args, kwargs)

        pos_args, kw_args = self.get_theano_args(args, kwargs)
        return fn(*pos_args, **kw_args)


class Gradient(Function):

    def __init__(self, pyfn, wrt=None, borrow=None, force_floatX=False):
        super(Gradient, self).__init__(pyfn=pyfn,
                                       borrow=borrow,
                                       force_floatX=force_floatX)
        self.wrt = utils.as_seq(wrt)

    def compile_function(self, args, kwargs):
        theano_vars = self.get_theano_vars(args, kwargs)

        inputs = theano_vars['inputs']
        outputs = theano_vars['outputs']
        graph = theano_vars['graph']

        # get wrt variables. If none were specified, use inputs.
        if len(self.wrt) == 0:
            wrt = [i.variable for i in inputs]
        else:
            wrt = [graph[self.get_symbolic_arg(w)] for w in self.wrt]

        grads = [tt.grad(o, wrt=wrt) for o in outputs]

        if len(grads) == 1:
            grads = grads[0]

        # compile function
        fn = theano.function(inputs=inputs,
                             outputs=grads,
                             on_unused_input='ignore')

        # store in cache
        self.cache[self.cache_id(args, kwargs)] = fn

        return fn


class HessianVector(Function):

    def __init__(self, pyfn, wrt=None, borrow=None, force_floatX=False):
        super(Gradient, self).__init__(pyfn=pyfn,
                                       borrow=borrow,
                                       force_floatX=force_floatX)
        self.wrt = utils.as_seq(wrt)

    def compile_function(self, args, kwargs):
        kwargs = kwargs.copy()
        kwargs.pop('_vectors', None)

        theano_vars = self.get_theano_vars(args, kwargs)

        inputs = theano_vars['inputs']
        outputs = theano_vars['outputs']
        graph = theano_vars['graph']

        # get wrt variables. If none were specified, use inputs.
        if len(self.wrt) == 0:
            wrt = [i.variable for i in inputs]
        else:
            wrt = [graph[self.get_symbolic_arg(w)] for w in self.wrt]

        grads = [tt.grad(o, wrt=wrt) for o in outputs]

        sym_vecs = [tt.TensorType(broadcastable=[False]*w.ndim)() for w in wrt]
        hess_vec = tt.Rop(grads, wrt, sym_vecs)
        inputs.extend(sym_vecs)

        if len(hess_vec) == 1:
            hess_vec = hess_vec[0]

        # compile function
        fn = theano.function(inputs=inputs,
                             outputs=hess_vec,
                             on_unused_input='ignore')

        # store in cache
        self.cache[self.cache_id(args, kwargs)] = fn

        def wrapper(*args, **kwargs):
            if '_vectors' in kwargs:
                vectors = kwargs.pop('_vectors')
            else:
                raise ValueError(
                    'Vectors must be passed the keyword \'_vectors\'.')
            vectors = utils.as_seq(vectors, tuple)

            if len(vectors) != len(self.wrt):
                raise ValueError('Expected {0} items in _vectors; received '
                                 '{1}.'.format(len(self.wrt), len(vectors)))

            all_args = args + vectors

            return fn(*all_args, **kwargs)

        return wrapper(fn)


class VectorArgs(Function):
    def __init__(self,
                 pyfn,
                 init_args,
                 init_kwargs,
                 compile_fn=False,
                 compile_grad=False,
                 compile_hv=False,
                 borrow=None,
                 force_floatX=False):
        if not (compile_fn or compile_grad or compile_hv):
            raise ValueError('At least one of \'compile_fn\', '
                             '\'compile_grad\', or \'compile_hv\' '
                             'must be True.')
        super(VectorArgs, self).__init__(pyfn, borrow, force_floatX)

        self.compile_fn = compile_fn
        self.compile_grad = compile_grad
        self.compile_hv = compile_hv

        self.compile_function(init_args, init_kwargs)

    def compile_function(self, args, kwargs):
        kwargs = kwargs.copy()
        kwargs.pop('_vectors', None)

        theano_vars = self.get_theano_vars(args, kwargs)

        inputs = theano_vars['inputs']
        outputs = theano_vars['outputs']

        if self.compile_grad or self.compile_hv:
            grad = tt.grad(outputs, wrt=inputs)

        if self.compile_hv:
            sym_vec = tt.vector()
            hess_vec = tt.Rop(grad, inputs, sym_vec)

        vector_inputs = [inputs]
        vector_outputs = []

        if self.compile_fn:
            vector_outputs.append(outputs)
        if self.compile_grad:
            vector_outputs.append(grad)
        if self.compile_hv:
            vector_inputs.append(sym_vec)
            vector_outputs.append(hess_vec)

        if len(vector_outputs) == 1:
            vector_outputs = vector_outputs[0]

        # compile function
        fn = theano.function(inputs=vector_inputs,
                             outputs=vector_outputs)

        # store in cache
        self.cache[self.cache_id(args, kwargs)] = fn

        return fn

    def get_theano_vars(self, args, kwargs):
        """
        Returns a dict containing inputs, outputs and givens corresponding to
        the Theano version of the pyfn.
        """

        # trace the function
        self.trace(args, kwargs)

        # get symbolic inputs corresponding to shared inputs in s_args
        s_memo = OrderedDict()
        sym_args = utils.flat_from_doc(self.s_args.values())

        # create a symbolic vector, then split it up into symbolic input
        # args
        inputs = tt.vector(name='theta')
        i = 0
        for a in sym_args:
            if a.shape:
                vector_arg = inputs[i: i + a.size].reshape(a.shape)
            else:
                vector_arg = inputs[i]
            s_memo[a] = tt.patternbroadcast(
                vector_arg.astype(str(a.dtype)),
                broadcastable=a.broadcastable)
            i += a.size

        # get new graph, replacing shared inputs with symbolic ones
        graph = theano.gof.graph.clone_get_equiv(
            theano.gof.graph.inputs(self.s_results.values()),
            self.s_results.values(),
            memo=s_memo.copy())

        # get symbolic outputs
        outputs = graph[self.s_results.values()[0]]

        theano_vars = {'inputs': inputs,
                       'outputs': outputs,
                       'graph': graph}

        return theano_vars

    def vector_from_args(self, args):
        return np.concatenate([np.asarray(a).flat for a in args])

    def args_from_vector(self, vector, orig_args):
        args = []
        last_idx = 0
        for a in orig_args:
            args.append(vector[last_idx:last_idx+a.size].reshape(a.shape))
            last_idx += a.size
        return args

    def call(self, *args):
        fn = self.cache.get(self.cache_id(args))
        return fn(*args)
