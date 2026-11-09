import json
from pathlib import Path
LLM = Path(".")
RUNS = LLM / "demo" / "runs"
FILES = ["request.md","transcript.md","llm_events.jsonl","tool_calls.jsonl","agent_audit.jsonl",
         "mission.json","mission_record.json","photos_metadata.json","metrics.json","summary.md"]
rows = []
for p in sorted(RUNS.glob("*/metrics.json")):
    rows.append(json.loads(p.read_text(encoding="utf-8")))
by = {}
for r in rows:
    by.setdefault(r["scenario_id"], []).append(r)
ok = True
order = ["P1","P2","P3","A1","A2","A3","A4","A5","A6","A7","A8","A9","A10"]
for sid in order:
    pool = [r for r in by.get(sid, []) if r.get("passed")] or by.get(sid, [])
    final = sorted(pool, key=lambda r: r["run_id"])[-1]
    d = RUNS / final["run_id"]
    missing = [f for f in FILES if not (d / f).is_file()]
    m = final
    exp = list((m.get("expected") or {}).get("expected_error_code") or [])
    codes = m.get("error_codes") or []
    codes_ok = all(c in codes for c in exp)
    ev_ok = True
    for name in ("llm_events.jsonl", "tool_calls.jsonl"):
        try:
            for line in (d / name).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
        except Exception:
            ev_ok = False
    a6 = ""
    if sid == "A6":
        txt = (d / "agent_audit.jsonl").read_text(encoding="utf-8", errors="replace")
        a6 = "force_rth=" + str("force_rth" in txt) + " final_idle=" + str((m.get("actual") or {}).get("final_state") == "idle")
    status = "OK" if (not missing and m.get("passed") and codes_ok and ev_ok) else "PROBLEM"
    if status != "OK":
        ok = False
    print("{} {:<22} {:<9} photos={:<3} codes={} exp={} final_state={} files_ok={} jsonl_ok={} {} {}".format(
        sid, final["run_id"], m.get("mode"), m.get("n_photos"), codes, exp,
        (m.get("actual") or {}).get("final_state"), not missing, ev_ok, a6, status))
print("ALL_OK", ok)