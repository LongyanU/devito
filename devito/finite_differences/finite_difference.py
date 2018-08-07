from __future__ import absolute_import

from functools import reduce, partial
from operator import mul

from sympy import finite_diff_weights, cos, sin

from devito.logger import error
from devito.finite_differences.operations import Add

__all__ = ['first_derivative', 'second_derivative', 'cross_derivative',
           'generic_derivative', 'second_cross_derivative',
           'left', 'right', 'centered', 'staggered_diff',
           'initialize_derivatives', 'transpose']


class Transpose(object):
    """Class that defines if the derivative is itself or adjoint (transpose).
    This only matter for odd order derivatives that requires
    a minus sign for the transpose."""
    def __init__(self, transpose):
        self._transpose = transpose

    def __eq__(self, other):
        return self._transpose == other._transpose

    def __repr__(self):
        return {1: 'direct', -1: 'transpose'}[self._transpose]


direct = Transpose(1)
transpose = Transpose(-1)


class Side(object):
    """Class encapsulating the side of the shift for derivatives."""

    def __init__(self, side):
        self._side = side

    def __eq__(self, other):
        return self._side == other._side

    def __repr__(self):
        return {-1: 'left', 0: 'centered', 1: 'right'}[self._side]

    def adjoint(self, matvec):
        if matvec == direct:
            return self
        else:
            if self == centered:
                return centered
            elif self == right:
                return left
            elif self == left:
                return right
            else:
                error("Unsupported side value")


left = Side(-1)
right = Side(1)
centered = Side(0)


def second_derivative(*args, **kwargs):
    """Derives second derivative for a product of given functions.

    :param \*args: All positional arguments must be fully qualified
       function objects, eg. `f(x, y)` or `g(t, x, y, z)`.
    :param dim: Symbol defininf the dimension wrt. which to
       differentiate, eg. `x`, `y`, `z` or `t`.
    :param diff: Finite Difference symbol to insert, default `h`.
    :param order: Discretisation order of the stencil to create.
    :returns: The second derivative

    Example: Deriving the second derivative of f(x, y)*g(x, y) wrt. x via
       ``second_derivative(f(x, y), g(x, y), order=2, dim=x)``
       results in ``(-2.0*f(x, y)*g(x, y) + 1.0*f(-h + x, y)*g(-h + x, y) +
       1.0*f(h + x, y)*g(h + x, y)) / h**2``.
    """
    order = kwargs.get('order', 2)
    dim = kwargs.get('dim')
    diff = kwargs.get('diff', dim.spacing)

    ind = [(dim + i * diff) for i in range(-int(order / 2),
                                           int(order / 2) + 1)]

    coeffs = finite_diff_weights(2, ind, dim)[-1][-1]
    deriv = 0

    for i in range(0, len(ind)):
            var = [a.subs({dim: ind[i]}) for a in args]
            deriv += coeffs[i] * reduce(mul, var, 1)
    return deriv


def cross_derivative(*args, **kwargs):
    """Derives cross derivative for a product of given functions.

    :param \*args: All positional arguments must be fully qualified
       function objects, eg. `f(x, y)` or `g(t, x, y, z)`.
    :param dims: 2-tuple of symbols defining the dimension wrt. which
       to differentiate, eg. `x`, `y`, `z` or `t`.
    :param diff: Finite Difference symbol to insert, default `h`.
    :returns: The cross derivative

    Example: Deriving the cross-derivative of f(x, y)*g(x, y) wrt. x and y via:
       ``cross_derivative(f(x, y), g(x, y), dims=(x, y))``
       results in:
       ``0.5*(-2.0*f(x, y)*g(x, y) + f(x, -h + y)*g(x, -h + y) +``
       ``f(x, h + y)*g(x, h + y) + f(-h + x, y)*g(-h + x, y) -``
       ``f(-h + x, h + y)*g(-h + x, h + y) + f(h + x, y)*g(h + x, y) -``
       ``f(h + x, -h + y)*g(h + x, -h + y)) / h**2``
    """
    dims = kwargs.get('dims')
    diff = kwargs.get('diff', (dims[0].spacing, dims[1].spacing))
    order = kwargs.get('order', 1)

    assert(isinstance(dims, tuple) and len(dims) == 2)
    deriv = 0

    # Stencil positions for non-symmetric cross-derivatives with symmetric averaging
    ind1r = [(dims[0] + i * diff[0])
             for i in range(-int(order / 2) + 1 - (order < 4),
                            int((order + 1) / 2) + 2 - (order < 4))]
    ind2r = [(dims[1] + i * diff[1])
             for i in range(-int(order / 2) + 1 - (order < 4),
                            int((order + 1) / 2) + 2 - (order < 4))]
    ind1l = [(dims[0] - i * diff[0])
             for i in range(-int(order / 2) + 1 - (order < 4),
                            int((order + 1) / 2) + 2 - (order < 4))]
    ind2l = [(dims[1] - i * diff[1])
             for i in range(-int(order / 2) + 1 - (order < 4),
                            int((order + 1) / 2) + 2 - (order < 4))]

    # Finite difference weights from Taylor approximation with this positions
    c11 = finite_diff_weights(1, ind1r, dims[0])[-1][-1]
    c21 = finite_diff_weights(1, ind1l, dims[0])[-1][-1]
    c12 = finite_diff_weights(1, ind2r, dims[1])[-1][-1]
    c22 = finite_diff_weights(1, ind2l, dims[1])[-1][-1]

    # Diagonal elements
    for i in range(0, len(ind1r)):
        for j in range(0, len(ind2r)):
            var1 = [a.subs({dims[0]: ind1r[i], dims[1]: ind2r[j]}) for a in args]
            var2 = [a.subs({dims[0]: ind1l[i], dims[1]: ind2l[j]}) for a in args]
            deriv += (.5 * c11[i] * c12[j] * reduce(mul, var1, 1) +
                      .5 * c21[-(j+1)] * c22[-(i+1)] * reduce(mul, var2, 1))

    return -deriv


