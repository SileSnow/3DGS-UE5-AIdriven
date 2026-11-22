"""只读自检：仓库状态、关键路径、数据目录、Python 依赖。

用法：
  python inspect_zeus.py --repo <repo>/yz-global-city-resilience-paper3
  python inspect_zeus.py --repo ... --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

KEY_PATHS = [
    ("L0–L5 契约", "_wiki-methodology/_wiki/_methods/zeus-multiscale-l0-l5-contract.md"),
    ("插件注册表", "_sandbox/2026-10-31-sim-service/zs/plugin_registry.py"),
    ("大屏入口", "_sandbox/2026-10-28-earth-dashboard/site/index.html"),
    ("城市渲染", "_sandbox/2026-10-28-earth-dashboard/site/js/city.js"),
    ("建筑解析", "_sandbox/2026-10-28-earth-dashboard/site/js/bld-worker.js"),
    ("城市数据生成", "_sandbox/2026-10-28-earth-dashboard/prep/build_city23.py"),
    ("仿真服务", "_sandbox/2026-10-31-sim-service/zs/api.py"),
    ("城市孪生", "_sandbox/2026-10-29-citytwin/settings.yaml"),
    ("数据目录方法", "_wiki-methodology/_wiki/_methods/zeus-data-catalog.md"),
]

GREP_PATTERNS = [
    "inferred_facades",
    "trained_radiance_field",
    "map3dview",
    "plugin_registry",
    "multiscale",
]


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    repo = args.repo.expanduser().resolve()
    result = {"repo": str(repo), "ok": False, "checks": {}}
    if not (repo / ".git").exists():
        print(f"[FAIL] 不是 git 仓库：{repo}", file=sys.stderr)
        return 2

    result["ok"] = True
    checks = result["checks"]

    def git(*a):
        return run(repo, "git", *a).stdout.strip()

    checks["branch"] = git("rev-parse", "--abbrev-ref", "HEAD")
    checks["head"] = git("log", "-1", "--format=%H %ci %s")
    checks["status"] = git("status", "-sb").splitlines()[0] if git("status", "-sb") else ""
    checks["remote"] = git("remote", "get-url", "origin")
    files = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    checks["file_count"] = len(files)

    checks["paths"] = {}
    for label, rel in KEY_PATHS:
        checks["paths"][label] = {"path": rel, "exists": rel in files}

    checks["missing_targets"] = {
        "contract": any("multiscale" in f for f in files),
        "plugin_registry": any(f.endswith("plugin_registry.py") for f in files),
        "four_slot_manifest": any(
            f.startswith(("plugins/connectors/", "plugins/solvers/", "plugins/layers/", "plugins/copilot/"))
            and f.endswith("manifest.json")
            for f in files
        ),
    }
    # 注意：partial clone（blob:none）下 git grep 会触发按 blob 的懒加载，可能长时间卡住；
    # 这里只做“文件名命中”，内容核对用编辑器/ripgrep 本地做。
    checks["name_hits"] = {
        pat: sum(1 for f in files if pat.lower() in f.lower()) for pat in GREP_PATTERNS
    }

    checks["data_dirs"] = {
        "site/data": (repo / "_sandbox/2026-10-28-earth-dashboard/site/data").exists(),
        "citytwin/data": (repo / "_sandbox/2026-10-29-citytwin/data").exists(),
    }
    checks["python"] = sys.version.split()[0]
    checks["numpy"] = np.__version__

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"repo    {repo}")
    print(f"branch  {checks['branch']}")
    print(f"head    {checks['head'][:80]}")
    print(f"status  {checks['status']}")
    print(f"files   {checks['file_count']}")
    print("")
    print("关键路径")
    for label, item in checks["paths"].items():
        print(f"  {'OK ' if item['exists'] else '-- '} {label:<14} {item['path']}")
    print("")
    print("邮件所指对象")
    for k, v in checks["missing_targets"].items():
        print(f"  {'FOUND' if v else 'MISS '} {k}")
    print("")
    print("文件名命中数（内容请用编辑器搜）")
    for k, v in checks["name_hits"].items():
        print(f"  {v:>4}  {k}")
    print("")
    print("数据目录")
    for k, v in checks["data_dirs"].items():
        print(f"  {'OK ' if v else '-- '} {k}")
    print("")
    print(f"python {checks['python']} / numpy {checks['numpy']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
