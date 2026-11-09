# mission JSON 契约（ue5-mission 解析器 v1）

> 用途：LLM 编排层（orchestrator）或仿真后端（drone-sim）产出的 mission JSON，
> 经 `llm_drone/ue5_mission/legacy/mission_to_poses.py`（历史原型；现行实现为 `mission_io.py`）转成 UE5 虚拟相机位姿，
> 再由 `render_mission.py`（UE 编辑器内）逐航点渲染 1600×1200 PNG + metadata。
> 解析器对字段别名刻意宽容；**最小必需字段只有 waypoint 的 `lat` / `lon`**，其余都有默认值。

## 1. 推荐格式（与 docs/CONTRACT.md 的工具参数一致）

~~~json
{
  "mission_id": "m-001",
  "pattern": "grid",
  "origin_wgs84": {"lat": 39.9042, "lon": 116.4074, "alt": 43.0},
  "photo_interval_s": 2.0,
  "defaults": {"alt_rel_m": 40.0, "gimbal_pitch": -45.0, "yaw": 90.0},
  "waypoints": [
    {"lat": 39.9042, "lon": 116.4074, "alt_rel_m": 40.0,
     "speed_mps": 6.0,
     "gimbal": {"pitch": -45.0, "yaw": 90.0, "roll": 0.0},
     "take_photo": true},
    {"lat": 39.9002, "lon": 116.4108, "alt_rel_m": 40.0,
     "gimbal": {"pitch": -48.0, "yaw": 120.0}}
  ]
}
~~~

| 字段 | 必需 | 说明 |
|---|---|---|
| `mission_id` | 否 | 写入 metadata；缺省 "mission"。别名 `id` / `name` |
| `pattern` | 否 | grid / orbit / point …，仅记录到 metadata |
| `origin_wgs84` | 否 | 局部原点，默认 39.9042 / 116.4074 / 43 m（与 capture 流水线一致，**不建议改**）|
| `photo_interval_s` | 否 | 无 timestamp 时按 序号×间隔 生成，默认 2 s |
| `defaults` | 否 | 航点级缺省（alt_rel_m / gimbal_pitch / yaw / gimbal 对象）|
| `waypoints[]` | **是** | 也接受 `photo_points` / `points` / `photos` / `shots` / `capture_points`；也接受根级数组、或 `{"args": {...}}` / `{"mission": {...}}` 包装 |
| `waypoints[].lat` / `lon` | **是** | 别名 `latitude` / `lng` / `longitude`；也可给 `ue_loc_cm: [x,y,z]` 直接指定 UE 坐标（调试用）|
| 高度 | 否 | `alt_rel_m`（默认，相对起飞点 43 m）/ `alt_abs_m`（绝对 WGS84）；泛用 `alt` / `altitude_m` 按**相对高度**解释 |
| `gimbal` | 否 | `{pitch,yaw,roll}`；DJI 习惯：yaw 北=0 顺时针，pitch 下为负。也可平铺为 `gimbal_pitch` / `gimbal_yaw` / `pitch` / `yaw` / `heading` |
| `take_photo` | 否 | 默认 true；false 表示过渡航点（不渲染，计入 stats.skipped）|
| `timestamp` | 否 | 秒；也接受 `t_rel_s` / `time_s` |

> 若 waypoint 未给云台 yaw：优先取前后航点连线方向（flight direction），单点任务取北（0°）。

## 2. 坐标/姿态换算（与 capture/scripts/synth_common.py 完全一致）

| 量 | 换算 |
|---|---|
| UE 原点 | WGS84 39.9042 / 116.4074 / 43.0 m |
| 水平 | `x_cm = (lon-lon0)·111320·cos(lat0)·100`（东为正）；`y_cm = -(lat-lat0)·111320·100`（南为正）|
| 高度 | `z_cm = (alt_abs_m - 43)·100`；`alt_abs_m = 43 + alt_rel_m` |
| 云台 yaw | `ue_yaw = dji_yaw - 90`（UE yaw 0 = +X = 东；北 = -90）|
| 云台 pitch/roll | 直接映射（下为负）|
| c2w | 4×4 行主序，列 = forward/right/up（UE 相机轴），平移 cm |

示例：DJI yaw=90（朝东）⇒ UE yaw=0；lat/lon 每 0.001° ≈ 111 m。

## 3. 生成/自检命令（宿主侧，无需 UE）

~~~powershell
cd C:\UEW\dji_ue5_3dgs

# mission -> poses 预览（检查 UE 坐标/姿态/GPS 是否合理）
python ./llm_drone/ue5_mission/legacy/mission_to_poses.py --mission ./llm_drone/ue5_mission/missions/mission_grid_12.json --out ./llm_drone/ue5_mission/missions/poses_preview.json --summary  # 仅旧原型
python ./llm_drone/ue5_mission/mission_io.py --mission ./llm_drone/ue5_mission/missions/mission_grid_12.json --out ./llm_drone/ue5_mission/missions/poses_preview.json --summary

# 生成示例任务（4 线 × 3 点 = 12 张；6 × 6 = 36 张）
python ./llm_drone/ue5_mission/legacy/mission_to_poses.py --make-grid --out ./llm_drone/ue5_mission/missions/mission_grid_12.json --mission-id mission_grid_12 --lines 4 --shots 3 --area-half-m 40 --alt-m 40 --pitch -45 --yaw 90  # 仅旧原型
python ./llm_drone/ue5_mission/legacy/mission_to_poses.py --make-grid --out ./llm_drone/ue5_mission/missions/mission_grid_36.json --mission-id mission_grid_36 --lines 6 --shots 6 --area-half-m 40 --alt-m 40 --pitch -45 --yaw 90  # 仅旧原型
~~~

## 4. 渲染（UE 内，启动前须向 lead 报备 + 4 核限载）

~~~powershell
powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission ./llm_drone/ue5_mission/missions/mission_grid_12.json
~~~

输出 `data/synthetic/mission/images/0001.png...` + `metadata.json` + `poses_mission.json`；
可选 `-ValFrames N` 额外渲染留出验证视角到 `data/synthetic/mission/val/`。
