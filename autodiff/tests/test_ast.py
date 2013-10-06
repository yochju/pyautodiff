import unittest
import numpy as np
import copy

import autodiff
import autodiff.utils as utils
from autodiff.context import Context
import autodiff.context as c


context = Context()


def checkfn(f, var_ndim, *args, **kwargs):
    override = kwargs.pop('override', None)
    dim = [[4] * nd for nd in var_ndim]
    values = tuple([np.random.random(d) for d in dim])
    # make shallow copies to avoid inplace corruption
    sym_values = tuple(copy.copy(v) for v in values)
    sym_args = tuple(copy.copy(a) for a in args)

    F = context.recompile(f)

    sym_vars = F(*(sym_values + args))
    sym_result = [v.eval() for v in utils.as_seq(sym_vars)]
    if len(sym_result) == 0:
        sym_result = None
    elif not isinstance(sym_vars, tuple):
        sym_result = sym_result[0]

    py_result = override or f(*(values + args))

    context.reset()

    if sym_result is None:
        return sym_result is None and py_result is None
    else:
        return np.allclose(py_result, sym_result)


class GarbageCollection(unittest.TestCase):
    # make sure shadowed variables aren't garbage-collected
    # so their id's do not get reused
    def test_gc(self):
        def f(x, y):
            return [x, y]

        F = context.recompile(f)
        assert F(3, 4)[1].eval() == 4


class AugAssign(unittest.TestCase):
    def test_aug_shadowing(self):
        def f(x):
            a = x
            x += 1
            return x

        F = context.recompile(f)
        assert F(1).eval() == 2


class Python(unittest.TestCase):
    def test_range(self):
        def f(x):
            for i in range(3):
                x += 5
            return x
        self.assertTrue(checkfn(f, [1]))

        def f(x):
            a = 3
            for i in range(a):
                x += 5
            return x
        self.assertTrue(checkfn(f, [1]))

        def f(x):
            a = x[0] + 10
            for i in range(int(a)):
                x += 5
            return x
        self.assertTrue(checkfn(f, [1]))

        def f(x, a):
            for i in range(a):
                x += 5
            return x
        self.assertTrue(checkfn(f, [1], 3))

    def test_pass(self):
        def fn(x):
            pass
        self.assertTrue(checkfn(fn, [1]))

    @unittest.expectedFailure
    def test_enumerate(self):
        def fn(x):
            z = np.arange(x.shape[0])
            for i, xi in enumerate(x):
                z[i] += xi
            return z
        self.assertTrue(checkfn(fn, [1]))


