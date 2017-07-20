from sympy import Eq, solve, diff
from sympy.abc import h, s

from devito import Operator, Forward, Backward, DenseData, TimeData, time
from examples.seismic import PointSource, Receiver, ABC


def pde(field, m, time_order, model):
    if time_order == 2:
        biharmonic = 0
        dt = model.critical_dt
    else:
        biharmonic = field.laplace2(1/m)
        dt = 1.73 * model.critical_dt
    eq = m * field.dt2 - field.laplace - s**2/12 * biharmonic
    return eq, dt


def ForwardOperator(model, source, receiver, time_order=2, space_order=4,
                    save=False, **kwargs):
    """
    Constructor method for the forward modelling operator in an acoustic media

    :param model: :class:`Model` object containing the physical parameters
    :param source: :class:`PointData` object containing the source geometry
    :param receiver: :class:`PointData` object containing the acquisition geometry
    :param time_order: Time discretization order
    :param space_order: Space discretization order
    :param save : Saving flag, True saves all time steps, False only the three
    """
    m = model.m

    # Create symbols for forward wavefield, source and receivers
    u = TimeData(name='u', shape=model.shape_domain, time_dim=source.nt,
                 time_order=time_order, space_order=space_order, save=save,
                 dtype=model.dtype)
    src = PointSource(name='src', ntime=source.nt, ndim=source.ndim,
                      npoint=source.npoint)
    rec = Receiver(name='rec', ntime=receiver.nt, ndim=receiver.ndim,
                   npoint=receiver.npoint)

    # Derive stencil from symbolic equation:
    eqn, dt = pde(u, m, time_order, model)
    stencil = [Eq(u.forward, solve(eqn, u.forward, rational=False)[0])]
    # Construct expression to inject source values
    # Note that src and field terms have differing time indices:
    #   src[time, ...] - always accesses the "unrolled" time index
    #   u[ti + 1, ...] - accesses the forward stencil value
    ti = u.indices[0]
    src_term = src.inject(field=u, u_t=ti + 1, offset=model.nbpml,
                          expr=src * dt**2 / m, p_t=time)

    # Create interpolation expression for receivers
    rec_term = rec.interpolate(expr=u, u_t=ti, offset=model.nbpml)

    abc = ABC(model, u, m)
    eq_abc = abc.damp_2d() if len(model.shape) == 2 else abc.damp_3d()

    return Operator(stencil + eq_abc + src_term + rec_term,
                    subs={s: dt, h: model.get_spacing()},
                    time_axis=Forward, name='Forward', **kwargs)


def AdjointOperator(model, source, receiver, time_order=2, space_order=4, **kwargs):
    """
    Constructor method for the adjoint modelling operator in an acoustic media

    :param model: :class:`Model` object containing the physical parameters
    :param source: :class:`PointData` object containing the source geometry
    :param receiver: :class:`PointData` object containing the acquisition geometry
    :param time_order: Time discretization order
    :param space_order: Space discretization order
    """
    m = model.m

    v = TimeData(name='v', shape=model.shape_domain, save=False,
                 time_order=time_order, space_order=space_order,
                 dtype=model.dtype)
    srca = PointSource(name='srca', ntime=source.nt, ndim=source.ndim,
                       npoint=source.npoint)
    rec = Receiver(name='rec', ntime=receiver.nt, ndim=receiver.ndim,
                   npoint=receiver.npoint)

    eqn, dt = pde(v, m, time_order, model)
    stencil = [Eq(v.backward, solve(eqn, v.backward, rational=False)[0])]

    # Construct expression to inject receiver values
    ti = v.indices[0]
    receivers = rec.inject(field=v, u_t=ti - 1, offset=model.nbpml,
                           expr=rec * dt**2 / m, p_t=time)

    # Create interpolation expression for the adjoint-source
    source_a = srca.interpolate(expr=v, u_t=ti, offset=model.nbpml)

    abc = ABC(model, v, m, taxis=Backward)
    eq_abc = abc.damp_2d() if len(model.shape) == 2 else abc.damp_3d()

    return Operator(stencil + eq_abc + receivers + source_a,
                    subs={s: dt, h: model.get_spacing()},
                    time_axis=Backward, name='Adjoint', **kwargs)


