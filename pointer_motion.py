"""Independent pointer motion engine; no NarrationAutomata dependencies.

Coordinates are normalized to the video canvas (0..1).  A scheduled motion
is active on the half-open interval [start, end).  FFmpeg expressions use
frame time `t`; they are deliberately separate from numeric evaluation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

Point = tuple[float, float]
_EPS = 1e-10


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _point(value: Any, label: str) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must be a pair [x, y]")
    result = (_number(value[0], label), _number(value[1], label))
    if any(v < 0 or v > 1 for v in result):
        raise ValueError(f"{label} must lie in [0, 1] (normalized canvas)")
    return result


def _fmt(v: float) -> str:
    return format(v, '.12g')


def _mix(a: Point, b: Point, u: float) -> Point:
    return a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u


def _bezier(points: Sequence[Point], u: float) -> Point:
    a, b, c, d = points
    v = 1-u
    return tuple(v**3*a[k]+3*v*v*u*b[k]+3*v*u*u*c[k]+u**3*d[k] for k in (0, 1))  # type: ignore[return-value]


@dataclass(frozen=True)
class Motion:
    kind: str
    points: tuple[Point, ...]
    center: Point = (0.5, 0.5)
    radius: float = 0.0
    phase: float = 0.0                 # radians
    clockwise: bool = True           # screen coordinates, y increases downwards
    turns: float = 1.0
    loop: bool = False
    speed: float | None = None        # normalized canvas lengths / second
    easing: str = 'linear'           # or smoothstep; available with auto duration
    radius_y: float = 0.0
    jitter_px: float = 0.0
    jitter_seed: int = 42
    moving_factor: float = 0.15
    jitter_transition: float = 0.25

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'Motion':
        kind = str(data.get('type', 'fixed'))
        if kind not in {'fixed', 'line', 'circle', 'ellipse', 'polygon', 'bezier', 'hidden'}:
            raise ValueError(f'Unsupported motion type: {kind}')
        raw = data.get('points', [])
        if kind == 'fixed':
            pts = (_point(data.get('point', data.get('center', [0.5, 0.5])), 'point'),)
        elif kind in {'line', 'bezier', 'polygon'}:
            if not isinstance(raw, (list, tuple)):
                raise ValueError('points must be an array')
            pts = tuple(_point(p, f'points[{i}]') for i, p in enumerate(raw))
            expected = {'line': 2, 'bezier': 4}.get(kind)
            if expected and len(pts) != expected:
                raise ValueError(f'{kind} requires exactly {expected} points')
            if kind == 'polygon' and not 2 <= len(pts) <= 32:
                raise ValueError('polygon requires 2..32 vertices')
            if kind == 'polygon':
                closed = bool(data.get('closed', True))
                if closed and pts[0] != pts[-1]:
                    pts = pts + (pts[0],)
                corner = _number(data.get('corner_radius', 0), 'corner_radius')
                if corner < 0 or corner > 0.25:
                    raise ValueError('corner_radius must be between 0 and 0.25')
                if corner:
                    pts = _rounded_polygon(pts, corner, closed)
        else:
            pts = ()
        center = _point(data.get('center', [0.5, 0.5]), 'center')
        radius = _number(data.get('radius_x', data.get('radius', 0.1 if kind in ('circle','ellipse') else 0)), 'radius_x')
        radius_y = _number(data.get('radius_y', radius), 'radius_y')
        if radius < 0 or radius_y < 0:
            raise ValueError('radii must be nonnegative')
        if kind in ('circle','ellipse') and (center[0]-radius < 0 or center[0]+radius > 1 or
                                center[1]-radius_y < 0 or center[1]+radius_y > 1):
            raise ValueError('ellipse extends outside the canvas')
        phase = math.radians(_number(data.get('phase_deg', -90), 'phase_deg'))
        turns = _number(data.get('turns', 1), 'turns')
        if turns < 0:
            raise ValueError('turns must be nonnegative')
        speed = data.get('speed')
        if speed is not None:
            speed = _number(speed, 'speed')
            if speed <= 0:
                raise ValueError('speed must be positive')
        easing = data.get('easing', 'linear')
        if easing not in ('linear', 'smoothstep'):
            raise ValueError('easing must be linear or smoothstep')
        if speed is not None and easing != 'linear':
            raise ValueError('speed and easing=smoothstep cannot be combined')
        jitter = data.get('jitter', False)
        if isinstance(jitter, Mapping):
            jitter_px = _number(jitter.get('amplitude_px', 3.0) if jitter.get('enabled', True) else 0, 'jitter.amplitude_px')
            seed = jitter.get('seed', 42)
            moving_factor = _number(jitter.get('moving_factor', 0.15), 'jitter.moving_factor')
            transition = _number(jitter.get('transition', 0.25), 'jitter.transition')
        else:
            jitter_px = 3.0 if jitter is True else 0.0
            seed = 42
            moving_factor = 0.15
            transition = 0.25
        if not 0 <= moving_factor <= 1 or not 0 <= transition <= 5:
            raise ValueError('jitter moving_factor and transition out of range')
        if jitter_px < 0 or jitter_px > 32:
            raise ValueError('jitter amplitude must be in 0..32 px')
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError('jitter seed must be an integer')
        return cls(kind, pts, center, radius, phase, bool(data.get('clockwise', True)),
                   turns, bool(data.get('loop', False)), speed, easing, radius_y, jitter_px, seed, moving_factor, transition)

    @property
    def distances(self) -> tuple[float, ...]:
        if self.kind in ('line', 'polygon'):
            return tuple(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))
        if self.kind in ('circle','ellipse'):
            return tuple(math.hypot(self.radius*(math.cos(2*math.pi*i/128)-math.cos(2*math.pi*(i-1)/128)),
                                    self.radius_y*(math.sin(2*math.pi*i/128)-math.sin(2*math.pi*(i-1)/128))) * self.turns
                         for i in range(1,129))
        if self.kind == 'bezier':
            return tuple(math.dist(_bezier(self.points, (i-1)/80), _bezier(self.points, i/80))
                         for i in range(1, 81))
        return ()

    @property
    def length(self) -> float:
        return sum(self.distances)


def _rounded_polygon(points: tuple[Point, ...], radius: float, closed: bool) -> tuple[Point, ...]:
    """Sample filleted polygon corners with quadratic Bezier arcs.

    radius is normalized distance per adjoining edge, automatically capped at
    35% of the shortest edge. No sharp turns remain in the sampled path.
    """
    vertices = list(points[:-1] if closed and points[0] == points[-1] else points)
    if len(vertices) < 3:
        return points
    result: list[Point] = []
    for i, vertex in enumerate(vertices):
        if not closed and i in (0, len(vertices)-1):
            result.append(vertex)
            continue
        prev = vertices[(i-1) % len(vertices)]
        nxt = vertices[(i+1) % len(vertices)]
        d0, d1 = math.dist(prev, vertex), math.dist(vertex, nxt)
        r = min(radius, d0*.35, d1*.35)
        if r < _EPS:
            result.append(vertex)
            continue
        a = _mix(vertex, prev, r/d0)
        b = _mix(vertex, nxt, r/d1)
        for j in range(9):
            t = j/8
            result.append(((1-t)**2*a[0]+2*(1-t)*t*vertex[0]+t*t*b[0],
                           (1-t)**2*a[1]+2*(1-t)*t*vertex[1]+t*t*b[1]))
    if closed:
        result.append(result[0])
    return tuple(result)


def _jitter_scale(m: Motion, t: float, duration: float) -> float:
    if m.kind == 'fixed' or m.length < _EPS:
        return 1.0
    if m.jitter_transition <= 0:
        return m.moving_factor
    # Smooth initial reduction: no abrupt shake at the beginning of a gesture.
    x = min(1.0, max(0.0, t/m.jitter_transition))
    eased = x*x*(3-2*x)
    scale = 1-(1-m.moving_factor)*eased
    # Increase shake only when the motion actually stops BEFORE the interval ends.
    completion = m.length/m.speed if m.speed is not None and not m.loop else duration
    if completion < duration - _EPS:
        z = min(1.0, max(0.0, (t-completion)/m.jitter_transition))
        z = z*z*(3-2*z)
        scale = scale+(1-scale)*z
    return scale


def _jitter_scale_expr(m: Motion, local: str, duration: float) -> str:
    if m.kind == 'fixed' or m.length < _EPS:
        return '1'
    if m.jitter_transition <= 0:
        return _fmt(m.moving_factor)
    u = f'min(1,max(0,({local})/{_fmt(m.jitter_transition)}))'
    eased = f'({u})*({u})*(3-2*({u}))'
    scale = f'(1-{_fmt(1-m.moving_factor)}*({eased}))'
    completion = m.length/m.speed if m.speed is not None and not m.loop else duration
    if completion < duration - _EPS:
        v = f'min(1,max(0,(({local})-{_fmt(completion)})/{_fmt(m.jitter_transition)}))'
        z = f'({v})*({v})*(3-2*({v}))'
        scale = f'(({scale})+(1-({scale}))*({z}))'
    return scale


def _jitter_terms(m: Motion, t: float, duration: float) -> Point:
    phase = (m.jitter_seed % 997)*0.037
    scale = _jitter_scale(m, t, duration)
    return (scale*m.jitter_px*(.62*math.sin(2*math.pi*2.0*t+phase)+.38*math.sin(2*math.pi*.83*t+phase*1.7)),
            scale*m.jitter_px*(.58*math.sin(2*math.pi*1.93*t+phase*2.1)+.42*math.sin(2*math.pi*1.07*t+phase*.7)))


def _jitter_expr(m: Motion, local: str, k: int) -> str:
    phase = (m.jitter_seed % 997)*0.037
    if k == 0:
        return f'({_fmt(m.jitter_px)}*(0.62*sin(2*PI*2.0*({local})+{_fmt(phase)})+0.38*sin(2*PI*0.83*({local})+{_fmt(phase*1.7)})))'
    return f'({_fmt(m.jitter_px)}*(0.58*sin(2*PI*1.93*({local})+{_fmt(phase*2.1)})+0.42*sin(2*PI*1.07*({local})+{_fmt(phase*.7)})))'


def _fraction(motion: Motion, local_t: float, duration: float) -> float:
    if motion.length < _EPS:
        return 0.0
    u = (local_t * motion.speed / motion.length if motion.speed is not None
         else local_t / duration)
    if motion.loop:
        u %= 1.0
    else:
        u = min(1.0, max(0.0, u))
    if motion.easing == 'smoothstep':
        u = u*u*(3-2*u)
    return u


def position_at(motion: Motion | Mapping[str, Any], local_t: float, duration: float,
                width: int = 960, height: int = 540) -> Point | None:
    """Get motion position at local seconds; None outside [0,duration) or hidden."""
    if not isinstance(motion, Motion):
        motion = Motion.from_dict(motion)
    if duration <= 0:
        raise ValueError('duration must be positive')
    if local_t < 0 or local_t >= duration or motion.kind == 'hidden':
        return None
    if motion.kind == 'fixed':
        p = motion.points[0]
        j = _jitter_terms(motion, local_t, duration)
        return (p[0]+j[0]/width, p[1]+j[1]/height)
    u = _fraction(motion, local_t, duration)
    if motion.kind in ('circle','ellipse'):
        angle = motion.phase + (1 if motion.clockwise else -1)*2*math.pi*motion.turns*u
        j = _jitter_terms(motion, local_t, duration)
        return (motion.center[0]+motion.radius*math.cos(angle)+j[0]/width,
                motion.center[1]+motion.radius_y*math.sin(angle)+j[1]/height)
    if motion.kind == 'bezier':
        p = _bezier(motion.points, u)
        j = _jitter_terms(motion, local_t, duration)
        return p[0]+j[0]/width, p[1]+j[1]/height
    lengths = motion.distances
    remaining = u*sum(lengths)
    for i, segment in enumerate(lengths):
        if remaining <= segment or i == len(lengths)-1:
            p = _mix(motion.points[i], motion.points[i+1],
                        (remaining/segment if segment > _EPS else 0))
            j = _jitter_terms(motion, local_t, duration)
            return p[0]+j[0]/width, p[1]+j[1]/height
        remaining -= segment
    p = motion.points[-1]
    j = _jitter_terms(motion, local_t, duration)
    return p[0]+j[0]/width, p[1]+j[1]/height


def _progress_expr(m: Motion, local: str, duration: float) -> str:
    base = (f'({local})*{_fmt(m.speed/m.length)}' if m.speed is not None and m.length > _EPS
            else f'({local})/{_fmt(duration)}')
    p = f'mod({base},1)' if m.loop else f'min(1,max(0,{base}))'
    if m.easing == 'smoothstep':
        p = f'({p})*({p})*(3-2*({p}))'
    return p


def _bezier_coord_expr(pts: Sequence[Point], k: int, u: str) -> str:
    a,b,c,d = (_fmt(p[k]) for p in pts)
    return f'((1-({u}))^3*{a}+3*(1-({u}))^2*({u})*{b}+3*(1-({u}))*({u})^2*{c}+({u})^3*{d})'


def ffmpeg_position_expr(motion: Motion | Mapping[str, Any], start: float, end: float,
                         width: int, height: int, pointer_size: int = 24,
                         pointer_anchor: tuple[float, float] | None = None) -> tuple[str, str]:
    """Return FFmpeg overlay x/y expressions, evaluated each output frame.

    Coordinates refer to a square pointer PNG; formulas center it on the target.
    Expressions should be single-quoted in the filtergraph (commas need quoting).
    """
    m = motion if isinstance(motion, Motion) else Motion.from_dict(motion)
    if end <= start or width <= 0 or height <= 0 or pointer_size <= 0:
        raise ValueError('invalid time interval, canvas, or pointer size')
    if m.kind == 'hidden':
        raise ValueError('hidden motion should not be overlaid')
    local = f'(t-{_fmt(start)})'
    u = _progress_expr(m, local, end-start)
    if m.kind == 'fixed':
        coords = [_fmt(v) for v in m.points[0]]
    elif m.kind in ('circle','ellipse'):
        angle = f'({_fmt(m.phase)}+{_fmt((1 if m.clockwise else -1)*2*math.pi*m.turns)}*({u}))'
        coords = [f'({_fmt(m.center[0])}+{_fmt(m.radius)}*cos({angle}))',
                  f'({_fmt(m.center[1])}+{_fmt(m.radius_y)}*sin({angle}))']
    elif m.kind == 'bezier':
        # The piecewise inverse-length lookup would produce excessively large FFmpeg
        # expressions; use parameter interpolation (non-uniform spatial speed).
        coords = [_bezier_coord_expr(m.points, k, u) for k in (0, 1)]
    else:
        ds = m.distances
        length = sum(ds)
        coords = []
        for k in (0, 1):
            if length < _EPS:
                coords.append(_fmt(m.points[0][k]))
                continue
            cumulative = [0.0]
            for distance in ds:
                cumulative.append(cumulative[-1] + distance)
            expr = _fmt(m.points[-1][k])
            for i in reversed(range(len(ds))):
                segment = ds[i]
                if segment < _EPS:
                    continue
                threshold = cumulative[i+1]/length
                normalized_start = cumulative[i]/length
                interp = f'(({u})-{_fmt(normalized_start)})/{_fmt(segment/length)}'
                a,b = m.points[i][k],m.points[i+1][k]
                piece = f'({_fmt(a)}+({_fmt(b-a)})*({interp}))'
                expr = f'if(lte({u},{_fmt(threshold)}),{piece},{expr})'
            coords.append(expr)
    factor = _jitter_scale_expr(m, local, end-start)
    jx = f'+({factor})*{_jitter_expr(m, local, 0)}' if m.jitter_px else ''
    jy = f'+({factor})*{_jitter_expr(m, local, 1)}' if m.jitter_px else ''
    ax, ay = pointer_anchor if pointer_anchor is not None else (pointer_size / 2, pointer_size / 2)
    return (f'({coords[0]})*{width}{jx}-{ax:g}',
            f'({coords[1]})*{height}{jy}-{ay:g}')


def validate_schedule(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate and sort non-overlapping half-open events."""
    result = []
    for i, event in enumerate(events):
        start = _number(event['start'], f'event[{i}].start')
        end = _number(event['end'], f'event[{i}].end')
        if start < 0 or end <= start:
            raise ValueError(f'event[{i}]: expected 0 <= start < end')
        motion = Motion.from_dict(event['motion'])
        result.append({'start': start, 'end': end, 'motion': motion})
    result.sort(key=lambda item:item['start'])
    for prev, curr in zip(result, result[1:]):
        if curr['start'] < prev['end'] - _EPS:
            raise ValueError('motion events overlap; each sentence must cancel the previous one')
    return result