class BasicMath(unittest.TestCase):
    def test_basic_ops(self):
        for d in range(3):
            self.assertTrue(checkfn(lambda x: x + 2, [d]))
            self.assertTrue(checkfn(lambda x: x - 2, [d]))
            self.assertTrue(checkfn(lambda x: x * 2, [d]))
            self.assertTrue(checkfn(lambda x: x / 2, [d]))
            self.assertTrue(checkfn(lambda x: x / 2.0, [d]))
            self.assertTrue(checkfn(lambda x: x // 2.0, [d]))
            self.assertTrue(checkfn(lambda x: x ** 2, [d]))
            self.assertTrue(checkfn(lambda x: x % 2, [d]))

    def test_comparisons(self):
        for d in range(3):
            self.assertTrue(checkfn(lambda x, y: x > y, [d, d]))
            self.assertTrue(checkfn(lambda x, y: x < y, [d, d]))
            self.assertTrue(checkfn(lambda x, y: x >= y, [d, d]))
            self.assertTrue(checkfn(lambda x, y: x <= y, [d, d]))
            self.assertTrue(checkfn(lambda x, y: x == y, [d, d]))
            self.assertTrue(checkfn(lambda x, y: x != y, [d, d]))

    def test_inplace(self):

        def iadd(x):
            x += 10
            return x

        def isub(x):
            x -= 10
            return x

        def imul(x):
            x *= 10
            return x

        def idiv(x):
            x /= 10.0
            return x

        for d in range(3):
            for f in [iadd, isub, imul, idiv]:
                print f, d
                self.assertTrue(checkfn(f, [d]))


class NumpyFns(unittest.TestCase):
    """
    Test for coverage of functions in np namespace
    """
    def test_all(self):
        def fn(x):
            return np.all(x > .5)
        self.assertTrue(checkfn(fn, [2]))

    def test_any(self):
        def fn(x):
            return np.any(x > .5)
        self.assertTrue(checkfn(fn, [2]))

    def test_arange(self):
        self.assertTrue(checkfn(lambda: np.arange(3), []))
        # numpy arange doesn't return an array with the same dtype as its
        # argument, but theano arange does. In Context, the numpy arange
        # should be cast to match the theano one.
        self.assertTrue(checkfn(lambda: np.arange(np.float32(3.)), []))

    def test_abs(self):
        def fn1(x):
            return np.abs(x)

        def fn2(x):
            return abs(x)

        self.assertTrue(checkfn(fn1, [2]))
        self.assertTrue(checkfn(fn2, [2]))

    def test_dot(self):
        def fn(x, y):
            return np.dot(x, y)
        for nd in np.ndindex(*([3] * fn.func_code.co_argcount)):
            self.assertTrue(checkfn(fn, nd))

    def test_exp(self):
        def fn(x):
            return np.exp(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_log(self):
        def fn(x):
            return np.log(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_log1p(self):
        def fn(x):
            return np.log1p(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_log10(self):
        def fn(x):
            return np.log10(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_maximum(self):
        def fn(x, y):
            return np.maximum(x, y)
        self.assertTrue(checkfn(fn, [2, 2]))

    def test_minimum(self):
        def fn(x, y):
            return np.minimum(x, y)
        self.assertTrue(checkfn(fn, [2, 2]))

    def test_reshape(self):
        def fn(x, shape):
            return np.reshape(x, shape)
        self.assertTrue(checkfn(fn, [2], [2, 8]))

        def fn(x, shape1, shape2):
            return np.reshape(x, [shape1, shape2])
        self.assertTrue(checkfn(fn, [2], 2, 8))
        self.assertTrue(checkfn(fn, [2], 2, -1))
        self.assertTrue(checkfn(lambda x: np.reshape(x, x.shape), [2]))
        self.assertTrue(checkfn(
            lambda x: np.reshape(x, (x.shape[0], x.shape[1])), [2]))

    def test_sum(self):
        self.assertTrue(checkfn(lambda x: np.sum(x), [2]))
        self.assertTrue(checkfn(lambda x: np.sum(x, 1), [2]))
        self.assertTrue(checkfn(lambda x: np.sum(x, axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: np.sum(x, a), [2], 0)
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: np.sum(x, axis=a), [2], 0)

    def test_sqrt(self):
        def fn(x):
            return np.sqrt(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_tanh(self):
        def fn(x):
            return np.tanh(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_zeros_like(self):
        def fn(x):
            return np.zeros_like(x)
        self.assertTrue(checkfn(fn, [2]))

    def test_astype(self):
        self.assertTrue(checkfn(lambda x: x.astype('float32'), [2]))

    def test_astype_numpy_class(self):
        self.assertTrue(checkfn(lambda x: x.astype(np.float32), [2]))

    def test_cast(self):
        self.assertTrue(checkfn(lambda x: int(x), [0]))
        self.assertTrue(checkfn(lambda x: float(x), [0]))
        self.assertTrue(checkfn(lambda x: bool(x), [0]))
        self.assertTrue(checkfn(lambda x: np.float_(x), [2]))
        self.assertTrue(checkfn(lambda x: np.float32(x), [2]))
        self.assertTrue(checkfn(lambda x: np.float64(x), [2]))
        self.assertTrue(checkfn(lambda x: np.int_(x), [2]))
        self.assertTrue(checkfn(lambda x: np.int16(x), [2]))
        self.assertTrue(checkfn(lambda x: np.bool_(x), [2]))
        self.assertTrue(checkfn(lambda x: np.bool(x), [0]))


class ArrayMethodsAttributes(unittest.TestCase):
    """
    Test for coverage of array methods and attributes
    """

    def test_argmax(self):
        self.assertTrue(checkfn(lambda x: x.argmax(), [2]))
        self.assertTrue(checkfn(lambda x: x.argmax(1), [2]))
        self.assertTrue(checkfn(lambda x: x.argmax(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.argmax(a), [2], 0)

    def test_argmin(self):
        self.assertTrue(checkfn(lambda x: x.argmin(), [2]))
        self.assertTrue(checkfn(lambda x: x.argmin(1), [2]))
        self.assertTrue(checkfn(lambda x: x.argmin(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.argmin(a), [2], 0)

    def test_argsort(self):
        self.assertTrue(checkfn(lambda x: x.argsort(), [2]))
        self.assertTrue(checkfn(lambda x: x.argsort(1), [2]))
        self.assertTrue(checkfn(lambda x: x.argsort(axis=1), [2]))
        self.assertTrue(checkfn(
            lambda x, a: x.argsort(a), [2], 0))

    def test_clip(self):
        def fn(x, a, b):
            return x.clip(a, b)
        self.assertTrue(checkfn(fn, [2], .4, .45))

    def test_conj(self):
        def fn(x):
            return x.conj()
        self.assertTrue(checkfn(fn, [2]))

    def test_conjugate(self):
        def fn(x):
            return x.conjugate()
        self.assertTrue(checkfn(fn, [2]))

    def test_copy(self):
        def fn(x):
            return x.copy()
        self.assertTrue(checkfn(fn, [2]))

    def test_diagonal(self):
        def fn(x):
            return x.diagonal()
        self.assertTrue(checkfn(fn, [2]))

    def test_dot(self):
        def fn(x, y):
            return x.dot(y)
        self.assertTrue(checkfn(fn, [2, 2]))
        self.assertTrue(checkfn(fn, [1, 2]))

    def test_imag(self):
        def fn(x):
            return x.imag
        self.assertTrue(checkfn(fn, [2]))

    def test_flatten(self):
        def fn(x):
            return x.flatten()
        self.assertTrue(checkfn(fn, [2]))

    def test_max(self):
        self.assertTrue(checkfn(lambda x: x.max(), [2]))
        self.assertTrue(checkfn(lambda x: x.max(1), [2]))
        self.assertTrue(checkfn(lambda x: x.max(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.max(a), [2], 0)

    def test_mean(self):
        self.assertTrue(checkfn(lambda x: x.mean(), [2]))
        self.assertTrue(checkfn(lambda x: x.mean(1), [2]))
        self.assertTrue(checkfn(lambda x: x.mean(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.mean(a), [2], 0)

    def test_min(self):
        self.assertTrue(checkfn(lambda x: x.min(), [2]))
        self.assertTrue(checkfn(lambda x: x.min(1), [2]))
        self.assertTrue(checkfn(lambda x: x.min(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.min(a), [2], 0)

    def test_prod(self):
        self.assertTrue(checkfn(lambda x: x.prod(), [2]))
        self.assertTrue(checkfn(lambda x: x.prod(1), [2]))
        self.assertTrue(checkfn(lambda x: x.prod(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.prod(a), [2], 0)

    def test_ravel(self):
        def fn(x):
            return x.ravel()
        self.assertTrue(checkfn(fn, [2]))

    def test_repeat(self):
        def fn(x, repeats):
            return x.repeat(repeats, axis=1)
        self.assertTrue(checkfn(fn, [2], 5))

    def test_real(self):
        def fn(x):
            return x.real
        self.assertTrue(checkfn(fn, [2]))

    def test_reshape(self):
        def fn(x, shape):
            return x.reshape(shape)
        self.assertTrue(checkfn(fn, [2], [2, 8]))

        def fn(x, s1, s2):
            return x.reshape(s1, s2)
        self.assertTrue(checkfn(fn, [2], 2, 8))
        self.assertTrue(checkfn(fn, [2], 2, -1))

    def test_sort(self):
        def fn(x):
            x.sort()
            return x
        self.assertTrue(checkfn(fn, [2]))

        def fn(x):
            x.sort(1)
            return x
        self.assertTrue(checkfn(fn, [2]))

        def fn(x):
            x.sort(axis=1)
            return x
        self.assertTrue(checkfn(fn, [2]))

        def fn(x, a):
            x.sort(a)
            return x
        self.assertTrue(checkfn(fn, [2], 0))

    def test_sum(self):
        self.assertTrue(checkfn(lambda x: x.sum(), [2]))
        self.assertTrue(checkfn(lambda x: x.sum(1), [2]))
        self.assertTrue(checkfn(lambda x: x.sum(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.sum(a), [2], 0)

    def test_swapaxes(self):
        def fn(x, a1, a2):
            return x.swapaxes(a1, a2)
        self.assertTrue(checkfn(fn, [2], 0, 1))

    def test_astype(self):
        self.assertTrue(checkfn(lambda x: x.astype('int8'), [2]))
        self.assertTrue(checkfn(lambda x: x.astype('float32'), [2]))
        self.assertTrue(checkfn(lambda x: x.astype(np.float32), [2]))
        self.assertTrue(checkfn(lambda x: x.astype(dtype='float32'), [2]))
        self.assertTrue(checkfn(lambda x: x.astype(dtype=np.float32), [2]))

    def test_std(self):
        self.assertTrue(checkfn(lambda x: x.std(), [2]))
        self.assertTrue(checkfn(lambda x: x.std(1), [2]))
        self.assertTrue(checkfn(lambda x: x.std(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.std(a), [2], 0)

    def test_size(self):
        self.assertTrue(checkfn(lambda x : np.arange(x.size), [1]))
        self.assertTrue(checkfn(lambda x : np.arange(x.size), [2]))

    def test_T(self):
        def fn(x):
            return x.T
        self.assertTrue(checkfn(fn, [1]))
        self.assertTrue(checkfn(fn, [2]))

    def test_transpose(self):
        def fn(x):
            return x.transpose()
        self.assertTrue(checkfn(fn, [1]))
        self.assertTrue(checkfn(fn, [2]))

    def test_var(self):
        self.assertTrue(checkfn(lambda x: x.var(), [2]))
        self.assertTrue(checkfn(lambda x: x.var(1), [2]))
        self.assertTrue(checkfn(lambda x: x.var(axis=1), [2]))
        self.assertRaises(TypeError, checkfn,
                          lambda x, a: x.var(a), [2], 0)

class NestedFunctions(unittest.TestCase):
    def test_nested_functions(self):
        def g(x):
            def h(x):
                return x.swapaxes(1, 0)
            return h(x)

        def f(x):
            return g(x)

        self.assertTrue(checkfn(f, [2]))

class ArraySubscripts(unittest.TestCase):
    def test_indexing(self):
        self.assertTrue(checkfn(lambda x : x[2], [1]))
        self.assertTrue(checkfn(lambda x : x[-2], [1]))
        self.assertTrue(checkfn(lambda x : x[2], [2]))
        self.assertTrue(checkfn(lambda x : x[-2], [2]))
        self.assertTrue(checkfn(lambda x : x[2, 2], [2]))
        self.assertTrue(checkfn(lambda x : x[-2, -2], [2]))

    def test_slicing(self):
        self.assertTrue(checkfn(lambda x : x[1:3], [1]))
        self.assertTrue(checkfn(lambda x : x[1:-1], [1]))
        self.assertTrue(checkfn(lambda x : x[1:3], [2]))
        self.assertTrue(checkfn(lambda x : x[1:-1], [2]))
        self.assertTrue(checkfn(lambda x : x[1:3, 1:3], [2]))
        self.assertTrue(checkfn(lambda x : x[1:-1, 1:-1], [2]))

    def test_index_and_slice(self):
        self.assertTrue(checkfn(lambda x : x[1:3, 2], [2]))

    def test_index_assign(self):
        def f():
            x = np.ones((3, 4))
            x[2] = 100
            return x
        self.assertTrue(checkfn(f, []))

        def f():
            x = np.ones((3, 4))
            x[2, 2] = 100
            return x
        self.assertTrue(checkfn(f, []))

        def f():
            x = np.ones((3, 4))
            x[2, 2] += 100
            return x
        self.assertTrue(checkfn(f, []))

        def f(x):
            x[2, 2] = 100
            return x
        self.assertTrue(checkfn(f, [2]))

        def f(x):
            x[2, 2] += 100
            return x
        self.assertTrue(checkfn(f, [2]))

    def test_slice_assign(self):
        def f():
            x = np.ones((3, 4))
            x[2:3] = 100
            return x
        self.assertTrue(checkfn(f, []))

        def f():
            x = np.ones((3, 4))
            x[2:3, 2:3] += 100
            return x
        self.assertTrue(checkfn(f, []))

        def f(x):
            x[2:3, 2:3] += 100
            return x
        self.assertTrue(checkfn(f, [2]))

    def test_array_assign(self):
        def f(x):
            o = np.ones((2, 3))
            x[1:3, 1:4] = o
            return x
        self.assertTrue(checkfn(f, [2]))


class TestMethods(unittest.TestCase):
    def test_instance_method(self):
        class Test(object):
            def test(self, x):
                return x * 2

        t = Test()
        self.assertTrue(checkfn(t.test, [2]))

    def test_class_method(self):
        class Test(object):
            @classmethod
            def test(cls, x):
                return x * 2

        t = Test()
        self.assertTrue(checkfn(t.test, [2]))
        self.assertTrue(checkfn(Test.test, [2]))

    def test_static_method(self):
        class Test(object):
            @staticmethod
            def test(x):
                return x * 2

        t = Test()
        self.assertTrue(checkfn(t.test, [2]))
        self.assertTrue(checkfn(Test.test, [2]))
