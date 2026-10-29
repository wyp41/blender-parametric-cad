"""Sample involute teaching profiles for existing Sketch/Extrude workflows.

Lengths use meters and pressure angles use radians. These are unshifted,
low-load prototype profiles, with circular rather than generated trochoid roots.
Backlash is each gear's reduction in reference-circle tooth thickness.
"""

from math import atan, atan2, ceil, cos, hypot, isfinite, pi, sin, sqrt, tan

from .entities import SketchLine


def _outline(module, teeth, pressure_angle, backlash, fillet, addendum, dedendum):
    rp = module * teeth / 2
    rb, ra, rf = rp*cos(pressure_angle), rp+addendum*module, rp-dedendum*module
    half = (pi*module/2-backlash)/(2*rp)
    base = -half-tan(pressure_angle)+pressure_angle
    if rf <= 0 or half <= 0 or ra <= rb:
        raise ValueError('Gear proportions do not produce a supported involute profile.')

    def polar(r, a):
        return r*cos(a), r*sin(a)

    def involute(t):
        return polar(rb*sqrt(1+t*t), base+t-atan(t))

    t0 = max(0.0, (sqrt(max(0.0, (rf+fillet)**2-rb**2))-fillet)/rb)
    if t0:
        p, direction = involute(t0), base+t0
    else:
        p, direction = polar(sqrt(rf*rf+2*rf*fillet), base), base
    center = p[0]+fillet*sin(direction), p[1]-fillet*cos(direction)
    q = tuple(v*rf/(rf+fillet) for v in center)
    a = atan2(q[1]-center[1], q[0]-center[0])
    b = atan2(p[1]-center[1], p[0]-center[0])
    sweep = (b-a) % (2*pi)-2*pi
    flank = [(center[0]+fillet*cos(a+sweep*i/8),
              center[1]+fillet*sin(a+sweep*i/8)) for i in range(9)]
    if t0 == 0:
        flank.append(involute(0))
    ta = sqrt((ra/rb)**2-1)
    if t0 >= ta:
        raise ValueError('Root fillet consumes the involute flank; reduce its radius.')
    flank.extend(involute(t0+(ta-t0)*i/16) for i in range(1, 17))
    tip = -atan2(flank[-1][1], flank[-1][0])
    root = -atan2(q[1], q[0])
    pitch = 2*pi/teeth
    if tip <= 0 or 2*root >= pitch:
        raise ValueError('Gear teeth or root fillets overlap.')
    tooth = flank + [polar(ra, -tip+2*tip*i/4) for i in range(1, 5)]
    tooth.extend((x, -y) for x, y in reversed(flank[:-1]))
    tooth.extend(polar(rf, root+(pitch-2*root)*i/6) for i in range(1, 6))
    points = []
    for k in range(teeth):
        c, s = cos(k*pitch), sin(k*pitch)
        points.extend((x*c-y*s, x*s+y*c) for x, y in tooth)
    return points


def spur_outline(module, teeth, pressure_angle=pi/9, backlash=0.0, root_fillet=None):
    """Return a CCW external outline; no undercut or profile shift is generated."""
    _validate(module, teeth, pressure_angle, backlash, minimum=18)
    if teeth < ceil(2/sin(pressure_angle)**2):
        raise ValueError('This unshifted profile would require undercut; increase tooth count or pressure angle.')
    fillet = 0.3*module if root_fillet is None else root_fillet
    if not isfinite(fillet) or fillet <= 0:
        raise ValueError('Root fillet must be positive and finite.')
    return _outline(module, teeth, pressure_angle, backlash, fillet, 1.0, 1.25)


def internal_outline(module, teeth, pressure_angle=pi/9, backlash=0.0, root_fillet=None):
    """Return the central void to CUT from a ring blank, with enlarged tooth spaces."""
    _validate(module, teeth, pressure_angle, backlash, minimum=40)
    fillet = 0.3*module if root_fillet is None else root_fillet
    if not isfinite(fillet) or fillet <= 0:
        raise ValueError('Root fillet must be positive and finite.')
    if module*(teeth/2-1) <= module*teeth/2*cos(pressure_angle):
        raise ValueError('Internal tip circle must lie outside its base circle.')
    return _outline(module, teeth, pressure_angle, -backlash, fillet, 1.25, 1.0)


def rack_outline(module, teeth, pressure_angle=pi/9, backlash=0.0, base_height=None):
    """Return a CCW straight rack; pitch line is Y=0 and teeth point toward +Y."""
    _validate(module, teeth, pressure_angle, backlash, minimum=1)
    base = 2.5*module if base_height is None else base_height
    if not isfinite(base) or base <= 0:
        raise ValueError('Rack base height must be positive and finite.')
    pitch, thickness = pi*module, pi*module/2-backlash
    top_half = thickness/2-module*tan(pressure_angle)
    root_half = thickness/2+1.25*module*tan(pressure_angle)
    if top_half <= 0 or root_half >= pitch/2:
        raise ValueError('Rack proportions overlap or have pointed teeth.')
    left, right = -teeth*pitch/2, teeth*pitch/2
    points = [(left, -1.25*module)]
    for k in range(teeth):
        x = left+(k+0.5)*pitch
        points.extend(((x-root_half, -1.25*module), (x-top_half, module),
                       (x+top_half, module), (x+root_half, -1.25*module)))
    points.extend(((right, -1.25*module), (right, -1.25*module-base),
                   (left, -1.25*module-base)))
    return list(reversed(points))


def add_outline(sketch, points):
    """Append one closed polyline to a Sketch, preserving all existing entities."""
    if len(points) < 3 or any(not all(isfinite(v) for v in p) for p in points):
        raise ValueError('A closed outline needs at least three finite points.')
    if any(hypot(b[0]-a[0], b[1]-a[1]) <= 1e-7
           for a, b in zip(points, points[1:]+points[:1])):
        raise ValueError('Outline edges must exceed the Sketch tolerance.')
    entities = [SketchLine(x1=a[0], y1=a[1], x2=b[0], y2=b[1])
                for a, b in zip(points, points[1:]+points[:1])]
    sketch.entities.extend(entities)
    return entities


def _validate(module, teeth, angle, backlash, minimum):
    if not isfinite(module) or module <= 0:
        raise ValueError('Module must be positive and finite.')
    if isinstance(teeth, bool) or not isinstance(teeth, int) or teeth < minimum:
        raise ValueError(f'Teeth must be an integer >= {minimum}.')
    if not isfinite(angle) or not 0 < angle < pi/4:
        raise ValueError('Pressure angle must be between 0 and 45 degrees.')
    if not isfinite(backlash) or not 0 <= backlash < pi*module/4:
        raise ValueError('Tooth-thickness reduction is outside the supported range.')
