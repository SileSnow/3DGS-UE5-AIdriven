# LLM Tool-Call 调度无人机（Phase-1 验证工程）

> 目标：验证 **「自然语言 → LLM 工具调用 → 确定性安全校验 → 无人机任务执行 → 航拍数据 → 3DGS/UE5」** 的完整可行性。
> Phase-1 全部在 **仿真 + UE5 虚拟相机** 中完成（无真机飞行）；Phase-2 为 Android MSDK v5 真机桥（设计+代码骨架+真机测试协议，本轮未执行）。

## 当前状态（2026-11-08）

| 模块 | 状态 | 证据 |
|---|---|---|
| 冻结规格（HTTP/工具/mission/安全/审计） | ✅ | `spec/PROTOCOL.md` v1.1、`spec/tools.json`、`spec/sample_mission.json` |
| LLM Orchestrator（真实本地 LLM 工具循环） | ✅ | `orchestrator/`；**13/13 场景 PASS**：P1-P3 真实 LLM（20/12/5 张照片）、A1-A5 真实 LLM 触发拒绝、A6-A10 scripted 直调；`demo/runs/` |
| 仿真 Drone Agent + SafetyValidator | ✅ | `sim/`、`safety/`；Lead 独立黑盒验收 27/27（`logs/lead/acceptance_*.json`） |
| 对抗安全（超限高/围栏/禁飞区/低电量/无确认/GPS/链路/参数/real 模式） | ✅ | `tests/safety/` + 验收 JSON + 演示 run |
| UE5 虚拟相机执行 Mission → PNG + metadata | ✅ | `data/synthetic/mission/`（16 帧 1600×1200 + metadata.json）；`ue5_mission/` |
| 与 3DGS 流水线兼容 | ✅ | `pipeline/.venv` 的 `dataset.load_dataset()` 成功加载 16 views（见报告 §7） |
| MSDK v5 桥（设计/Kotlin 骨架/映射/真机协议） | 🟡 设计完成，**未编译、未真机** | `msdk_bridge/`（README/DESIGN/app/mapping/PROTOCOL_COMPLIANCE/test_protocol） |
| 真机飞行 | ⏳ Phase-2 | — |

## 架构（三段式）

```
用户自然语言
  → ① LLM Orchestrator（工具循环 / 规划 / 确认门禁 / 审计）
  → ② Drone Agent（确定性 SafetyValidator + 执行 + 遥测；Phase-1 仿真 / Phase-2 MSDK v5 桥）
  → ③ 无人机（Phase-1 运动学仿真 / Phase-2 DJI Mini 4 Pro）
```

**LLM 永远不直连 DJI SDK**：LLM 只生成工具调用意图与参数，所有飞行指令必须经过确定性安全层。

## 快速开始

```powershell
cd dji_ue5_3dgs\llm_drone

# 0) 依赖：Python 3.14+（纯标准库）；（可选）Ollama qwen3.5:4b 用于真实 LLM 演示

# 1) 启动仿真无人机（127.0.0.1:8765，20 倍时间加速）
python -m sim.server --port 8765 --time-scale 20

# 2) 跑演示场景（真实 LLM；P1-P3 正向 + A1-A10 对抗）
python -m orchestrator.run_demo --agent-url http://127.0.0.1:8765 --scenario all --out demo/runs

# 3) 单元测试（sim/safety/orchestrator）
python -m unittest discover -s tests -v

# 4) Lead 独立黑盒验收（自动起 server，不 import 被测代码）
python logs\lead\verify_acceptance.py --port 8766

# 5) UE5 渲染 Mission JSON → PNG + metadata（ASCII junction C:\UEW；独占 GPU）
powershell -ExecutionPolicy Bypass -File ue5_mission\run_mission.ps1 -Mission spec\sample_mission.json -Out ..\data\synthetic\mission
python ue5_mission\validate_output.py --out ..\data\synthetic\mission
```

无真实 LLM 时可用 `--scripted`（预置工具序列）做确定性演示；但**正向能力证据以真实 LLM run 为准**。

## 目录

| 目录 | 内容 |
|---|---|
| `spec/` | **冻结规格（唯一事实源）**：PROTOCOL（HTTP/mission/审计/安全/错误码）、tools.json（15 工具）、sample_mission.json |
| `docs/` | 任务契约 `CONTRACT.md`、最终报告 `LLM调度无人机方案与验证报告.md`、断点现场 |
| `orchestrator/` | LLM 工具循环（Ollama native tools / OpenAI 兼容）、规划器（grid/orbit/point）、工具运行时、审计、`run_demo.py` |
| `sim/` | 仿真 Drone Agent：HTTP server、状态机、运动学、电量、任务执行、照片/遥测记录 |
| `safety/` | SafetyValidator（纯函数）、错误码、坐标/几何、Schema、JSONL 审计 |
| `tests/` | `sim/`、`safety/`、`orchestrator/` 单测；Lead 验收脚本在 `logs/lead/` |
| `demo/` | 场景定义与 `runs/<run_id>/` 证据（transcript/审计/mission/photos/metrics） |
| `ue5_mission/` | Mission JSON → UE5 虚拟相机渲染 + 真值 metadata + 独立校验 |
| `msdk_bridge/` | Phase-2 Android MSDK v5 桥：设计、Kotlin 骨架、工具→API 映射、真机测试协议 |
| `logs/` | 各 agent 运行日志、审计、验收结果 |

## 关键设计

- **15 个工具、三级风险**：只读（遥测/预检/规划）、低风险（云台/拍照/录像）、飞行（起降/航点/环绕/返航）；飞行工具强制 `confirm=true`。
- **规划与执行两步**：`plan_capture_mission` 只出计划（plan_id），`goto_waypoints` 才执行 —— 与无人机"先航线上传、后执行"的工程习惯一致，也避免小模型传输大数组。
- **确定性安全层**：限高 120 m、限速 15 m/s、圆形围栏 300 m、禁飞多边形、起飞电量 ≥30%、返航保留 20%、GPS fix≥3/卫星≥10、链路、白名单、Schema、confirm、审计；错误码结构化回灌给 LLM 自我纠正。
- **同一契约双后端**：仿真与 Android MSDK v5 桥实现同一套 HTTP JSON API，Orchestrator 零改动切换。
- **闭环到 3DGS**：任务照片/UE5 渲染结果直接落成上游 `shared/CONVENTIONS.md` 的 metadata.json，可接 `pipeline/` 训练。

## 安全与合规

- 不修改固件、不绕过地理围栏/限高/限速；不使用逆向工具控制飞机。
- 真机测试须合法空域、限高 120 m 内、目视范围、提前报备；详见 `msdk_bridge/test_protocol.md`。
- 所有命令与拒绝均写审计 JSONL，不可关闭。

## 相关文档

- 最终报告：`docs/LLM调度无人机方案与验证报告.md`
- 任务契约：`docs/CONTRACT.md`；冻结规格：`spec/PROTOCOL.md`
- DJI Mini SDK 使用方法（代码级）：`../docs/research/08_MSDKv5_Android使用方法.md`、`09_MSDKv4_使用方法与Mini2链路.md`、`10_KMZ_WPML航线格式与任务下发.md`
- 上游 3DGS/UE5：`../pipeline/`、`../capture/`、`../shared/CONVENTIONS.md`
