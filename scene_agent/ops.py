"""Scene graph validation, edit ops, inverse ops, and a tiny NL parser.

Design source: Issue #1 (interface design), sections 2.1.3 / 2.2 / 2.3.2.
The PoC keeps scene.json free of version fields so that rollback can be
byte-identical to the target version; version/parent live in manifest/diff.
"""
from __future__ import annotations

import math
import re

from . import errors as E
from .util import deep_copy, get_path, set_path, delete_path

SCENE_SCHEMA = "gaia.scene_graph/v1"
FRAME = "UE_LHS_Zup_cm"
MAX_MOVE_CM = 50000.0          # 500 m, configurable at the caller
ANCHOR_TOL_CM = 50.0           # 0.5 m
M_PER_DEG_LAT = 111320.0

CLASSES = {"building", "pumpjack", "ground", "tank", "pipe", "camera_rig", "marker", "other"}
DOMAIN_CLASSES = CLASSES | {"building_group"}


def _num(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise E.SceneError(E.PARAM_TYPE, f"{what} must be a number")
    if not math.isfinite(float(value)):
        raise E.SceneError(E.PARAM_TYPE, f"{what} must be finite")
    return float(value)


def _vec3(value, what):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise E.SceneError(E.PARAM_TYPE, f"{what} must be [x, y, z]")
    return [_num(v, f"{what}[{i}]") for i, v in enumerate(value)]


def normalize_elements(elements):
    if not isinstance(elements, list) or not elements:
        raise E.SceneError(E.SCHEMA, "elements must be a non-empty list")
    out = []
    seen = set()
    for i, raw in enumerate(elements):
        if not isinstance(raw, dict):
            raise E.SceneError(E.SCHEMA, f"elements[{i}] must be an object")
        obj = deep_copy(raw)
        oid = obj.get("object_id")
        if not isinstance(oid, str) or not oid.strip():
            raise E.SceneError(E.SCHEMA, f"elements[{i}].object_id is required")
        if oid in seen:
            raise E.SceneError(E.SCHEMA, f"duplicate object_id: {oid}")
        seen.add(oid)
        if not isinstance(obj.get("class"), str) or not obj["class"]:
            raise E.SceneError(E.SCHEMA, f"{oid}.class is required")
        transform = obj.get("transform")
        if not isinstance(transform, dict):
            raise E.SceneError(E.SCHEMA, f"{oid}.transform is required")
        if not transform.get("frame"):
            raise E.SceneError(E.FRAME_REQUIRED, f"{oid}.transform.frame is required")
        if transform["frame"] != FRAME:
            raise E.SceneError(E.FRAME_INCONSISTENT,
                               f"{oid}.transform.frame={transform['frame']} != {FRAME}")
        transform["location_cm"] = _vec3(transform.get("location_cm"), f"{oid}.location_cm")
        rot = transform.get("rotation") or {}
        transform["rotation"] = {
            "yaw_deg": _num(rot.get("yaw_deg", 0.0), f"{oid}.yaw_deg"),
            "pitch_deg": _num(rot.get("pitch_deg", 0.0), f"{oid}.pitch_deg"),
            "roll_deg": _num(rot.get("roll_deg", 0.0), f"{oid}.roll_deg"),
        }
        transform["scale"] = _vec3(transform.get("scale", [1.0, 1.0, 1.0]), f"{oid}.scale")
        if any(s <= 0 for s in transform["scale"]):
            raise E.SceneError(E.PARAM_RANGE, f"{oid}.scale must be > 0")
        geom = obj.get("geometry") or {"kind": "mesh"}
        if not isinstance(geom, dict) or not geom.get("kind"):
            raise E.SceneError(E.SCHEMA, f"{oid}.geometry.kind is required")
        obj["geometry"] = geom
        obj["display_name"] = str(obj.get("display_name") or oid)
        obj["aliases"] = list(obj.get("aliases") or [])
        obj["tags"] = list(obj.get("tags") or [])
        obj["properties"] = dict(obj.get("properties") or {})
        obj["locked"] = bool(obj.get("locked", False))
        obj["parent_id"] = obj.get("parent_id")
        obj["created_in_version"] = int(obj.get("created_in_version", 0))
        obj["last_modified_in_version"] = int(obj.get("last_modified_in_version", 0))
        if "bounds_local_cm" in geom:
            b = geom["bounds_local_cm"]
            geom["bounds_local_cm"] = {"min": _vec3(b.get("min"), f"{oid}.bounds.min"),
                                        "max": _vec3(b.get("max"), f"{oid}.bounds.max")}
        out.append(obj)
    ids = {e["object_id"] for e in out}
    for e in out:
        if e.get("parent_id") and e["parent_id"] not in ids:
            raise E.SceneError(E.SCHEMA, f"{e['object_id']}.parent_id does not exist")
    return out


def make_scene(scene_id: str, elements) -> dict:
    return {"schema": SCENE_SCHEMA, "scene_id": scene_id,
            "elements": normalize_elements(elements)}


def validate_scene(scene: dict) -> dict:
    if not isinstance(scene, dict) or scene.get("schema") != SCENE_SCHEMA:
        raise E.SceneError(E.SCHEMA, f"scene.schema must be {SCENE_SCHEMA}")
    scene["elements"] = normalize_elements(scene.get("elements"))
    return scene


def _origin(origin):
    if not isinstance(origin, dict):
        raise E.SceneError(E.SCHEMA, "origin_wgs84 is required")
    return {"lat": _num(origin.get("lat"), "origin.lat"),
            "lon": _num(origin.get("lon"), "origin.lon"),
            "alt": _num(origin.get("alt", 0.0), "origin.alt")}


def ue_to_wgs84(location_cm, origin) -> dict:
    o = _origin(origin)
    east_m = location_cm[0] / 100.0
    north_m = -location_cm[1] / 100.0
    up_m = location_cm[2] / 100.0
    lat = o["lat"] + north_m / M_PER_DEG_LAT
    lon = o["lon"] + east_m / (M_PER_DEG_LAT * math.cos(math.radians(o["lat"])))
    return {"lat": round(lat, 9), "lon": round(lon, 9), "alt_abs_m": round(o["alt"] + up_m, 4)}


def wgs84_to_ue(anchor, origin) -> list:
    o = _origin(origin)
    north_m = (_num(anchor.get("lat"), "anchor.lat") - o["lat"]) * M_PER_DEG_LAT
    east_m = (_num(anchor.get("lon"), "anchor.lon") - o["lon"]) * M_PER_DEG_LAT * math.cos(math.radians(o["lat"]))
    alt_m = _num(anchor.get("alt_abs_m", anchor.get("alt", o["alt"])), "anchor.alt") - o["alt"]
    return [east_m * 100.0, -north_m * 100.0, alt_m * 100.0]


def check_anchor(element, origin) -> None:
    anchor = element.get("wgs84_anchor")
    if not anchor:
        return
    expected = ue_to_wgs84(element["transform"]["location_cm"], origin)
    got_ue = wgs84_to_ue(anchor, origin)
    want_ue = element["transform"]["location_cm"]
    dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(got_ue, want_ue)))
    if dist > ANCHOR_TOL_CM:
        raise E.SceneError(
            E.FRAME_INCONSISTENT,
            f"{element['object_id']}.wgs84_anchor is {dist:.1f} cm away from location_cm",
            {"object_id": element["object_id"], "distance_cm": round(dist, 2)})
    _ = expected


