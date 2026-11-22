# UE5 东京坐标 + 预定航线模拟飞行 — 执行报告（失败）

- 执行时间：2026-11-22 15:23–15:24 +08:00
- 工作区：`<workspace>`
- 主仓库：`dji_ue5_3dgs`（通过 ASCII junction `C:\UEW`）
- 结论：**未完成渲染（0 帧）**。UE 启动前被 CPU 温度保护拒绝（87.9 °C ≥ 80 °C）；
  且即使绕过温度保护，`render_mission.py` 也会因东京 origin 与固定园区 origin 不一致而硬失败。
- 未修改仓库源码，未 git commit，未删除/覆盖任何既有 evidence/data 目录。

## 1. 命令与 exit code

| # | 命令 | exit code | 结果 |
|---|---|---|---|
| 1 | `python -m json.tool "_tmp/tokyo_mission.json"` | 0 | JSON 合法 |
| 2 | `python dji_ue5_3dgs\llm_drone\ue5_mission\mission_io.py --mission "_tmp/tokyo_mission.json" --out _tmp/tokyo_plan` | 0 | 解析成功，16 帧，写出 mission_plan.json |
| 3 | `Get-Process -Name UnrealEditor` | 0 | 0 个实例；C:\UEW / UE_5.8 / UnrealEditor.exe 均存在 |
| 4 | `powershell -ExecutionPolicy Bypass -File .\llm_drone\ue5_mission\run_mission.ps1 -Mission C:\UEW\_tmp\tokyo_mission.json -Out data/synthetic/mission_tokyo_demo` | **1** | 温度预检拒绝，未启动 UE |
| 5 | `python .\llm_drone\ue5_mission\validate_output.py --out data/synthetic/mission_tokyo_demo` | **未执行** | 无输出帧；且该命令默认写 `llm_drone/ue5_mission/results/validation.json`，会覆盖既有证据，故未运行 |

## 2. 失败原文（step 4，stderr）

```text
CPU temperature 87.9 C >= 80 C, refusing to start UE (-Force overrides)
At C:\UEW\dji_ue5_3dgs\llm_drone\ue5_mission\run_mission.ps1:143 char:52
+ ... l -ge 80) { throw "CPU temperature $thermal C >= 80 C, refusing to st ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (CPU temperature...orce overrides):String) [], RuntimeException
    + FullyQualifiedErrorId : CPU temperature 87.9 C >= 80 C, refusing to start UE (-Force overrides)
```

- 渲染尝试耗时：**3.1 s**（全部耗在预检，UE 进程 0 个，未进入场景/渲染）
- 帧数：**0**
- 输出目录：`<workspace>\dji_ue5_3dgs\data\synthetic\mission_tokyo_demo`
  （相对：`data/synthetic/mission_tokyo_demo`；脚本预检前创建，当前为空）
- 本次运行日志：**未生成**（`run_mission.ps1` 在温度检查通过后才创建 `log/run_<ts>.json`；
  失败发生在赋值之前）
- 目录下最新日志仍是旧文件：`llm_drone/logs/ue5-mission/ue_mission_20261112_100501.log`（2026-11-12，与本次无关）

## 3. 第二个硬阻塞：东京 origin 与固定场景 origin 冲突（静态代码证据）

`render_mission.py` 在渲染前强制校验 mission 的 `origin_wgs84`：

- `llm_drone/ue5_mission/render_mission.py:50` `ORIGIN_ANGLE_TOL = 1e-7`
- `llm_drone/ue5_mission/render_mission.py:114-121` 逐项比较 `origin.lat/lon/alt` 与
  `C.ORIGIN_WGS84`（园区固定 origin = 39.9042 / 116.4074 / 43）
- `llm_drone/ue5_mission/render_mission.py:122-125` 不一致时抛出
  `RuntimeError("mission does not match the capture rig / campus scene origin: ...")`

东京 origin（35.665 / 139.7525 / 43）与园区 origin 的经纬度差远大于 1e-7，因此
**即使温度降到 80 °C 以下重跑（或加 -Force），渲染仍会在建场景前被拒绝**。
本报告未使用 `-Force`：它绕过的是温度安全保护，且任务未授权；也未修改源码去放宽该校验。

## 4. 东京坐标与航线证据（离线干跑，可信）

- mission：`_tmp/tokyo_mission.json`
- 干跑计划：`_tmp/tokyo_plan/mission_plan.json`
- origin_wgs84：`{"lat": 35.665, "lon": 139.7525, "alt": 43.0}`
- 航线：4×4 = 16 个 photo 航点；东西/南北间距各 **20 m**（按
  `dlat = m/110574`、`dlon = m/(cos(35.665°)*111320)` 计算，kx/ky 口径）
- 航点经纬度包围盒：
  - lat_min = `35.664728688`，lat_max = `35.665271312`（跨度 60.000 m @110574）
  - lon_min = `139.752168291`，lon_max = `139.752831709`（跨度 60.000 m @cos(35.665°)*111320）
- 首帧 GPS：`35.664728688, 139.752168291, 83.00`
- 末帧 GPS：`35.664728688, 139.752831709, 83.00`
- 渲染计划帧数：**16**；时间戳 0.000–67.824 s
- UE 坐标包围盒（mission_io 用 111320 反算）：`[-3000.003, -3020.245, 4000.0] .. [3000.003, 3020.245, 4000.0]` cm
  （注：因 mission_io 南北用 111320、本任务按 110574 布点，20 m 网格在 UE 侧显示为约 20.1348 m）
- GPS 往返误差（waypoint lat/lon → UE → gps）：max |Δlat| = 0°，max |Δlon| = 0°，
  折算 **0.000000000 m**（16/16 帧）

## 5. validation.json / contact sheet

- validation.json：**未生成**（无 images/metadata，且为避免覆盖
  `llm_drone/ue5_mission/results/validation.json` 未执行默认命令）
- ok：N/A；PASS/FAIL/SKIP/WARN：N/A；帧数：0；分辨率：N/A；c2w 误差：N/A
- contact sheet：**未生成**
- 如需在隔离目录补做失败校验（不触碰既有 evidence）：
  `python .\llm_drone\ue5_mission\validate_output.py --out data/synthetic/mission_tokyo_demo --mission _tmp/tokyo_mission.json --results _tmp/tokyo_validation --tag tokyo_demo`

## 6. 判断与建议

1. 直接原因：CPU 热区 87.9 °C（随后复测 81.9 °C，GPU 45.8 °C）触发
   `run_mission.ps1:143` 的 80 °C 预检；机器处于高负载/高温，不适合启动 UE。
2. 根本阻塞：UE 场景是固定北京园区（origin 39.9042/116.4074/43），渲染器设计上拒绝任何
   其他 origin 的 mission（README §9 与 render_mission.py 均明确）。因此“东京坐标 + 预定航线”
   在当前链路上**不可渲染**，不是本次操作失误。
3. 下一步（需人类/lead 决策，二选一）：
   - A. 若只要“预定航线模拟飞行”证据：用园区 origin 重算同一 4×4/20 m 航线，跑通渲染与 validation；
   - B. 若必须东京坐标：需要场景替换/让 renderer 支持场景原点参数（属于改源码/改冻结行为，
     有 GPS 真值失效风险，需先拍板）。
4. 在温度降到 80 °C 以下且无其他 UE 实例前，不要重跑正式渲染；不要用 `-Force` 绕过安全保护。

