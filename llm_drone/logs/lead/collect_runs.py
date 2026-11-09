#!/usr/bin/env python
"""扫描 llm_drone/demo/runs/* 的 metrics.json，输出 markdown 汇总表（供报告/验收引用）。"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LLM_DRONE = os.path.abspath(os.path.join(HERE, "..", ".."))
RUNS = os.path.join(LLM_DRONE, "demo", "runs")


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"_error": str(e)}


def main():
    dirs = sorted(glob.glob(os.path.join(RUNS, "*")))
    rows = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        runs = [p for p in [os.path.join(d, "metrics.json"), os.path.join(d, "run_metrics.json")]
                if os.path.isfile(p)]
        if not runs:
            continue
        m = load(runs[0])
        if "_error" in m:
            print("BAD", d, m["_error"])
            continue
        rows.append({
            "run_id": m.get("run_id") or os.path.basename(d),
            "scenario": m.get("scenario_id") or m.get("scenario") or "",
            "kind": m.get("kind") or m.get("scenario_kind") or "",
            "passed": m.get("passed"),
            "llm": m.get("llm") or m.get("model") or "",
            "llm_calls": m.get("llm_calls"),
            "tool_calls": m.get("tool_calls"),
            "rejected": m.get("rejected"),
            "error_codes": ",".join(m.get("error_codes") or m.get("reject_codes") or []) if isinstance(m.get("error_codes") or m.get("reject_codes") or [], list) else m.get("error_codes"),
            "photos": m.get("n_photos") or m.get("photos"),
            "wall_s": m.get("wall_s") or m.get("duration_s"),
            "path": os.path.relpath(d, os.path.dirname(LLM_DRONE)),
        })
    print("| run_id | scenario | kind | passed | llm | llm_calls | tool_calls | rejected | error_codes | photos | wall_s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print("| {run_id} | {scenario} | {kind} | {passed} | {llm} | {llm_calls} | {tool_calls} | {rejected} | {error_codes} | {photos} | {wall_s} |".format(**r))
    print()
    print("total runs:", len(rows), "| passed:", sum(1 for r in rows if r["passed"]), "| failed:", sum(1 for r in rows if not r["passed"]))
    # 汇总 json
    out = os.path.join(HERE, "runs_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"runs": rows}, f, ensure_ascii=False, indent=2)
    print("summary ->", out)


if __name__ == "__main__":
    sys.exit(main())