def _editable(element):
    if element.get("editable") is False:
        return False
    geom = element.get("geometry") or {}
    return geom.get("kind") not in ("splat", "splat_ref") and geom.get("editable", True) is not False


def _target_objects(scene, op):
    elements = scene["elements"]
    by_id = {e["object_id"]: e for e in elements}
    targets = op.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise E.SceneError(E.PARAM_TYPE, f"{op.get('op')}: targets is required")
    found = []
    for t in targets:
        if not isinstance(t, dict):
            raise E.SceneError(E.PARAM_TYPE, "target must be an object")
        if t.get("object_id"):
            obj = by_id.get(t["object_id"])
            if not obj:
                raise E.SceneError(E.OBJECT_NOT_FOUND, f"object_id not found: {t['object_id']}")
            found.append(obj)
        elif t.get("name"):
            needle = str(t["name"]).strip().casefold()
            hits = [e for e in elements
                    if e["display_name"].casefold() == needle
                    or any(str(a).casefold() == needle for a in e.get("aliases", []))]
            if not hits:
                raise E.SceneError(E.OBJECT_NOT_FOUND, f"name not found: {t['name']}")
            if len(hits) > 1:
                raise E.SceneError(E.AMBIGUOUS_TARGET, f"name matches {len(hits)} objects: {t['name']}",
                                   {"object_ids": [e["object_id"] for e in hits]})
            found.append(hits[0])
        else:
            raise E.SceneError(E.PARAM_TYPE, "target needs object_id or name")
    return found


