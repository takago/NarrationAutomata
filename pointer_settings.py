"""Three-level pointer settings and validated semantic motion conversion."""
from __future__ import annotations

from typing import Any

MODES = {"static", "active", "hidden"}
OVERRIDES = MODES | {"inherit"}
MOTIONS = {"fixed", "line", "ellipse", "rounded_polygon", "hidden"}
DIRECTIONS = {"left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"}


def effective_mode(project: dict, page: int, sentence: dict | None = None) -> str:
    base = project.get("pointer_default_mode", "static")
    if base not in MODES:
        base = "static"
    slide = project.get("pointer_slide_modes", {})
    slide_value = slide.get(str(page), "inherit") if isinstance(slide, dict) else "inherit"
    if slide_value in MODES:
        base = slide_value
    value = (sentence or {}).get("pointer_mode", "inherit")
    return value if value in MODES else base


def normalize_motion(value: Any) -> dict:
    if isinstance(value, str):
        value = {"type": value}
    if not isinstance(value, dict):
        return {"type": "fixed"}
    kind = value.get("type", "fixed")
    if kind not in MOTIONS:
        kind = "fixed"
    result = {"type": kind}
    if kind == "line" and value.get("direction") in DIRECTIONS:
        result["direction"] = value["direction"]
    return result


def create_motion(value: Any, block: dict, size: tuple[int, int]) -> dict:
    """Convert LLM semantic motion to normalized coordinates without trusting its geometry."""
    w, h = size
    if w <= 0 or h <= 0:
        raise ValueError('invalid image size')
    b = block.get('bbox')
    if not isinstance(b, (tuple, list)) or len(b) != 4:
        raise ValueError('no usable bounding box')
    x1, y1, x2, y2 = [float(v) for v in b]
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError('bbox outside canvas')
    x1 /= w; x2 /= w; y1 /= h; y2 /= h
    cx, cy = (x1+x2)/2, (y1+y2)/2
    motion = normalize_motion(value)
    kind = motion['type']
    jitter = {'enabled': True, 'amplitude_px': 2.0, 'frequency': 2.0,
              'moving_factor': 0.15, 'transition': 0.25}
    if kind in ('fixed', 'hidden'):
        # Match the existing pointer position instead of the center of the bbox.
        if kind == 'hidden':
            return {'type': 'hidden'}
        px, py = float(block['x']) / w, float(block['y']) / h
        return {'type': 'fixed', 'point': [min(1,max(0,px)),min(1,max(0,py))], 'jitter': jitter}
    if kind == 'line':
        direction = motion.get('direction', 'left_to_right')
        inset_x = min((x2-x1)*0.1, 0.02)
        inset_y = min((y2-y1)*0.1, 0.02)
        endpoints = {
            'left_to_right': [[x1+inset_x, cy], [x2-inset_x, cy]],
            'right_to_left': [[x2-inset_x, cy], [x1+inset_x, cy]],
            'top_to_bottom': [[cx, y1+inset_y], [cx, y2-inset_y]],
            'bottom_to_top': [[cx, y2-inset_y], [cx, y1+inset_y]],
        }
        return {'type': 'line', 'points': endpoints[direction], 'easing': 'smoothstep', 'jitter': jitter}
    if kind == 'ellipse':
        # Inset to avoid drawing outside the video canvas.
        rx = min((x2-x1)*0.48, cx-0.015, 0.985-cx)
        ry = min((y2-y1)*0.48, cy-0.015, 0.985-cy)
        if min(rx,ry) <= 0.004:
            raise ValueError('target too small for ellipse')
        return {'type':'ellipse','center':[cx,cy], 'radius_x':rx,'radius_y':ry,
                'turns':1,'loop':False,'jitter':jitter}
    if kind == 'rounded_polygon':
        if min(x2-x1, y2-y1) < 0.035:
            raise ValueError('target too small for rounded polygon')
        # Four corners of bbox are only an approximation, not shape recognition.
        return {'type':'polygon','points':[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],
                'corner_radius':min(0.018,(x2-x1)/8,(y2-y1)/8),
                'loop':False,'jitter':jitter}
    raise ValueError('unsupported motion')
