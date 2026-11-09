#!/usr/bin/env python
"""Lead 独立黑盒验收：按 llm_drone/spec/PROTOCOL.md 复跑 CONTRACT.md §6 验收标准。

不 import 任何 sim/safety/orchestrator 代码，只走 HTTP，避免"自己测自己"。
用法（在项目任意位置）：
    python dji_ue5_3dgs/llm_drone/logs/lead/verify_acceptance.py [--port 8766]
输出：llm_drone/logs/lead/acceptance_<ts>.json + .md，控制台摘要。
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LLM_DRONE = os.path.abspath(os.path.join(HERE, "..", ".."))
SPEC = os.path.join(LLM_DRONE, "spec")
PROJECT = os.path.abspath(os.path.join(LLM_DRONE, ".."))
AUDIT_DIR = os.path.join(LLM_DRONE, "logs", "drone-sim")

RESULTS = []
DETAILS = {}


def rec(name, ok, detail="", extra=None):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    if extra:
        DETAILS.setdefault(name, {}).update(extra)
    print(("PASS " if ok else "FAIL ") + name + ("  | " + str(detail) if detail else ""))
    return ok


def http(method, path, body=None, base="", timeout=15):
    url = base.rstrip("/") + path
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {"_raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return {"_http_error": e.code, "_raw": raw}
    except Exception as e:
        return {"_net_error": str(e)}


def wait_health(base, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = http("GET", "/v1/health", base=base, timeout=3)
        if r.get("ok") and ("backend" in r or "version" in r):
            return r
        time.sleep(0.5)
    return None


def cmd(base, tool, args=None, confirm=False, run_id=None, cid=None, timeout=20):
    body = {"command_id": cid or ("lead-%d-%s" % (int(time.time() * 1000), tool)),
            "tool": tool, "args": args or {}, "confirm": bool(confirm)}
    if run_id:
        body["run_id"] = run_id
    return http("POST", "/v1/command", body, base=base, timeout=timeout)


def telemetry(base):
    return http("GET", "/v1/telemetry", base=base, timeout=5)


def wait_tele(base, pred, timeout=120, interval=0.3):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        t = telemetry(base)
        last = t
        if "lat" in t and pred(t):
            return t
        time.sleep(interval)
    return last


def reset(base, run_id):
    r = http("POST", "/v1/reset", {"run_id": run_id}, base=base)
    return r.get("ok") is True


def sim_config(base, **kw):
    return http("POST", "/v1/sim/config", kw, base=base)


def load_sample_mission():
    with open(os.path.join(SPEC, "sample_mission.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def fresh_cid(prefix):
    return "lead-%s-%s" % (prefix, datetime.now().strftime("%H%M%S%f")[:12])


def orthonormal(c2w, tol=1e-5):
    # c2w 行主序 4x4: 前三列 = forward,right,up 的 xyz? 按 spec: 列为 [forward,right,up]
    f = c2w[0:3]
    r = c2w[4:7]
    u = c2w[8:11]
    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    return (abs(dot(f, f) - 1) < tol and abs(dot(r, r) - 1) < tol and abs(dot(u, u) - 1) < tol
            and abs(dot(f, r)) < tol and abs(dot(f, u)) < tol and abs(dot(r, u)) < tol)


def find_audit(run_id):
    if not os.path.isdir(AUDIT_DIR):
        return None
    for name in os.listdir(AUDIT_DIR):
        if run_id in name and name.endswith(".jsonl"):
            return os.path.join(AUDIT_DIR, name)
    return None


def read_audit(path):
    events = []
    if not path or not os.path.isfile(path):
        return events
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def start_server(port, log_dir):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "sim_server_accept_%d.log" % port)
    fh = open(log_path, "w", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    candidates = [
        [sys.executable, "-m", "sim.server", "--port", str(port), "--time-scale", "20"],
        [sys.executable, os.path.join(LLM_DRONE, "sim", "drone_agent.py"), "--port", str(port), "--time-scale", "20"],
    ]
    proc = None
    for cmdline in candidates:
        proc = subprocess.Popen(cmdline, cwd=LLM_DRONE, stdout=fh, stderr=subprocess.STDOUT, env=env)
        base = "http://127.0.0.1:%d" % port
        h = wait_health(base, timeout=25)
        if h:
            print("server started:", " ".join(cmdline[:4]), "pid=", proc.pid, "log=", log_path)
            return proc, base, log_path
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
    fh.close()
    return None, None, log_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-start", action="store_true", help="复用已运行的 server")
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = HERE
    base = args.base_url or ("http://127.0.0.1:%d" % args.port)
    proc = None
    if not args.no_start:
        proc, base, log_path = start_server(args.port, log_dir)
        if not base:
            print("FATAL: 无法启动 sim server（尝试 python -m sim.server 与 sim/drone_agent.py），见日志")
            with open(os.path.join(log_dir, "acceptance_%s.json" % ts), "w", encoding="utf-8") as f:
                json.dump({"fatal": "server-not-started"}, f, ensure_ascii=False, indent=2)
            return 2
    try:
        run_checks(base)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()

    ok_n = sum(1 for r in RESULTS if r["ok"])
    summary = {"ts": datetime.now().isoformat(timespec="seconds"), "base_url": base,
               "checks_total": len(RESULTS), "checks_passed": ok_n,
               "checks_failed": len(RESULTS) - ok_n,
               "passed": ok_n == len(RESULTS), "results": RESULTS, "details": DETAILS}
    jpath = os.path.join(log_dir, "acceptance_%s.json" % ts)
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    mpath = os.path.join(log_dir, "acceptance_%s.md" % ts)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("# Lead 独立验收结果（黑盒 HTTP）\n\n- 时间：%s\n- server：%s\n- 结果：%d/%d 通过\n\n| 检查 | 结果 | 说明 |\n|---|---|---|\n"
                % (summary["ts"], base, ok_n, len(RESULTS)))
        for r in RESULTS:
            f.write("| %s | %s | %s |\n" % (r["check"], "PASS" if r["ok"] else "FAIL", str(r["detail"]).replace("|", "/").replace("\n", " ")))
    print("\n=== ACCEPTANCE %d/%d passed ===\njson: %s\nmd:   %s" % (ok_n, len(RESULTS), jpath, mpath))
    return 0 if ok_n == len(RESULTS) else 1


def run_checks(base):
    # ---------- 0. health / telemetry ----------
    h = wait_health(base, timeout=10)
    rec("health: /v1/health 可用", bool(h and h.get("ok")), json.dumps(h, ensure_ascii=False)[:160] if h else "no response")
    t = telemetry(base)
    need = ["ts", "lat", "lon", "alt_rel_m", "battery_pct", "gimbal", "gps", "rc", "mode", "state"]
    missing = [k for k in need if k not in t]
    rec("telemetry: 字段齐备", not missing, "missing=%s" % missing)
    rec("telemetry: 初始 idle/电量100", t.get("state") == "idle" and float(t.get("battery_pct", 0)) >= 99, "state=%s battery=%s" % (t.get("state"), t.get("battery_pct")))

    # ---------- 1. 正向：起飞 → sample_mission 16 点 → 返航降落 ----------
    run_id = "lead_%s_pos" % datetime.now().strftime("%H%M%S")
    rec("reset: 场景重置", reset(base, run_id), "run_id=" + run_id)
    r = cmd(base, "takeoff", {"altitude_m": 40}, confirm=True, run_id=run_id, cid=fresh_cid("takeoff"))
    rec("正向: takeoff(40, confirm) accepted", r.get("ok") is True, json.dumps(r.get("error") or r.get("state"), ensure_ascii=False)[:200])
    t = wait_tele(base, lambda x: float(x.get("alt_rel_m", 0)) >= 39.0, timeout=60)
    rec("正向: 爬升到 40m 悬停", bool(t and float(t.get("alt_rel_m", 0)) >= 39.0), "alt=%.2f state=%s" % (float(t.get("alt_rel_m", 0)) if t else -1, t.get("state") if t else "?"))
    mission = load_sample_mission()
    mission["mission_id"] = "lead-sample-grid"
    r = cmd(base, "goto_waypoints", {"mission": mission, "photo_interval_s": 1}, confirm=True, run_id=run_id, cid=fresh_cid("goto"), timeout=30)
    mid = r.get("mission_id") or (r.get("telemetry") or {}).get("mission_id")
    rec("正向: goto_waypoints(sample_mission) accepted", r.get("ok") is True, "mission_id=%s err=%s" % (mid, json.dumps(r.get("error"), ensure_ascii=False)[:160]))
    # 轮询 mission record
    mr = {}
    t0 = time.time()
    while time.time() - t0 < 180:
        if mid:
            mr = http("GET", "/v1/missions/%s" % mid, base=base, timeout=10)
        else:
            lst = http("GET", "/v1/missions?limit=1", base=base, timeout=10)
            mts = lst.get("missions") or []
            if mts:
                mid = mts[0].get("mission_id")
                mr = http("GET", "/v1/missions/%s" % mid, base=base, timeout=10)
        if mr.get("state") in ("completed", "failed", "aborted"):
            break
        time.sleep(0.4)
    photos = mr.get("photos") or []
    rec("正向: mission completed", mr.get("state") == "completed", "state=%s mission_id=%s" % (mr.get("state"), mid))
    rec("CONTRACT §6-2 正向: 拍照数 >= 16", len(photos) >= 16, "n_photos=%d" % len(photos))
    c2w_ok = all(orthonormal(p.get("c2w", [])) for p in photos) if photos else False
    rec("c2w 正交性（每张照片）", c2w_ok, "n=%d" % len(photos))
    alt_ok = all(abs(float(p.get("alt_rel_m", 0)) - 40.0) < 1.0 for p in photos) if photos else False
    gim_ok = all(abs(float((p.get("gimbal") or {}).get("pitch", 0)) + 45.0) < 1.0 for p in photos) if photos else False
    rec("照片元数据: 高度 40m / 云台 -45°", alt_ok and gim_ok, "alt_ok=%s gimbal_ok=%s" % (alt_ok, gim_ok))
    rec("CONTRACT §6-3: mission stats 完整", bool((mr.get("stats") or {}).get("n_photos")), json.dumps(mr.get("stats"), ensure_ascii=False)[:160])
    r = cmd(base, "return_to_home", {}, confirm=False, run_id=run_id, cid=fresh_cid("rth"))
    rec("正向: return_to_home accepted", r.get("ok") is True, json.dumps(r.get("error"), ensure_ascii=False)[:160])
    t = wait_tele(base, lambda x: x.get("state") in ("idle", "landing") and float(x.get("alt_rel_m", 99)) < 0.6, timeout=120)
    rec("正向: 返航后降落（idle, alt<0.6m）", bool(t and t.get("state") == "idle"), "state=%s alt=%s" % (t.get("state") if t else "?", t.get("alt_rel_m") if t else "?"))

    # ---------- 2. 对抗场景（A1-A10，spec §11.2） ----------
    def reject(name, tool, args, confirm, expect_code, run_id=None, cid=None):
        r = cmd(base, tool, args, confirm=confirm, run_id=run_id, cid=cid or fresh_cid(name))
        code = (r.get("error") or {}).get("code") if isinstance(r.get("error"), dict) else None
        rec("%s: 返回 %s" % (name, expect_code), (r.get("ok") is False and code == expect_code),
            "ok=%s code=%s msg=%s" % (r.get("ok"), code, str((r.get("error") or {}).get("message"))[:120]))

    rid = "lead_a1_%d" % int(time.time())
    reset(base, rid)
    reject("A1 超限高", "takeoff", {"altitude_m": 200.0}, True, "E_ALT_LIMIT", run_id=rid)

    rid = "lead_a2_%d" % int(time.time())
    reset(base, rid)
    cmd(base, "takeoff", {"altitude_m": 40}, confirm=True, run_id=rid, cid=fresh_cid("a2t"))
    wait_tele(base, lambda x: float(x.get("alt_rel_m", 0)) >= 39.0, timeout=60)
    m2 = load_sample_mission()
    m2["mission_id"] = "lead-a2-fence"
    m2["waypoints"][0]["lon"] = m2["waypoints"][0]["lon"] + 800.0 / (111320.0 * math.cos(math.radians(m2["origin_wgs84"]["lat"])))
    reject("A2 飞出围栏", "goto_waypoints", {"mission": m2}, True, "E_GEOFENCE", run_id=rid)

    rid = "lead_a3_%d" % int(time.time())
    reset(base, rid)
    cmd(base, "takeoff", {"altitude_m": 40}, confirm=True, run_id=rid, cid=fresh_cid("a3t"))
    wait_tele(base, lambda x: float(x.get("alt_rel_m", 0)) >= 39.0, timeout=60)
    m3 = load_sample_mission()
    m3["mission_id"] = "lead-a3-nofly"
    m3["waypoints"][0]["lat"] = 39.9048
    m3["waypoints"][0]["lon"] = 116.4080
    reject("A3 飞禁飞区", "goto_waypoints", {"mission": m3}, True, "E_NOFLY", run_id=rid)

    rid = "lead_a4_%d" % int(time.time())
    reset(base, rid)
    sim_config(base, battery_pct=22.0)
    reject("A4 低电量起飞", "takeoff", {"altitude_m": 40.0}, True, "E_BATTERY_TAKEOFF", run_id=rid)

    rid = "lead_a5_%d" % int(time.time())
    reset(base, rid)
    cmd(base, "takeoff", {"altitude_m": 40}, confirm=True, run_id=rid, cid=fresh_cid("a5t"))
    m5 = load_sample_mission()
    m5["mission_id"] = "lead-a5-noconfirm"
    reject("A5 无确认执行", "goto_waypoints", {"mission": m5}, False, "E_CONFIRM_REQUIRED", run_id=rid)

    rid = "lead_a6_%d" % int(time.time())
    reset(base, rid)
    cmd(base, "takeoff", {"altitude_m": 40}, confirm=True, run_id=rid, cid=fresh_cid("a6t"))
    wait_tele(base, lambda x: float(x.get("alt_rel_m", 0)) >= 39.0, timeout=60)
    sim_config(base, battery_pct=19.0)
    t = wait_tele(base, lambda x: x.get("state") == "idle", timeout=150, interval=0.4)
    audit = read_audit(find_audit(rid))
    force = [e for e in audit if e.get("event") == "force_rth"]
    rec("A6 飞行中低电量: 强制 RTH 并落地", bool(t and t.get("state") == "idle" and force), "final_state=%s force_rth_events=%d" % (t.get("state") if t else "?", len(force)))

    rid = "lead_a7_%d" % int(time.time())
    reset(base, rid)
    sim_config(base, gps_fix=1, gps_satellites=6)
    reject("A7 GPS 质量差", "takeoff", {"altitude_m": 40.0}, True, "E_GPS", run_id=rid)

    rid = "lead_a8_%d" % int(time.time())
    reset(base, rid)
    sim_config(base, rc_connected=False)
    reject("A8 遥控链路断开", "takeoff", {"altitude_m": 40.0}, True, "E_RC_LINK", run_id=rid)

    rid = "lead_a9_%d" % int(time.time())
    reset(base, rid)
    reject("A9a 非法参数", "takeoff", {"altitude_m": -5.0}, True, "E_PARAM_RANGE", run_id=rid)
    r = cmd(base, "fly_to_moon", {}, confirm=False, cid=fresh_cid("a9b"))
    code = (r.get("error") or {}).get("code") if isinstance(r.get("error"), dict) else None
    rec("A9b 未知工具: 返回 E_UNKNOWN_TOOL", r.get("ok") is False and code == "E_UNKNOWN_TOOL", "ok=%s code=%s" % (r.get("ok"), code))

    rid = "lead_a10_%d" % int(time.time())
    reset(base, rid)
    reject("A10 real 模式未接入", "set_mode", {"mode": "real"}, True, "E_REAL_NOT_AVAILABLE", run_id=rid)

    # ---------- 3. 审计 ----------
    found = 0
    bad = 0
    sample_events = set()
    for name in os.listdir(AUDIT_DIR) if os.path.isdir(AUDIT_DIR) else []:
        if not (name.startswith("audit_") and name.endswith(".jsonl")):
            continue
        path = os.path.join(AUDIT_DIR, name)
        if not os.path.getmtime(path) > time.time() - 3600:
            continue
        found += 1
        try:
            ev = read_audit(path)
            sample_events.update(e.get("event") for e in ev)
            for e in ev:
                for k in ("ts", "seq", "run_id", "event"):
                    if k not in e:
                        bad += 1
        except Exception:
            bad += 1
    rec("审计: 近 1h audit_*.jsonl 可逐行 json 解析且字段齐备", found > 0 and bad == 0, "files=%d bad=%d" % (found, bad))
    need_events = {"command_received", "safety_check", "command_accepted", "command_rejected"}
    rec("审计: 关键事件类型齐备", need_events.issubset(sample_events), "events=%s" % sorted(sample_events)[:14])


if __name__ == "__main__":
    sys.exit(main())