def _check_write(element, op_name, touch_geometry=True):
    if element.get("locked"):
        raise E.SceneError(E.OBJECT_LOCKED, f"{element['object_id']} is locked")
    if touch_geometry and not _editable(element):
        raise E.SceneError(E.ASSET_NOT_EDITABLE, f"{element['object_id']} is a read-only splat asset")


def _record_change(changes, oid, path, before, after):
    if before == after:
        return
    changes.append({"op": "modify", "object_id": oid, "path": path,
                    "before": before, "after": after})


def _apply_translate(scene, op):
    delta = _vec3((op.get("params") or {}).get("delta"), "delta")
    frame = (op.get("params") or {}).get("frame")
    if not frame:
        raise E.SceneError(E.FRAME_REQUIRED, "translate requires params.frame")
    if frame != FRAME:
        raise E.SceneError(E.FRAME_INCONSISTENT, f"translate frame {frame} != {FRAME}")
    if math.sqrt(sum(v * v for v in delta)) > MAX_MOVE_CM:
        raise E.SceneError(E.PARAM_RANGE, f"translate {delta} exceeds {MAX_MOVE_CM} cm")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "translate")
        before = list(e["transform"]["location_cm"])
        before_anchor = deep_copy(e.get("wgs84_anchor"))
        after = [before[i] + delta[i] for i in range(3)]
        _record_change(changes, e["object_id"], "transform.location_cm", before, after)
        e["transform"]["location_cm"] = after
        if e.get("wgs84_anchor"):
            e["wgs84_anchor"] = ue_to_wgs84(after, scene.get("_origin") or {})
        if before_anchor:
            inverses.append({"op": "set_anchor", "targets": [{"object_id": e["object_id"]}],
                             "params": {"anchor": before_anchor}})
        inverses.append({"op": "translate", "targets": [{"object_id": e["object_id"]}],
                         "params": {"delta": [-v for v in delta], "frame": FRAME,
                                    "delta_semantics": "world_axis"}})
    return changes, inverses


def _apply_set_anchor(scene, op):
    params = op.get("params") or {}
    anchor = params.get("anchor")
    if anchor is not None and not isinstance(anchor, dict):
        raise E.SceneError(E.PARAM_TYPE, "anchor must be an object or null")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "set_anchor", touch_geometry=False)
        before = deep_copy(e.get("wgs84_anchor"))
        _record_change(changes, e["object_id"], "wgs84_anchor", before, anchor)
        if anchor is None:
            e.pop("wgs84_anchor", None)
        else:
            e["wgs84_anchor"] = deep_copy(anchor)
        inverses.append({"op": "set_anchor", "targets": [{"object_id": e["object_id"]}],
                         "params": {"anchor": before}})
    return changes, inverses


def _apply_rotate(scene, op):
    yaw = _num((op.get("params") or {}).get("yaw_delta_deg"), "yaw_delta_deg")
    if abs(yaw) > 3600:
        raise E.SceneError(E.PARAM_RANGE, "yaw_delta_deg exceeds 3600")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "rotate")
        before = e["transform"]["rotation"]["yaw_deg"]
        after = ((before + yaw + 180.0) % 360.0) - 180.0
        _record_change(changes, e["object_id"], "transform.rotation.yaw_deg", before, after)
        e["transform"]["rotation"]["yaw_deg"] = after
        inverses.append({"op": "rotate", "targets": [{"object_id": e["object_id"]}],
                         "params": {"yaw_delta_deg": -yaw}})
    return changes, inverses


def _apply_scale(scene, op):
    raw = (op.get("params") or {}).get("factor")
    factor = _vec3(raw, "factor") if isinstance(raw, list) else [_num(raw, "factor")] * 3
    if any(f <= 0 or f > 100 for f in factor):
        raise E.SceneError(E.PARAM_RANGE, "scale factor must be in (0, 100]")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "scale")
        before = list(e["transform"]["scale"])
        after = [round(before[i] * factor[i], 9) for i in range(3)]
        _record_change(changes, e["object_id"], "transform.scale", before, after)
        e["transform"]["scale"] = after
        geom = e.get("geometry") or {}
        if isinstance(geom.get("bounds_local_cm"), dict):
            b = geom["bounds_local_cm"]
            geom["bounds_local_cm"] = {"min": [b["min"][i] * factor[i] for i in range(3)],
                                        "max": [b["max"][i] * factor[i] for i in range(3)]}
        inverses.append({"op": "scale", "targets": [{"object_id": e["object_id"]}],
                         "params": {"factor": [1.0 / f for f in factor]}})
    return changes, inverses