def build_overlay_filter(events: Sequence[Mapping[str, Any]], width: int, height: int,
                         pointer_size: int = 24, fps: int = 30) -> str:
    """Return a filter_complex_script using input 0=background, 1=looped PNG.

    Includes [outv] output pad. Events with hidden type are skipped. Temporal
    gating is [start,end), using gte*lt rather than inclusive between().
    """
    if fps <= 0:
        raise ValueError('fps must be positive')
    ordered = validate_schedule(events)
    visible = [event for event in ordered if event['motion'].kind != 'hidden']
    if not visible:
        return '[0:v]format=yuv420p[outv]\n'
    parts = [f'[1:v]format=rgba,split={len(visible)}' + ''.join(f'[ptr{i}]' for i in range(len(visible))) + ';'] if len(visible)>1 else ['[1:v]format=rgba[ptr0];']
    previous = '[0:v]'
    for i, event in enumerate(visible):
        start,end,m = event['start'],event['end'],event['motion']
        x,y = ffmpeg_position_expr(m,start,end,width,height,pointer_size)
        dest = f'[v{i}]'
        enable = f'gte(t,{_fmt(start)})*lt(t,{_fmt(end)})'
        parts.append(f"{previous}[ptr{i}]overlay=x='{x}':y='{y}':eval=frame:enable='{enable}':eof_action=pass{dest};")
        previous = dest
    parts.append(f'{previous}format=yuv420p[outv]')
    return '\n'.join(parts)+'\n'
