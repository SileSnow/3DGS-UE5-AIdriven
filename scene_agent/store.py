"""File-backed Scene Agent store: import, plan, commit, verify, rollback, undo.

Storage layout (under --root):

    scenes/<scene_id>/
      manifest.json                 # current_version + versions[]
      v0000/scene.json              # canonical object graph (no version fields)
      v0000/assets_inventory.json
      v0000/diff_from_parent.json   # null for v0
      v000N/...
      audit/scene_audit_<run_id>.jsonl
      checkpoints/cp_*.json

Design notes:
- integer linear chain, v0000 immutable, rollback/undo create a new version;
- scene.json is canonical JSON (sorted keys, no spaces) + trailing newline;
- manifest is replaced atomically with os.replace after the version dir is durable;
- commit is single-writer: expected_version + intent base hash;
- license status == draft blocks writes (E_SCENE_LICENSE_UNDECLARED);
- splat assets are read-only (transform ops rejected).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import errors as E
from . import ops
from .util import (atomic_write, atomic_write_json, canonical_json, manifest_bytes,
                   now_iso, read_json, scene_bytes, sha256_bytes)

SCENE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
INTENT_TTL_S = 300
MAX_COMMANDS = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SceneStore:
    def __init__(self, root):
        self.root = Path(root)
        self.scenes_dir = self.root / "scenes"
        self._lock = threading.RLock()
        self._intents = {}
        self._commands = OrderedDict()
        self._seq = 0

    # ---------------------------------------------------------------- helpers
    def _scene_dir(self, scene_id: str) -> Path:
        return self.scenes_dir / scene_id

    def _manifest_path(self, scene_id: str) -> Path:
        return self._scene_dir(scene_id) / "manifest.json"

    def _version_dir(self, scene_id: str, version: int) -> Path:
        return self._scene_dir(scene_id) / f"v{version:04d}"

    @staticmethod
    def _check_scene_id(scene_id):
        if not isinstance(scene_id, str) or not SCENE_ID_RE.match(scene_id):
            raise E.SceneError(E.SCHEMA, "scene_id must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}")

    def _load_manifest(self, scene_id: str) -> dict:
        path = self._manifest_path(scene_id)
        if not path.exists():
            raise E.SceneError(E.NOT_FOUND, f"scene not found: {scene_id}")
        try:
            manifest = read_json(path)
        except (OSError, ValueError) as exc:
            raise E.SceneError(E.MANIFEST_INVALID, f"cannot read manifest: {exc}")
        if manifest.get("schema") != "gaia.scene/v1":
            raise E.SceneError(E.MANIFEST_INVALID, "manifest.schema must be gaia.scene/v1")
        if not isinstance(manifest.get("versions"), list) or not manifest["versions"]:
            raise E.SceneError(E.MANIFEST_INVALID, "manifest.versions is empty")
        return manifest

    def _manifest_sha(self, manifest: dict) -> str:
        return sha256_bytes(manifest_bytes(manifest))

    def _save_manifest(self, scene_id: str, manifest: dict) -> None:
        atomic_write(self._manifest_path(scene_id), manifest_bytes(manifest))

    def _entry(self, manifest: dict, version: int) -> dict:
        for item in manifest["versions"]:
            if int(item["version"]) == int(version):
                return item
        raise E.SceneError(E.VERSION_NOT_FOUND, f"version not found: {version}")

    def _load_scene(self, scene_id: str, version: int) -> dict:
        path = self._version_dir(scene_id, version) / "scene.json"
        if not path.exists():
            raise E.SceneError(E.VERSION_NOT_FOUND, f"version files missing: v{version:04d}")
        try:
            scene = read_json(path)
        except (OSError, ValueError) as exc:
            raise E.SceneError(E.MANIFEST_INVALID, f"cannot read scene.json: {exc}")
        ops.validate_scene(scene)
        if scene.get("scene_id") != scene_id:
            raise E.SceneError(E.SCHEMA, "scene.scene_id does not match directory")
        return scene

    def _resolve_ref(self, body: dict):
        ref = body.get("scene_ref") or {}
        if not isinstance(ref, dict):
            raise E.SceneError(E.PARAM_TYPE, "scene_ref must be an object")
        scene_id = ref.get("scene_id") or body.get("scene_id")
        self._check_scene_id(scene_id)
        manifest = self._load_manifest(scene_id)
        raw_version = ref.get("scene_version", body.get("scene_version"))
        version = int(manifest["current_version"]) if raw_version is None else int(raw_version)
        entry = self._entry(manifest, version)
        if entry.get("status") == "deleted":
            raise E.SceneError(E.VERSION_NOT_FOUND, f"version v{version:04d} is deleted")
        want_hash = ref.get("manifest_sha256", body.get("manifest_sha256"))
        if want_hash and want_hash != self._manifest_sha(manifest):
            raise E.SceneError(E.VERSION_HASH_MISMATCH,
                               "manifest_sha256 does not match current manifest")
        scene = self._load_scene(scene_id, version)
        return manifest, version, scene

    def _license_status(self, manifest: dict) -> str:
        lic = (manifest.get("provenance") or {}).get("license") or {}
        fields = [lic.get("type"), lic.get("holder"), lic.get("evidence_path")]
        return "draft" if any(v in (None, "", "待确认") for v in fields) else "declared"

    def _audit(self, scene_id, run_id, action, ok, version=None, command_id=None, error=None):
        if not run_id:
            return None
        audit_dir = self._scene_dir(scene_id) / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        path = audit_dir / f"scene_audit_{run_id}.jsonl"
        self._seq += 1
        event = {"seq": self._seq, "ts": now_iso(), "run_id": run_id,
                 "action": action, "scene_id": scene_id, "version": version,
                 "command_id": command_id, "ok": bool(ok)}
        if error:
            event["error"] = error
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(canonical_json(event) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return self._seq

    def _require_run_id(self, run_id):
        if not isinstance(run_id, str) or not run_id.strip():
            raise E.SceneError(E.RUN_ID_REQUIRED, "run_id is required for write operations")
        if not re.match(r"^[A-Za-z0-9_.:-]{1,64}$", run_id):
            raise E.SceneError(E.PARAM_TYPE, "run_id has unsupported characters")
        return run_id

    def _cache_get(self, command_id):
        if not command_id:
            return None
        return self._commands.get(command_id)

    def _cache_put(self, command_id, response):
        if not command_id:
            return
        self._commands[command_id] = response
        while len(self._commands) > MAX_COMMANDS:
            self._commands.popitem(last=False)

    # ---------------------------------------------------------------- import
    def import_scene(self, body: dict) -> dict:
        scene_id = body.get("scene_id")
        self._check_scene_id(scene_id)
        run_id = self._require_run_id(body.get("run_id"))
        command_id = body.get("command_id")
        cached = self._cache_get(command_id)
        if cached is not None:
            return cached
        with self._lock:
            if self._manifest_path(scene_id).exists():
                raise E.SceneError(E.ALREADY_EXISTS, f"scene already exists: {scene_id}")
            origin = ops._origin(body.get("origin_wgs84"))
            scene_payload = body.get("scene") if isinstance(body.get("scene"), dict) else body
            elements = scene_payload.get("elements")
            scene = ops.make_scene(scene_id, elements)
            for element in scene["elements"]:
                ops.check_anchor(element, origin)
            assets = body.get("assets") or []
            if not isinstance(assets, list):
                raise E.SceneError(E.PARAM_TYPE, "assets must be a list")
            inventory = {"schema": "gaia.scene_assets/v1", "assets": assets}
            license_obj = body.get("license") or {}
            if not isinstance(license_obj, dict):
                raise E.SceneError(E.PARAM_TYPE, "license must be an object")
            bounds = body.get("bounds_cm")
            world = {
                "coord_system": ops.FRAME,
                "ue_axis": "UE +X = East, UE +Y = South, UE +Z = Up (cm)",
                "origin_wgs84": origin,
                "origin_source": "manifest_declared",
                "units_linear": "cm",
                "units_angular": "deg",
                "up_axis": "Z",
                "handedness": "left",
            }
            if bounds is not None:
                if not isinstance(bounds, dict) or "min" not in bounds or "max" not in bounds:
                    raise E.SceneError(E.PARAM_TYPE, "bounds_cm needs min/max")
                world["bounds_cm"] = {"min": list(bounds["min"]), "max": list(bounds["max"])}
            manifest = {
                "schema": "gaia.scene/v1",
                "scene_id": scene_id,
                "current_version": 0,
                "versions": [],
                "world": world,
                "assets": assets,
                "provenance": {
                    "dataset": body.get("dataset") or "manual_import",
                    "license": license_obj,
                },
            }
            manifest["provenance"]["license_status"] =                 "draft" if self._license_status(manifest) == "draft" else "declared"
            vdir = self._version_dir(scene_id, 0)
            vdir.mkdir(parents=True, exist_ok=True)
            scene_sha = sha256_bytes(scene_bytes(scene))
            atomic_write(vdir / "scene.json", scene_bytes(scene))
            atomic_write_json(vdir / "assets_inventory.json", inventory)
            atomic_write(vdir / "diff_from_parent.json", b"null\n")
            entry = {
                "version": 0, "parent": None, "created_at": now_iso(),
                "created_by": "import", "command_id": command_id, "intent_id": None,
                "scene_json_sha256": scene_sha, "n_elements": len(scene["elements"]),
                "status": "ok", "readback": "pass", "summary": {"added": len(scene["elements"])},
            }
            checks = self._readback(scene_id, 0, manifest, entry)
            bad = [c for c in checks if not c["pass"]]
            if bad:
                raise E.SceneError(bad[0].get("code", E.READBACK_INVARIANT),
                                   bad[0]["detail"], {"level": bad[0]["level"]})
            manifest["versions"].append(entry)
            self._save_manifest(scene_id, manifest)
            audit_seq = self._audit(scene_id, run_id, "scene_import", True, 0, command_id)
            response = self._load_response(scene_id, manifest, 0, scene)
            response["manifest_sha256"] = self._manifest_sha(manifest)
            response["readback"] = "pass"
            response["audit_seq"] = audit_seq
            self._cache_put(command_id, response)
            return response

    # ---------------------------------------------------------------- read
    def _load_response(self, scene_id, manifest, version, scene):
        return {
            "ok": True,
            "scene_id": scene_id,
            "scene_version": version,
            "n_elements": len(scene["elements"]),
            "world": manifest["world"],
            "assets": [{"asset_id": a.get("asset_id"), "type": a.get("type"),
                        "editable": bool(a.get("editable", True))}
                       for a in (manifest.get("assets") or [])],
            "license_status": self._license_status(manifest),
            "readonly": self._license_status(manifest) == "draft",
            "warnings": [],
        }

    def scene_load(self, body: dict) -> dict:
        with self._lock:
            manifest, version, scene = self._resolve_ref(body)
            response = self._load_response(manifest["scene_id"], manifest, version, scene)
            response["manifest_sha256"] = self._manifest_sha(manifest)
            return response

    def scene_query(self, body: dict) -> dict:
        with self._lock:
            manifest, version, scene = self._resolve_ref(body)
            flt = body.get("filter") or {}
            if not isinstance(flt, dict):
                raise E.SceneError(E.BAD_FILTER, "filter must be an object")
            limit = body.get("limit", 50)
            if not isinstance(limit, int) or not (1 <= limit <= 500):
                raise E.SceneError(E.BAD_FILTER, "limit must be 1..500")
            cursor = body.get("cursor")
            try:
                offset = 0 if cursor in (None, "") else int(cursor)
            except (TypeError, ValueError):
                raise E.SceneError(E.CURSOR_INVALID, "cursor must be an integer string")
            if offset < 0:
                raise E.SceneError(E.CURSOR_INVALID, "cursor must be >= 0")
            include_locked = bool(flt.get("include_locked", True))
            classes = flt.get("class")
            if classes is not None and not isinstance(classes, list):
                raise E.SceneError(E.BAD_FILTER, "filter.class must be a list")
            tags = flt.get("tags")
            if tags is not None and not isinstance(tags, list):
                raise E.SceneError(E.BAD_FILTER, "filter.tags must be a list")
            name_contains = flt.get("name_contains")
            bbox = flt.get("bbox_cm")
            hits = []
            for element in scene["elements"]:
                if not include_locked and element.get("locked"):
                    continue
                if classes and element.get("class") not in classes:
                    continue
                if tags and not set(tags).intersection(element.get("tags") or []):
                    continue
                if name_contains:
                    needle = str(name_contains).casefold()
                    hay = [element.get("display_name", "")] + list(element.get("aliases") or [])
                    if not any(needle in str(x).casefold() for x in hay):
                        continue
                if bbox:
                    if (not isinstance(bbox, dict) or "min" not in bbox or "max" not in bbox
                            or not isinstance(bbox["min"], list) or not isinstance(bbox["max"], list)
                            or len(bbox["min"]) != 3 or len(bbox["max"]) != 3):
                        raise E.SceneError(E.BAD_FILTER, "bbox_cm needs min/max triples")
                    loc = element["transform"]["location_cm"]
                    if any(loc[i] < bbox["min"][i] or loc[i] > bbox["max"][i] for i in range(3)):
                        continue
                hits.append(element)
            page = hits[offset:offset + limit]
            next_cursor = str(offset + len(page)) if offset + len(page) < len(hits) else None
            return {"ok": True, "n_total": len(hits), "cursor": next_cursor, "elements": page}

    def scene_get(self, body: dict) -> dict:
        with self._lock:
            manifest, version, scene = self._resolve_ref(body)
            object_id = body.get("object_id")
            if not isinstance(object_id, str):
                raise E.SceneError(E.PARAM_TYPE, "object_id is required")
            target = next((e for e in scene["elements"] if e["object_id"] == object_id), None)
            if not target:
                raise E.SceneError(E.OBJECT_NOT_FOUND, f"object_id not found: {object_id}")
            loc = target["transform"]["location_cm"]
            geom = target.get("geometry") or {}
            world_bounds = None
            if isinstance(geom.get("bounds_local_cm"), dict):
                b = geom["bounds_local_cm"]
                world_bounds = {"min": [loc[i] + b["min"][i] for i in range(3)],
                                "max": [loc[i] + b["max"][i] for i in range(3)]}
            children = [e["object_id"] for e in scene["elements"]
                        if e.get("parent_id") == object_id]
            out = dict(target)
            out["derived"] = {
                "bounds_world_cm": world_bounds,
                "wgs84_center": ops.ue_to_wgs84(loc, manifest["world"]["origin_wgs84"]),
                "children_ids": children,
            }
            return {"ok": True, "element": out}

    # ---------------------------------------------------------------- plan
    def scene_plan(self, body: dict) -> dict:
        with self._lock:
            manifest, version, scene = self._resolve_ref(body)
            ops_list = body.get("ops")
            if ops_list is None:
                ops_list = ops.parse_utterance(body.get("utterance"))
            if not isinstance(ops_list, list) or not ops_list:
                raise E.SceneError(E.PARSE_FAILED, "provide ops[] or a parseable utterance")
            new_version = int(manifest["current_version"]) + 1
            new_scene, changes, inverse_ops = ops.apply_ops(
                scene, ops_list, new_version=new_version,
                origin=manifest["world"]["origin_wgs84"],
                bounds_cm=(manifest["world"] or {}).get("bounds_cm"))
            base_sha = sha256_bytes(scene_bytes(scene))
            intent_id = "intent-" + sha256_bytes(
                (canonical_json({"scene_id": manifest["scene_id"], "scene_version": version,
                                 "base": base_sha, "ops": ops_list}) + "\n").encode("utf-8")
            )[:12]
            now = _utcnow()
            intent = {
                "intent_id": intent_id,
                "scene_id": manifest["scene_id"],
                "scene_version": version,
                "manifest_sha256": self._manifest_sha(manifest),
                "base_scene_sha256": base_sha,
                "ops": ops_list,
                "inverse_ops": inverse_ops,
                "created_at": now.isoformat(timespec="seconds"),
                "expires_at": (now + timedelta(seconds=INTENT_TTL_S)).isoformat(timespec="seconds"),
            }
            self._intents[intent_id] = intent
            summary = self._summary(changes)
            return {
                "ok": True, "intent_id": intent_id, "requires_confirm": True,
                "intent": {"scene_ref": {"scene_id": manifest["scene_id"],
                                         "scene_version": version,
                                         "manifest_sha256": intent["manifest_sha256"]},
                           "ops": ops_list, "summary": summary,
                           "expires_at": intent["expires_at"]},
                "preview_diff": {"summary": summary, "ops": changes},
                "warnings": [],
            }

    @staticmethod
    def _summary(changes):
        added = sum(1 for c in changes if c.get("op") == "add")
        removed = sum(1 for c in changes if c.get("op") == "remove")
        modified_ids = {c.get("object_id") for c in changes if c.get("op") == "modify"}
        renamed = 0
        for c in changes:
            if c.get("path") == "display_name":
                renamed += 1
        return {"added": added, "removed": removed,
                "modified": len(modified_ids), "renamed": renamed}

    # ---------------------------------------------------------------- commit
    def scene_commit(self, body: dict) -> dict:
        if body.get("confirm") is not True:
            raise E.SceneError(E.CONFIRM_REQUIRED, "confirm=true is required for commit")
        run_id = self._require_run_id(body.get("run_id"))
        command_id = body.get("command_id")
        cached = self._cache_get(command_id)
        if cached is not None:
            return cached
        with self._lock:
            manifest, version, scene = self._resolve_ref(body)
            scene_id = manifest["scene_id"]
            intent_id = body.get("intent_id")
            if not intent_id:
                raise E.SceneError(E.CONFIRM_TARGET_MISSING, "intent_id is required with confirm")
            intent = self._intents.get(intent_id)
            if not intent:
                raise E.SceneError(E.INTENT_NOT_FOUND, f"unknown intent: {intent_id}")
            now = _utcnow()
            expires = datetime.fromisoformat(intent["expires_at"])
            if now > expires:
                raise E.SceneError(E.INTENT_EXPIRED, "intent expired; call edit/plan again")
            expected = body.get("expected_version")
            if expected is None:
                raise E.SceneError(E.VERSION_CONFLICT, "expected_version is required")
            expected_int = int(expected)
            if expected_int != int(manifest["current_version"]) or version != expected_int:
                raise E.SceneError(E.VERSION_CONFLICT,
                                   f"expected {expected}, current {manifest['current_version']}")
            if intent["scene_id"] != scene_id or int(intent["scene_version"]) != version:
                raise E.SceneError(E.INTENT_EXPIRED, "intent belongs to another version")
            if self._license_status(manifest) == "draft":
                raise E.SceneError(E.LICENSE_UNDECLARED,
                                   "license is not declared; scene is read-only")
            if intent["base_scene_sha256"] != sha256_bytes(scene_bytes(scene)):
                raise E.SceneError(E.INTENT_EXPIRED, "scene changed since plan; replan")
            new_version = int(manifest["current_version"]) + 1
            new_scene, changes, _inverse = ops.apply_ops(
                scene, intent["ops"], new_version=new_version,
                origin=manifest["world"]["origin_wgs84"],
                bounds_cm=(manifest["world"] or {}).get("bounds_cm"))
            diff = {
                "schema": "gaia.scene_diff/v1", "scene_id": scene_id,
                "from_version": version, "to_version": new_version,
                "created_at": now_iso(), "command_id": command_id,
                "intent_id": intent_id, "ops": changes,
                "summary": self._summary(changes), "inverse_ops": intent["inverse_ops"],
            }
            entry = self._advance(scene_id, manifest, new_scene, diff,
                                  created_by="llm_edit", command_id=command_id,
                                  intent_id=intent_id, run_id=run_id,
                                  summary=diff["summary"], extra={"intent_id": intent_id})
            response = {
                "ok": True, "scene_id": scene_id, "previous_version": version,
                "new_version": new_version,
                "scene_json_sha256": entry["scene_json_sha256"],
                "diff_summary": diff["summary"], "readback": entry["readback"],
                "manifest_sha256": self._manifest_sha(self._load_manifest(scene_id)),
                "audit_seq": entry.get("audit_seq"),
            }
            self._cache_put(command_id, response)
            return response

    def _advance(self, scene_id, manifest, new_scene, diff, *, created_by, command_id,
                 intent_id, run_id, summary, extra=None):
        new_version = int(manifest["current_version"]) + 1
        vdir = self._version_dir(scene_id, new_version)
        vdir.mkdir(parents=True, exist_ok=True)
        scene_sha = sha256_bytes(scene_bytes(new_scene))
        atomic_write(vdir / "scene.json", scene_bytes(new_scene))
        parent_inv = self._version_dir(scene_id, manifest["current_version"]) / "assets_inventory.json"
        inventory = read_json(parent_inv) if parent_inv.exists() else             {"schema": "gaia.scene_assets/v1", "assets": []}
        atomic_write_json(vdir / "assets_inventory.json", inventory)
        atomic_write_json(vdir / "diff_from_parent.json", diff)
        entry = {
            "version": new_version, "parent": int(manifest["current_version"]),
            "created_at": now_iso(), "created_by": created_by,
            "command_id": command_id, "intent_id": intent_id,
            "scene_json_sha256": scene_sha, "n_elements": len(new_scene["elements"]),
            "status": "ok", "readback": "pass", "summary": summary,
        }
        if extra:
            entry.update(extra)
        checks = self._readback(scene_id, new_version, manifest, entry)
        bad = [c for c in checks if not c["pass"]]
        if bad:
            raise E.SceneError(bad[0].get("code", E.READBACK_INVARIANT),
                               bad[0]["detail"], {"level": bad[0]["level"]})
        manifest["versions"].append(entry)
        manifest["current_version"] = new_version
        self._save_manifest(scene_id, manifest)
        audit_seq = self._audit(scene_id, run_id, created_by, True, new_version, command_id)
        entry["audit_seq"] = audit_seq
        return entry

    # ---------------------------------------------------------------- verify
    def _readback(self, scene_id, version, manifest, entry):
        checks = []
        vdir = self._version_dir(scene_id, version)
        scene_path = vdir / "scene.json"
        inv_path = vdir / "assets_inventory.json"
        diff_path = vdir / "diff_from_parent.json"
        # L1
        missing = [str(p.relative_to(vdir)) for p in (scene_path, inv_path, diff_path) if not p.exists()]
        checks.append({"level": "L1", "pass": not missing, "code": E.READBACK_MISSING,
                       "detail": "files present" if not missing else f"missing: {missing}"})
        if missing:
            return checks
        try:
            scene = read_json(scene_path)
            ops.validate_scene(scene)
            inv = read_json(inv_path)
        except E.SceneError as exc:
            checks.append({"level": "L2", "pass": False, "code": E.READBACK_SCHEMA,
                           "detail": exc.message})
            return checks
        except (OSError, ValueError) as exc:
            checks.append({"level": "L2", "pass": False, "code": E.READBACK_SCHEMA,
                           "detail": f"cannot parse: {exc}"})
            return checks
        # L2
        ids = [e["object_id"] for e in scene["elements"]]
        ok_l2 = len(ids) == len(set(ids)) and all(e.get("transform", {}).get("frame") == ops.FRAME
                                                  for e in scene["elements"])
        checks.append({"level": "L2", "pass": ok_l2, "code": E.READBACK_SCHEMA,
                       "detail": f"{len(ids)} elements, unique={len(set(ids)) == len(ids)}"})
        # L3
        detail = []
        try:
            n = len(scene["elements"])
            if n != int(entry["n_elements"]):
                detail.append(f"n_elements {n} != {entry['n_elements']}")
            diff = read_json(diff_path)
            if isinstance(diff, dict):
                by_id = {e["object_id"]: e for e in scene["elements"]}
                for change in diff.get("ops") or []:
                    op = change.get("op")
                    oid = change.get("object_id")
                    if op == "add" and oid not in by_id:
                        detail.append(f"added {oid} missing")
                    elif op == "remove" and oid in by_id:
                        detail.append(f"removed {oid} still present")
                    elif op == "modify":
                        element = by_id.get(oid)
                        if not element:
                            detail.append(f"modified {oid} missing")
                            continue
                        try:
                            actual = ops.get_path(element, change["path"])
                        except (KeyError, IndexError, TypeError):
                            actual = None
                        if actual != change.get("after"):
                            detail.append(f"{oid}.{change['path']} mismatch")
                for e in scene["elements"]:
                    if e.get("wgs84_anchor"):
                        ops.check_anchor(e, manifest["world"]["origin_wgs84"])
        except (OSError, ValueError, KeyError, E.SceneError) as exc:
            detail.append(str(exc))
        checks.append({"level": "L3", "pass": not detail, "code": E.READBACK_INVARIANT,
                       "detail": "invariants ok" if not detail else "; ".join(detail)})
        # L4
        actual = sha256_bytes(scene_path.read_bytes())
        hash_ok = actual == entry["scene_json_sha256"]
        asset_bad = []
        for asset in (inv.get("assets") or []):
            rel = asset.get("path")
            if not rel:
                continue
            target = self._scene_dir(scene_id) / rel
            if not target.exists():
                asset_bad.append(rel)
            elif asset.get("sha256") and sha256_bytes(target.read_bytes()) != asset["sha256"]:
                asset_bad.append(rel)
        checks.append({"level": "L4", "pass": hash_ok and not asset_bad,
                       "code": E.READBACK_HASH_MISMATCH,
                       "detail": "hash ok" if hash_ok and not asset_bad else
                                 f"scene hash match={hash_ok}, bad assets={asset_bad}"})
        return checks

    def scene_verify(self, body: dict) -> dict:
        with self._lock:
            manifest, version, scene = self._resolve_ref(body)
            entry = self._entry(manifest, version)
            checks = self._readback(manifest["scene_id"], version, manifest, entry)
            ok = all(c["pass"] for c in checks)
            return {"ok": ok, "readback": "pass" if ok else "fail", "checks": checks,
                    "assertions": {
                        "elements_conserved": all(c["pass"] for c in checks if c["level"] == "L3"),
                        "hash_match": next(c["pass"] for c in checks if c["level"] == "L4"),
                        "frame_consistent": next(c["pass"] for c in checks if c["level"] == "L2"),
                    }}

    # ---------------------------------------------------------------- versions
    def scene_versions(self, body: dict) -> dict:
        with self._lock:
            scene_id = body.get("scene_id")
            self._check_scene_id(scene_id)
            manifest = self._load_manifest(scene_id)
            known = {int(v["version"]) for v in manifest["versions"]}
            dirs = {}
            for path in self._scene_dir(scene_id).glob("v[0-9][0-9][0-9][0-9]"):
                try:
                    dirs[int(path.name[1:])] = path
                except ValueError:
                    continue
            missing = sorted(v for v in known if v not in dirs)
            missing_files = sorted(v for v in known if v in dirs
                                   and not (dirs[v] / "scene.json").exists())
            orphans = sorted(v for v in dirs if v not in known)
            broken = bool(missing or missing_files)
            gaps = []
            if known:
                lo, hi = min(known), max(known)
                gaps = [n for n in range(lo, hi + 1) if n not in known]
            parent_missing = []
            for item in manifest["versions"]:
                p = item.get("parent")
                if p is not None and int(p) not in known:
                    parent_missing.append(int(item["version"]))
            if parent_missing:
                broken = True
            versions = sorted(manifest["versions"], key=lambda x: int(x["version"]), reverse=True)
            return {
                "ok": True, "scene_id": scene_id,
                "current_version": int(manifest["current_version"]),
                "chain_integrity": "broken" if broken else ("gap" if gaps else "ok"),
                "versions": versions,
                "gaps": gaps, "orphans": orphans,
                "deleted": [int(v["version"]) for v in manifest["versions"]
                            if v.get("status") == "deleted"],
                "missing": missing, "missing_files": missing_files,
                "parent_missing": parent_missing,
            }

    # ---------------------------------------------------------------- rollback / undo
    def scene_rollback(self, body: dict) -> dict:
        if body.get("confirm") is not True:
            raise E.SceneError(E.CONFIRM_REQUIRED, "confirm=true is required for rollback")
        run_id = self._require_run_id(body.get("run_id"))
        command_id = body.get("command_id")
        cached = self._cache_get(command_id)
        if cached is not None:
            return cached
        with self._lock:
            scene_id = body.get("scene_id")
            self._check_scene_id(scene_id)
            manifest = self._load_manifest(scene_id)
            current = int(manifest["current_version"])
            if int(body.get("expected_version", -1)) != current:
                raise E.SceneError(E.VERSION_CONFLICT,
                                   f"expected {body.get('expected_version')}, current {current}")
            to_version = int(body.get("to_version", -1))
            target_entry = self._entry(manifest, to_version)
            if target_entry.get("status") == "deleted":
                raise E.SceneError(E.ROLLBACK_TARGET_DELETED, "target version is deleted")
            target_scene = self._load_scene(scene_id, to_version)
            new_scene = json.loads(canonical_json(target_scene))
            new_version = current + 1
            if sha256_bytes(scene_bytes(new_scene)) != target_entry["scene_json_sha256"]:
                raise E.SceneError(E.ROLLBACK_DRIFT,
                                   "rollback scene hash differs from target before write")
            diff = {
                "schema": "gaia.scene_diff/v1", "scene_id": scene_id,
                "from_version": current, "to_version": new_version,
                "created_at": now_iso(), "command_id": command_id, "intent_id": None,
                "rollback_of": to_version, "ops": [],
                "summary": {"rollback_of": to_version}, "inverse_ops": [],
            }
            entry = self._advance(scene_id, manifest, new_scene, diff,
                                  created_by="rollback", command_id=command_id,
                                  intent_id=None, run_id=run_id,
                                  summary=diff["summary"],
                                  extra={"rollback_of": to_version})
            same = True
            response = {"ok": True, "new_version": new_version, "rollback_of": to_version,
                        "readback": entry["readback"], "sha256_equals_target": same,
                        "manifest_sha256": self._manifest_sha(self._load_manifest(scene_id)),
                        "audit_seq": entry.get("audit_seq")}
            self._cache_put(command_id, response)
            return response

    def scene_undo(self, body: dict) -> dict:
        if body.get("confirm") is not True:
            raise E.SceneError(E.CONFIRM_REQUIRED, "confirm=true is required for undo")
        run_id = self._require_run_id(body.get("run_id"))
        command_id = body.get("command_id")
        cached = self._cache_get(command_id)
        if cached is not None:
            return cached
        with self._lock:
            scene_id = body.get("scene_id")
            self._check_scene_id(scene_id)
            manifest = self._load_manifest(scene_id)
            current = int(manifest["current_version"])
            if int(body.get("expected_version", -1)) != current:
                raise E.SceneError(E.VERSION_CONFLICT,
                                   f"expected {body.get('expected_version')}, current {current}")
            of_version = int(body.get("of_version", current))
            if of_version != current:
                raise E.SceneError(E.UNDO_UNAVAILABLE, "only the current version can be undone")
            current_scene = self._load_scene(scene_id, current)
            diff_path = self._version_dir(scene_id, current) / "diff_from_parent.json"
            diff = read_json(diff_path)
            if not isinstance(diff, dict):
                raise E.SceneError(E.UNDO_UNAVAILABLE, "version 0 has no diff to undo")
            # undo a rollback by rolling back to the pre-rollback version
            if diff.get("rollback_of") is not None:
                target = int(diff.get("from_version"))
                target_entry = self._entry(manifest, target)
                target_scene = self._load_scene(scene_id, target)
                new_scene = json.loads(canonical_json(target_scene))
                if sha256_bytes(scene_bytes(new_scene)) != target_entry["scene_json_sha256"]:
                    raise E.SceneError(E.UNDO_UNAVAILABLE,
                                       "undo hash differs from target before write")
                new_diff = {
                    "schema": "gaia.scene_diff/v1", "scene_id": scene_id,
                    "from_version": current, "to_version": current + 1,
                    "created_at": now_iso(), "command_id": command_id, "intent_id": None,
                    "undo_of": current, "ops": [], "summary": {"undo_of": current},
                    "inverse_ops": [],
                }
                entry = self._advance(scene_id, manifest, new_scene, new_diff,
                                      created_by="undo", command_id=command_id,
                                      intent_id=None, run_id=run_id,
                                      summary=new_diff["summary"], extra={"undo_of": current})
                same = True
                response = {"ok": True, "new_version": current + 1, "undo_of": current,
                            "restored_sha256": entry["scene_json_sha256"], "readback": "pass",
                            "sha256_equals_target": same}
                self._cache_put(command_id, response)
                return response
            inverse = diff.get("inverse_ops") or []
            if not inverse:
                raise E.SceneError(E.UNDO_UNAVAILABLE, "diff has no inverse_ops")
            new_version = current + 1
            new_scene, changes, _inv = ops.apply_ops(
                current_scene, inverse, new_version=new_version,
                origin=manifest["world"]["origin_wgs84"],
                bounds_cm=(manifest["world"] or {}).get("bounds_cm"))
            parent_entry = self._entry(manifest, current - 1) if current > 0 else None
            if parent_entry is not None and sha256_bytes(scene_bytes(new_scene)) != parent_entry["scene_json_sha256"]:
                raise E.SceneError(E.UNDO_UNAVAILABLE,
                                   "undo result is not byte-identical to the previous version before write")
            new_diff = {
                "schema": "gaia.scene_diff/v1", "scene_id": scene_id,
                "from_version": current, "to_version": new_version,
                "created_at": now_iso(), "command_id": command_id, "intent_id": None,
                "undo_of": current, "ops": changes,
                "summary": self._summary(changes), "inverse_ops": [],
            }
            entry = self._advance(scene_id, manifest, new_scene, new_diff,
                                  created_by="undo", command_id=command_id,
                                  intent_id=None, run_id=run_id,
                                  summary=new_diff["summary"], extra={"undo_of": current})
            same = True
            response = {"ok": True, "new_version": new_version, "undo_of": current,
                        "restored_sha256": entry["scene_json_sha256"],
                        "readback": entry["readback"], "sha256_equals_target": same}
            self._cache_put(command_id, response)
            return response

    # ---------------------------------------------------------------- checkpoints
    def checkpoint_save(self, body: dict) -> dict:
        run_id = self._require_run_id(body.get("run_id"))
        with self._lock:
            scene_id = body.get("scene_id")
            self._check_scene_id(scene_id)
            manifest = self._load_manifest(scene_id)
            version = int(body.get("version", manifest["current_version"]))
            entry = self._entry(manifest, version)
            scene = self._load_scene(scene_id, version)
            cp_id = "cp_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
            payload = {
                "schema": "gaia.scene_checkpoint/v1", "checkpoint_id": cp_id,
                "scene_id": scene_id, "version": version,
                "label": body.get("label") or "", "note": body.get("note") or "",
                "created_at": now_iso(), "scene_json_sha256": entry["scene_json_sha256"],
                "manifest_sha256": self._manifest_sha(manifest), "scene": scene,
            }
            cp_dir = self._scene_dir(scene_id) / "checkpoints"
            cp_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(cp_dir / f"{cp_id}.json", payload)
            self._audit(scene_id, run_id, "checkpoint_save", True, version, body.get("command_id"))
            return {"ok": True, "checkpoint_id": cp_id,
                    "scene_json_sha256": entry["scene_json_sha256"]}

    def checkpoint_open(self, body: dict) -> dict:
        if body.get("confirm") is not True:
            raise E.SceneError(E.CONFIRM_REQUIRED, "confirm=true is required for checkpoint/open")
        run_id = self._require_run_id(body.get("run_id"))
        command_id = body.get("command_id")
        cached = self._cache_get(command_id)
        if cached is not None:
            return cached
        with self._lock:
            scene_id = body.get("scene_id")
            self._check_scene_id(scene_id)
            manifest = self._load_manifest(scene_id)
            current = int(manifest["current_version"])
            if int(body.get("expected_version", -1)) != current:
                raise E.SceneError(E.VERSION_CONFLICT,
                                   f"expected {body.get('expected_version')}, current {current}")
            cp_id = body.get("checkpoint_id")
            if not isinstance(cp_id, str) or not re.match(r"^cp_[A-Za-z0-9_]+$", cp_id):
                raise E.SceneError(E.CHECKPOINT_NOT_FOUND, "invalid checkpoint_id")
            path = self._scene_dir(scene_id) / "checkpoints" / f"{cp_id}.json"
            if not path.exists():
                raise E.SceneError(E.CHECKPOINT_NOT_FOUND, f"checkpoint not found: {cp_id}")
            cp = read_json(path)
            scene = cp.get("scene")
            if not isinstance(scene, dict):
                raise E.SceneError(E.CHECKPOINT_CORRUPT, "checkpoint has no scene")
            ops.validate_scene(scene)
            actual = sha256_bytes(scene_bytes(scene))
            if actual != cp.get("scene_json_sha256"):
                raise E.SceneError(E.CHECKPOINT_CORRUPT, "checkpoint scene hash mismatch")
            new_scene = json.loads(canonical_json(scene))
            new_version = current + 1
            if sha256_bytes(scene_bytes(new_scene)) != cp["scene_json_sha256"]:
                raise E.SceneError(E.CHECKPOINT_CORRUPT, "opened scene hash mismatch before write")
            diff = {
                "schema": "gaia.scene_diff/v1", "scene_id": scene_id,
                "from_version": current, "to_version": new_version,
                "created_at": now_iso(), "command_id": command_id, "intent_id": None,
                "opened_from_checkpoint": cp_id, "ops": [],
                "summary": {"opened_from_checkpoint": cp_id}, "inverse_ops": [],
            }
            entry = self._advance(scene_id, manifest, new_scene, diff,
                                  created_by="checkpoint_open", command_id=command_id,
                                  intent_id=None, run_id=run_id,
                                  summary=diff["summary"],
                                  extra={"opened_from_checkpoint": cp_id})
            same = True
            response = {"ok": True, "new_version": new_version,
                        "opened_from_checkpoint": cp_id, "readback": entry["readback"],
                        "sha256_equals_checkpoint": same}
            self._cache_put(command_id, response)
            return response