def _apply_rename(scene, op):
    params = op.get("params") or {}
    name = params.get("display_name")
    if not isinstance(name, str) or not name.strip():
        raise E.SceneError(E.PARAM_TYPE, "display_name must be a non-empty string")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "rename", touch_geometry=False)
        before_name, before_aliases = e["display_name"], list(e.get("aliases", []))
        after_aliases = list(params.get("aliases", before_aliases))
        _record_change(changes, e["object_id"], "display_name", before_name, name)
        _record_change(changes, e["object_id"], "aliases", before_aliases, after_aliases)
        e["display_name"] = name
        e["aliases"] = after_aliases
        inverses.append({"op": "rename", "targets": [{"object_id": e["object_id"]}],
                         "params": {"display_name": before_name, "aliases": before_aliases}})
    return changes, inverses


def _apply_set_property(scene, op):
    params = op.get("params") or {}
    key = params.get("key")
    if not isinstance(key, str) or not key:
        raise E.SceneError(E.PARAM_TYPE, "properties key is required")
    if "value" not in params:
        raise E.SceneError(E.PARAM_TYPE, "properties value is required")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "set_property", touch_geometry=False)
        props = e.setdefault("properties", {})
        had = key in props
        before = props.get(key)
        after = params["value"]
        _record_change(changes, e["object_id"], f"properties.{key}", before, after)
        props[key] = after
        if had:
            inverses.append({"op": "set_property", "targets": [{"object_id": e["object_id"]}],
                             "params": {"key": key, "value": before}})
        else:
            inverses.append({"op": "unset_property", "targets": [{"object_id": e["object_id"]}],
                             "params": {"key": key}})
    return changes, inverses


def _apply_delete(scene, op):
    changes, inverses = [], []
    ids = {e["object_id"] for e in _target_objects(scene, op)}
    for e in list(scene["elements"]):
        if e["object_id"] in ids:
            _check_write(e, "delete")
            children = [c["object_id"] for c in scene["elements"] if c.get("parent_id") == e["object_id"]]
            if children:
                raise E.SceneError(E.PARAM_TYPE,
                                   f"cannot delete {e['object_id']}: has children {children}")
            changes.append({"op": "remove", "object_id": e["object_id"], "element": deep_copy(e)})
            inverses.append({"op": "add", "params": {"element": deep_copy(e)}})
            scene["elements"].remove(e)
    return changes, inverses


def _apply_add(scene, op):
    params = op.get("params") or {}
    element = params.get("element")
    if not isinstance(element, dict):
        raise E.SceneError(E.PARAM_TYPE, "add requires params.element")
    oid = element.get("object_id")
    if any(e["object_id"] == oid for e in scene["elements"]):
        raise E.SceneError(E.SCHEMA, f"duplicate object_id: {oid}")
    normalized = normalize_elements([element])[0]
    normalized["created_in_version"] = int(params.get("created_in_version", 0))
    normalized["last_modified_in_version"] = normalized["created_in_version"]
    scene["elements"].append(normalized)
    return ([{"op": "add", "object_id": oid, "element": deep_copy(normalized)}],
            [{"op": "delete", "targets": [{"object_id": oid}]}])


def _apply_unset_property(scene, op):
    params = op.get("params") or {}
    key = params.get("key")
    if not isinstance(key, str) or not key:
        raise E.SceneError(E.PARAM_TYPE, "properties key is required")
    changes, inverses = [], []
    for e in _target_objects(scene, op):
        _check_write(e, "unset_property", touch_geometry=False)
        props = e.setdefault("properties", {})
        if key not in props:
            continue
        before = props.get(key)
        _record_change(changes, e["object_id"], f"properties.{key}", before, None)
        del props[key]
        inverses.append({"op": "set_property", "targets": [{"object_id": e["object_id"]}],
                         "params": {"key": key, "value": before}})
    return changes, inverses


_HANDLERS = {
    "translate": _apply_translate,
    "set_anchor": _apply_set_anchor,
    "rotate": _apply_rotate,
    "scale": _apply_scale,
    "rename": _apply_rename,
    "set_property": _apply_set_property,
    "unset_property": _apply_unset_property,
    "delete": _apply_delete,
    "add": _apply_add,
}