def first_derivative(*args, **kwargs):
    """Derives first derivative for a product of given functions.

    :param \*args: All positional arguments must be fully qualified
       function objects, eg. `f(x, y)` or `g(t, x, y, z)`.
    :param dims: symbol defining the dimension wrt. which
       to differentiate, eg. `x`, `y`, `z` or `t`.
    :param diff: Finite Difference symbol to insert, default `h`.
    :param side: Side of the shift for the first derivatives.
    :returns: The first derivative

    Example: Deriving the first-derivative of f(x)*g(x) wrt. x via:
       ``cross_derivative(f(x), g(x), dim=x, side=1, order=1)``
       results in:
       ``*(-f(x)*g(x) + f(x + h)*g(x + h) ) / h``
    """
    dim = kwargs.get('dim')
    diff = kwargs.get('diff', dim.spacing)
    order = int(kwargs.get('order', 1))
    matvec = kwargs.get('matvec', direct)
    side = kwargs.get('side', centered).adjoint(matvec)
    deriv = Add(0)
    # Stencil positions for non-symmetric cross-derivatives with symmetric averaging
    if side == right:
        ind = [(dim + i * diff) for i in range(-int(order / 2) + 1 - (order % 2),
                                               int((order + 1) / 2) + 2 - (order % 2))]
    elif side == left:
        ind = [(dim - i * diff) for i in range(-int(order / 2) + 1 - (order % 2),
                                               int((order + 1) / 2) + 2 - (order % 2))]
    else:
        ind = [(dim + i * diff) for i in range(-int(order / 2),
                                               int((order + 1) / 2) + 1)]
    # Finite difference weights from Taylor approximation with this positions
    c = finite_diff_weights(1, ind, dim)
    c = c[-1][-1]
    # Loop through positions
    for i in range(0, len(ind)):
            var = [a.subs({dim: ind[i]}) for a in args]
            deriv += reduce(mul, var, 1) * c[i]
    return deriv * matvec._transpose


def generic_derivative(function, deriv_order, dim, fd_order, **kwargs):
    """
    Create generic arbitrary order derivative expression from a
    single :class:`Function` object. This methods is essentially a
    dedicated wrapper around SymPy's `as_finite_diff` utility for
    :class:`devito.Function` objects.

    :param function: The symbol representing a function.
    :param deriv_order: Derivative order, eg. 2 for a second derivative.
    :param dim: The dimension for which to take the derivative.
    :param fd_order: Order of the coefficient discretization and thus
                     the width of the resulting stencil expression.
    """
    indices = [(dim + i * dim.spacing) for i in range(-fd_order, fd_order + 1)]
    c = finite_diff_weights(deriv_order, indices, dim)[-1][-1]
    deriv = Add(0)
    for i in range(0, len(indices)):
            var = [function.subs({dim: indices[i]})]
            deriv += reduce(mul, var, 1) * c[i]
    return deriv


def second_cross_derivative(function, dims, order):
    """
    Create a second order order cross derivative for a given function.

    :param function: The symbol representing a function.
    :param dims: Dimensions for which to take the derivative.
    :param order: Discretisation order of the stencil to create.
    """
    first = second_derivative(function, dim=dims[0], width=order)
    return Add(second_derivative(first, dim=dims[1], order=order))