def GradientOperator(model, source, receiver, time_order=2, space_order=4, **kwargs):
    """
    Constructor method for the gradient operator in an acoustic media

    :param model: :class:`Model` object containing the physical parameters
    :param source: :class:`PointData` object containing the source geometry
    :param receiver: :class:`PointData` object containing the acquisition geometry
    :param time_order: Time discretization order
    :param space_order: Space discretization order
    """
    m = model.m

    # Gradient symbol and wavefield symbols
    grad = DenseData(name='grad', shape=model.shape_domain,
                     dtype=model.dtype)
    u = TimeData(name='u', shape=model.shape_domain, save=True,
                 time_dim=source.nt, time_order=time_order,
                 space_order=space_order, dtype=model.dtype)
    v = TimeData(name='v', shape=model.shape_domain, save=False,
                 time_order=time_order, space_order=space_order,
                 dtype=model.dtype)
    rec = Receiver(name='rec', ntime=receiver.nt, ndim=receiver.ndim,
                   npoint=receiver.npoint)

    eqn, dt = pde(v, m, time_order, model)
    eqnu, _ = pde(u, m, time_order, model)
    stencil = [Eq(v.backward, solve(eqn, v.backward, rational=False)[0])]
    gradient_update = Eq(grad, grad - diff(eqnu, m) * v)

    # Add expression for receiver injection
    ti = v.indices[0]
    receivers = rec.inject(field=v, u_t=ti - 1, offset=model.nbpml,
                           expr=rec * dt * dt / m, p_t=time)

    abc = ABC(model, v, m, taxis=Backward)
    eq_abc = abc.damp_2d() if len(model.shape) == 2 else abc.damp_3d()

    return Operator(stencil + receivers + eq_abc + [gradient_update],
                    subs={s: dt, h: model.get_spacing()},
                    time_axis=Backward, name='Gradient', **kwargs)


def BornOperator(model, source, receiver, time_order=2, space_order=4, **kwargs):
    """
    Constructor method for the Linearized Born operator in an acoustic media

    :param model: :class:`Model` object containing the physical parameters
    :param source: :class:`PointData` object containing the source geometry
    :param receiver: :class:`PointData` object containing the acquisition geometry
    :param time_order: Time discretization order
    :param space_order: Space discretization order
    """
    m = model.m

    # Create source and receiver symbols
    src = PointSource(name='src', ntime=source.nt, ndim=source.ndim,
                      npoint=source.npoint)
    rec = Receiver(name='rec', ntime=receiver.nt, ndim=receiver.ndim,
                   npoint=receiver.npoint)

    # Create wavefields and a dm field
    u = TimeData(name="u", shape=model.shape_domain, save=False,
                 time_order=time_order, space_order=space_order,
                 dtype=model.dtype)
    U = TimeData(name="U", shape=model.shape_domain, save=False,
                 time_order=time_order, space_order=space_order,
                 dtype=model.dtype)
    dm = DenseData(name="dm", shape=model.shape_domain,
                   dtype=model.dtype)

    # Derive stencil from symbolic equation:
    eqnu, dt = pde(u, m, time_order, model)
    stencilu = [Eq(u.forward, solve(eqnu, u.forward, rational=False)[0])]
    eqnU, dt = pde(U, m, time_order, model)
    stencilU = [Eq(U.forward, solve(eqnU + dm * diff(eqnu, m), U.forward, rational=False)[0])]

    # Add source term expression for u
    ti = u.indices[0]
    source = src.inject(field=u, u_t=ti + 1, offset=model.nbpml,
                        expr=src * dt * dt / m, p_t=time)

    # Create receiver interpolation expression from U
    receivers = rec.interpolate(expr=U, u_t=ti, offset=model.nbpml)

    abcu = ABC(model, u, m)
    eq_abcu = abcu.damp_2d() if len(model.shape) == 2 else abcu.damp_3d()
    abcU = ABC(model, U, m)
    eq_abcU = abcU.damp_2d() if len(model.shape) == 2 else abcU.damp_3d()

    return Operator(stencilu + eq_abcu + source + stencilU + eq_abcU + receivers,
                    subs={s: dt, h: model.get_spacing()},
                    time_axis=Forward, name='Born', **kwargs)