def _check_bounds(scene, touched_ids):
    world = scene.get("_bounds_cm")
    if not world:
        return
    lo, hi = world.get("min"), world.get("max")
    if not (isinstance(lo, list) and isinstance(hi, list)):
        return
    for e in scene["elements"]:
        if e["object_id"] not in touched_ids:
            continue
        loc = e["transform"]["location_cm"]
        b = (e.get("geometry") or {}).get("bounds_local_cm")
        if b:
            e_lo = [loc[i] + b["min"][i] for i in range(3)]
            e_hi = [loc[i] + b["max"][i] for i in range(3)]
        else:
            e_lo = e_hi = list(loc)
        for i in range(3):
            if e_lo[i] < lo[i] or e_hi[i] > hi[i]:
                raise E.SceneError(
                    E.BOUNDS_VIOLATION,
                    f"{e['object_id']} leaves scene bounds on axis {i}",
                    {"object_id": e["object_id"], "axis": i,
                     "bounds_min": e_lo, "bounds_max": e_hi, "world": world})


def apply_ops(scene: dict, ops: list, *, new_version: int, origin=None, bounds_cm=None):
    """Pure function: returns (new_scene, changes, inverse_ops)."""
    if not isinstance(ops, list) or not ops:
        raise E.SceneError(E.NOOP, "ops is empty")
    new = deep_copy(scene)
    new["_origin"] = origin
    new["_bounds_cm"] = bounds_cm
    changes, inverses = [], []
    touched = set()
    for op in ops:
        if not isinstance(op, dict):
            raise E.SceneError(E.PARAM_TYPE, "op must be an object")
        kind = op.get("op")
        handler = _HANDLERS.get(kind)
        if not handler:
            raise E.SceneError(E.PARAM_TYPE, f"unknown op: {kind}")
        c, inv = handler(new, op)
        for ch in c:
            if ch.get("object_id"):
                touched.add(ch["object_id"])
        changes.extend(c)
        inverses.extend(inv)
    if not changes:
        raise E.SceneError(E.NOOP, "net change is zero")
    _check_bounds(new, touched)
    for e in new["elements"]:
        if e["object_id"] in touched and e.get("wgs84_anchor"):
            check_anchor(e, origin or {})
    new.pop("_origin", None)
    new.pop("_bounds_cm", None)
    inverses.reverse()
    return new, changes, inverses


_DIRS = {"东": [1, 0, 0], "西": [-1, 0, 0], "南": [0, 1, 0], "北": [0, -1, 0],
         "上": [0, 0, 1], "下": [0, 0, -1]}


def parse_utterance(text: str):
    """Very small deterministic NL parser for the PoC demo.

    Supported: 把<X>往<方向>移<N>米 / 把<X>旋转<N>度(顺时针|逆时针).
    Anything else -> E_SCENE_PARSE_FAILED. The LLM path is supposed to produce
    structured ops; this parser only exists so the service is demoable offline.
    """
    if not isinstance(text, str) or not text.strip():
        raise E.SceneError(E.PARSE_FAILED, "utterance is empty")
    s = text.strip()
    m = re.search(r"(?:把|将)?\s*(.+?)\s*(?:往|向)\s*(东|西|南|北|上|下)\s*(?:方向)?\s*"
                  r"(?:移|平移|移动)\s*([0-9]+(?:\.[0-9]+)?)\s*(米|m|厘米|cm)", s)
    if m:
        name, direction, num, unit = m.groups()
        scale = 100.0 if unit in ("米", "m") else 1.0
        d = _DIRS[direction]
        delta = [v * float(num) * scale for v in d]
        return [{"op": "translate", "targets": [{"name": name.strip()}],
                 "params": {"delta": delta, "frame": FRAME, "delta_semantics": "world_axis"}}]
    m = re.search(r"(?:把|将)?\s*(.+?)\s*(?:旋转|转)\s*([0-9]+(?:\.[0-9]+)?)\s*度\s*(顺时针|逆时针)?", s)
    if m:
        name, deg, direction = m.groups()
        yaw = float(deg) * (1.0 if direction != "逆时针" else -1.0)
        return [{"op": "rotate", "targets": [{"name": name.strip()}],
                 "params": {"yaw_delta_deg": yaw}}]
    raise E.SceneError(E.PARSE_FAILED, f"cannot parse: {text}")
