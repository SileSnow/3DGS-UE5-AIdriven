# drone-sim 工作总结（task-4：Phase-1 仿真 Drone Agent + SafetyValidator + 对抗测试）

> 状态：**完成（2026-11-08 22:0x）**。规格唯一事实源：`llm_drone/spec/PROTOCOL.md` v1.0（FROZEN）。
> 交付：`llm_drone/sim/`（HTTP 仿真 Agent）、`llm_drone/safety/`（确定性安全层）、
> `llm_drone/tests/sim|safety/`（unittest）、`llm_drone/logs/drone-sim/`（证据）。

## 1. 交付物与验收结果

| 交付物 | 状态 | 证据 |
|---|---|---|
| `sim/`：`python -m sim.server --port 8765 --time-scale 20` HTTP 仿真 Agent（§3/§4/§5/§6/§7/§9.1/§10） | ✅ | `sim/README.md`；Lead 独立黑盒验收 27/27 PASS：`llm_drone/logs/lead/acceptance_20261108_215559.{json,md}` |
| `safety/`：SafetyValidator（确定性纯函数）+ 默认 config（§8/§8.1 逐字）+ 错误码 + 几何 | ✅ | `safety/README.md`；`safety/config.json` |
| `tests/sim/` 协议/任务/审计测试 | ✅ 21 tests OK | `logs/drone-sim/selftest_20261108_220127.log` |
| `tests/safety/` A1-A10 + 几何 + c2w + 集成测试 | ✅ 45 tests OK | 同上 |
| 真实 server 冒烟（health→reset→takeoff→goto(sample_mission 16 点)→completed 16 photos→rth→land） | ✅ PASS | `logs/drone-sim/SMOKE.md`、`smoke_20261108_220257.log`、`audit_smoke_20261108_220257.jsonl` |
| 审计 JSONL 逐行 `json.loads`；c2w `|R R^T-I|<1e-6` | ✅ 16/16 张 | `SMOKE.md` §3/§4 |
| README（sim/safety） | ✅ | `llm_drone/sim/README.md`、`llm_drone/safety/README.md` |

## 2. 测试结果（可复现命令）

```powershell
cd C:\Users\<user>\Desktop\GAIA项目\dji_ue5_3dgs\llm_drone
python -m unittest discover -s tests/sim -t tests -v      # Ran 21 tests ... OK
python -m unittest discover -s tests/safety -t tests -v   # Ran 45 tests ... OK
python -m unittest discover -s tests -v                   # Ran 118 tests ... OK（全仓，含其他 agent 测试，2026-11-08 22:01）
python logs\drone-sim\smoke_run.py                        # 退出码 0（真实 server 冒烟）
```

- drone-sim scope 测试共 **66 个**（21 sim + 45 safety），连续 3 轮压力复跑 0 失败
  （见 `selftest_20261108_220127.log` 的 stress #1-#3）。
- 测试全部使用**临时审计目录 + 随机端口（port=0）**，不污染 `logs/drone-sim/audit_*.jsonl`。
- `tests/` 根目录还有早期 `test_geo.py`（10 tests，geo 兼容性），亦通过。

### 用例清单

`tests/sim/`（21）
- `test_protocol.py`（10）：health、telemetry §5 字段、command_id 幂等、未知工具、reset 恢复默认+切审计文件、sim/config 注入与非法参数、missions 空列表/E_MISSION_NOT_FOUND、audit 端点 since_seq/last_seq。
- `test_mission.py`（6）：takeoff→goto(sample_mission 16 点)→16 photos→completed→rth→land 全链路（含照片字段/c2w 正交/平移 cm 校验）、abort、地面动作 E_NOT_AIRBORNE、空中低风险动作（云台/拍照/录像）、E_STATE、mission status/list。
- `test_audit.py`（4）：JSONL 字段完整+seq 严格递增、拒绝事件 error_code/reasons、force_rth（decision=force_rth）+最终 idle、mission_started/photo_captured×16/mission_completed 事件。
- `test_shim_probe.py`（1）：discover 包名 shim 自检。

`tests/safety/`（45）
- `test_rules.py`（22）：§8/§8.1 默认值逐项、错误码拼写、白名单⊆tools.json、A1-A10 逐条（A6 规则层面 + 能量估算拒绝）、E_STATE/E_BUSY/E_NOT_AIRBORNE、校验顺序（battery>alt、confirm>battery、state>geofence、geofence>nfz）、preflight、§6 Mission 归一化。
- `test_integration.py`（13）：真实 HTTP 下 A1/A2/A3/A4/A5/A6/A7/A8/A9/A10 + E_BUSY + E_NOT_AIRBORNE + E_STATE。
- `test_c2w.py`（6）：§7.2 公式逐元素、平移=UE cm、正交性、§7.3 metadata 导出。
- 另有根 `tests/test_geo.py`（10）：坐标换算与 capture 工程一致性。

## 3. 冒烟结果（真实 server，独立 urllib 客户端）

`python -m sim.server --port 60035 --time-scale 20 --audit-dir ...\logs\drone-sim`：

