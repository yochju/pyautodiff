"""
SciPy-based function optimization
"""

import numpy as np
import scipy

from autodiff.symbolic import VectorArg
import autodiff.utils as utils


__all__ = ['fmin_cg', 'fmin_l_bfgs_b']


def fmin_cg(fn,
            args,
            **scipy_kwargs):
    """
    Minimize a scalar valued function using SciPy's nonlinear conjugate
    gradient algorithm. The initial parameter guess is 'args'.

    """

    args = utils.as_seq(args, tuple)
    f = VectorArg(fn, init_args=args, compile_fn=True)
    fprime = VectorArg(fn, init_args=args, compile_grad=True)
    x0 = f.vector_from_args(args)

    x_opt = scipy.optimize.fmin_cg(
        f=f,
        x0=x0,
        fprime=fprime,
        full_output=False,
        **scipy_kwargs)

    x_reshaped = f.args_from_vector(x_opt)
    if len(x_reshaped) == 1:
        x_reshaped = x_reshaped[0]

    return x_reshaped


def fmin_l_bfgs_b(fn,
                  args,
                  scalar_bounds=None,
                  return_info=False,
                  **scipy_kwargs):
    """
    Minimize a scalar valued function using SciPy's L-BFGS-B algorithm. The
    initial parameter guess is 'args'.

    """

    args = utils.as_seq(args, tuple)
    f_df = VectorArg(fn, init_args=args, compile_fn=True, compile_grad=True)
    x0 = f_df.vector_from_args(args)

    if 'approx_grad' in scipy_kwargs:
        raise TypeError('duplicate argument: approx_grad')
    if scalar_bounds is not None:
        lb, ub = scalar_bounds
        bounds = np.empty((len(x0), 2))
        bounds[:, 0] = lb
        bounds[:, 1] = ub
        if 'bounds' in scipy_kwargs:
            raise TypeError('duplicate argument: bounds')
        scipy_kwargs['bounds'] = bounds

    x_opt, f_opt, info = scipy.optimize.fmin_l_bfgs_b(
        func=f_df,
        x0=x0,
        approx_grad=False,
        **scipy_kwargs)

    x_reshaped = f_df.args_from_vector(x_opt)
    if len(x_reshaped) == 1:
        x_reshaped = x_reshaped[0]

    if return_info:
        return x_reshaped, {'f_opt': f_opt, 'info': info}
    else:
        return x_reshaped