def staggered_diff(f, deriv_order, dim, fd_order, stagger=centered):
    """
    Utility function to generate staggered derivatives
    :param f: function objects, eg. `f(x, y)` or `g(t, x, y, z)`.
    :param dims: symbol defining the dimension wrt. which
       to differentiate, eg. `x`, `y`, `z` or `t`.
    :param order: Order of the coefficient discretization and thus
                  the width of the resulting stencil expression.
    :param stagger: Shift for the FD, `left`, `right` or `centered`
    :param theta: Dip (or polar) angle for rotated FD
    :param phi: Azimuth angle for rotated FD
    """
    if stagger == left:
        off = -.5
    elif stagger == right:
        off = .5
    else:
        off = 0

    diff = dim.spacing
    idx = list(set([(dim + int(i+.5+off)*diff)
                    for i in range(-int(fd_order / 2), int(fd_order / 2))]))
    if int(fd_order / 2) == 1:
        idx = [dim - diff, dim]
    deriv = f.diff(*(tuple(dim for _ in range(deriv_order))))
    return deriv.as_finite_difference(idx, x0=dim + off*dim.spacing)

def initialize_derivatives(self):
    """
    Dynamically create notational shortcuts for space derivatives.
    """
    if self.is_TimeFunction:
        _t = self.time_dim
        if self.time_order < 1:
            debug("Time order is 0, no time derivatives generated")
            return

        dt = partial(first_derivative, dim=_t, order=self.time_order)
        setattr(self.__class__, 'dt',
                property(dt, 'Return the symbolic expression for '
                         'the centered first derivative wrt. time'))
        if self.time_order > 1:
            dt2 = partial(second_derivative, dim=_t, order=self.time_order)
            setattr(self.__class__, 'dt2',
                    property(dt2, 'Return the symbolic expression for '
                             'the centered second derivative wrt. time'))

    for (dim, s) in zip(self.space_dimensions, self.staggered[1:]):
        deriv_function = staggered_diff if s is not None else generic_derivative
        if s == 0:
            side = left
        elif s == 1:
            side = right
        else:
            side = centered
        name = dim.parent.name if dim.is_Derived else dim.name
        # First derivative, centred
        dx = partial(deriv_function, deriv_order=1, dim=dim,
                     fd_order=self.space_order, stagger=side)
        setattr(self.__class__, 'd%s' % name,
                property(dx, 'Return the symbolic expression for '
                         'the centered first derivative wrt. '
                         'the %s dimension' % name))

        # First derivative, left, only for cartesian grid
        if s is None:
            dxl = partial(deriv_function, order=self.space_order,
                          dim=dim, side=left)
            setattr(self.__class__, 'd%sl' % name,
                    property(dxl, 'Return the symbolic expression for '
                             'the left-sided first derivative wrt. '
                             'the %s dimension' % name))

            # First derivative, right
            dxr = partial(first_derivative, order=self.space_order,
                          dim=dim, side=right)
            setattr(self.__class__, 'd%sr' % name,
                    property(dxr, 'Return the symbolic expression for '
                             'the right-sided first derivative wrt. '
                             'the %s dimension' % name))

        # Second derivative
        dx2 = partial(deriv_function, deriv_order=2, dim=dim,
                      fd_order=int(self.space_order / 2), stagg=side)
        setattr(self.__class__, 'd%s2' % name,
                property(dx2, 'Return the symbolic expression for '
                         'the second derivative wrt. the '
                         '%s dimension' % name))

        # Fourth derivative
        dx4 = partial(deriv_function, deriv_order=4, dim=dim,
                      fd_order=max(int(self.space_order / 2), 2), stagg=side)
        setattr(self.__class__, 'd%s4' % name,
                property(dx4, 'Return the symbolic expression for '
                         'the fourth derivative wrt. the '
                         '%s dimension' % name))

        # Cross derivatives, not supported in staggered grid
        if any(self.staggered) is None:
            for dim2 in self.space_dimensions:
                name2 = dim2.parent.name if dim2.is_Derived else dim2.name
                # First cross derivative
                dxy = partial(cross_derivative, order=self.space_order,
                              dims=(dim, dim2))
                setattr(self.__class__, 'd%s%s' % (name, name2),
                        property(dxy, 'Return the symbolic expression for '
                                 'the first cross derivative wrt. the '
                                 '%s and %s dimensions' %
                                 (name, name2)))

                # Second cross derivative
                dx2y2 = partial(second_cross_derivative, dims=(dim, dim2),
                                order=self.space_order)
                setattr(self.__class__, 'd%s2%s2' % (dim.name, name2),
                        property(dx2y2, 'Return the symbolic expression for '
                                 'the second cross derivative wrt. the '
                                 '%s and %s dimensions' %
                                 (name, name2)))