- health：`ok=true, backend=sim, version=1.0.0, mode=sim, time_scale=20.0`
- reset(run_id=smoke_20261108_220257) → idle / battery 100
- preflight_check → `can_fly=true`
- takeoff(40, confirm) → hovering，alt_rel_m=40.0，battery=97.9
- goto_waypoints(spec/sample_mission.json 16 点) → mission_id=`sample-grid-16`
- mission record：**state=completed, progress_pct=100.0, n_photos=16**，stats=`{distance_m:319.239, duration_s:164.0, n_photos:16}`
- 照片：file `SIM_0001.jpg … SIM_0016.jpg`；c2w **16/16 满足 |R R^T-I|<1e-6 且 det=+1**；第 0 张 c2w 平移 (-2800, +2800, 4000) cm 与 §7.2 公式一致
- return_to_home → returning → idle（lat=39.9042, lon=116.4074, alt_rel=0）
- 地面 land → `E_STATE`（预期）
- 审计：`audit_smoke_20261108_220257.jsonl` **58 行逐行 json.loads 通过**，seq 1→58 严格递增，每行含 ts/seq/run_id/event；
  event 含 command_received/safety_check/command_accepted/command_rejected/photo_captured×16/mission_completed/rth_started/landed/telemetry_keyframe

## 4. 关键设计决策（已与 Lead / llm-orchestrator 对齐）

1. **校验顺序严格 §4**：schema→whitelist→mode→confirm→state→battery→gps→rc→range→geofence→no-fly→RTH 能量→allow。
   因此 A2/A3 场景必须“先 takeoff 再 goto”（地面 goto = `E_STATE`）；A5 confirm 在 state 之前，任意状态 `E_CONFIRM_REQUIRED`。
2. 未知工具白名单先于 schema（schema 依赖工具定义），返回 `E_UNKNOWN_TOOL`（满足 §8 规则 10 / A9）。
3. `E_BUSY` 在 state 阶段最前；任务中仅允许 abort/get_telemetry/get_mission_status/return_to_home。
4. `goto_waypoints.args.mission` 严格 §6（action∈photo/video_start/video_stop/none；不认旧 CONTRACT 的 take_photo/嵌套 gimbal）；
   mission_id 缺省时 Agent 分配 `m-%04d`。
5. 飞行中低电量（<20%）→ 强制 RTH：审计 `{"event":"force_rth","decision":"force_rth","reason":"battery ... < 20.00%",...}`，
   任务标记 aborted/error.code=`FORCE_RTH`，最终 landed/idle。
6. 照片 c2w 按 §7.2（yaw_ue=heading−90，行主序，列 forward/right/up，平移 UE cm，原点=mission origin_wgs84）。
7. 审计写入 run_id 专属文件；`/v1/reset {run_id}` 切换文件并清空任务/幂等缓存。
8. 早期（断电前）CONTRACT 版 sim/safety 代码已被冻结规格版**整体替换**；旧 `tests/helpers.py`、`tests/test_geo.py`
   通过 safety 的兼容别名（Fence/NFZ/load_safety_config/nominal_state 等）保持可用，未改动其文件。
9. unittest discover 的包名冲突：`tests/sim/__init__.py`、`tests/safety/__init__.py` 用
   `__path__` 追加真实实现目录，使 `import sim.server`/`import safety.validator` 命中实现包（已在 README 注明）。

## 5. 证据文件

| 文件 | 内容 |
|---|---|
| `logs/drone-sim/SMOKE.md` | 真实 server 冒烟步骤/关键输出/审计摘录/c2w 说明 |
| `logs/drone-sim/smoke_20261108_220257.log` | 冒烟完整 stdout（含 mission record JSON） |
| `logs/drone-sim/audit_smoke_20261108_220257.jsonl` | 本次冒烟真实审计（58 行） |
| `logs/drone-sim/selftest_20261108_220127.log` | 3 轮压力复跑 + 最终 scoped/full 单测完整输出 |
| `sim/README.md`、`safety/README.md` | 设计/端点/命令表/API 示例/复现命令/边界 |
| `llm_drone/logs/lead/acceptance_20261108_215559.{json,md}` | Lead 独立黑盒验收 27/27 PASS（非本 scope 产出） |

## 6. 已知边界 / 遗留说明

- Phase1 只有仿真后端（`set_mode(real)` → `E_REAL_NOT_AVAILABLE`）；照片只有记录（`SIM_%04d.jpg` 占位），
  真实 PNG 由 `llm_drone/ue5_mission/` 渲染。
- `/v1/reset`、`/v1/sim/config` 为仿真专属；Phase2 真机桥应返回 `E_NOT_SUPPORTED`。
- mission record 的 `error.code` 对中止类使用非协议码 `ABORTED/RETURN_TO_HOME/FORCE_RTH`（协议错误码表仅用于命令响应）。
- Lead 验收后对 server 做过一处**纯增量**改动：`_ok_response` 合并命令附加字段（abort 的 `mission_state` 等），
  未改变任何校验/执行/错误码行为；单测与冒烟均已在新代码上复跑通过。
- 本轮 smoke 在 Lead 验收之后复跑，结论一致。
