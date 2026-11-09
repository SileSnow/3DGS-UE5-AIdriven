"""错误码定义（严格逐字对齐 llm_drone/spec/PROTOCOL.md 第 8.2 节）。

所有错误码都是大写字符串常量，SafetyValidator / Drone Agent / 测试
统一从本模块引用，避免拼写漂移（Lead 会按错误码断言）。
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------- 参数/协议层
E_SCHEMA = "E_SCHEMA"                    # 参数不满足 JSON Schema
E_PARAM_RANGE = "E_PARAM_RANGE"          # 参数物理范围非法
E_UNKNOWN_TOOL = "E_UNKNOWN_TOOL"        # 不在白名单
E_CONFIRM_REQUIRED = "E_CONFIRM_REQUIRED"  # 飞行命令缺 confirm=true
E_MODE = "E_MODE"                        # 当前模式不允许该操作
E_STATE = "E_STATE"                      # 状态机不允许
E_BUSY = "E_BUSY"                        # 任务执行中的并发飞行命令

# ---------------------------------------------------------------- 飞行安全
E_ALT_LIMIT = "E_ALT_LIMIT"              # 超过最大相对高度
E_SPEED_LIMIT = "E_SPEED_LIMIT"          # 超过最大速度
E_GEOFENCE = "E_GEOFENCE"                # 超出地理围栏
E_NOFLY = "E_NOFLY"                      # 进入禁飞区
E_BATTERY_TAKEOFF = "E_BATTERY_TAKEOFF"  # 起飞电量不足
E_BATTERY_RTH = "E_BATTERY_RTH"          # 返航电量不足（任务前能量估算）
E_GPS = "E_GPS"                          # GPS 质量不足
E_RC_LINK = "E_RC_LINK"                  # 遥控链路断开

# ---------------------------------------------------------------- 资源/运行
E_MISSION_NOT_FOUND = "E_MISSION_NOT_FOUND"
E_REAL_NOT_AVAILABLE = "E_REAL_NOT_AVAILABLE"
E_NOT_SUPPORTED = "E_NOT_SUPPORTED"
E_NOT_AIRBORNE = "E_NOT_AIRBORNE"
E_INTERNAL = "E_INTERNAL"


#: 错误码 -> 中文含义（与 PROTOCOL.md 8.2 表格逐字一致，供文档/日志使用）
ERROR_MESSAGES = {
    E_SCHEMA: "参数不满足 JSON Schema（缺字段/类型错/多余字段）",
    E_PARAM_RANGE: "参数物理范围非法",
    E_UNKNOWN_TOOL: "不在指令白名单",
    E_CONFIRM_REQUIRED: "飞行命令缺 confirm=true",
    E_MODE: "当前模式不允许该操作",
    E_STATE: "状态机不允许",
    E_BUSY: "任务执行中收到并发的飞行命令",
    E_ALT_LIMIT: "超过最大相对高度",
    E_SPEED_LIMIT: "超过最大速度",
    E_GEOFENCE: "超出地理围栏",
    E_NOFLY: "进入禁飞区",
    E_BATTERY_TAKEOFF: "起飞电量不足",
    E_BATTERY_RTH: "返航电量不足（任务前能量估算）",
    E_GPS: "GPS 质量不足",
    E_RC_LINK: "遥控链路断开",
    E_MISSION_NOT_FOUND: "mission_id 不存在",
    E_REAL_NOT_AVAILABLE: "Phase1 无真机后端",
    E_NOT_SUPPORTED: "仿真专属端点被 real 后端调用",
    E_NOT_AIRBORNE: "需要空中状态的动作（拍照/云台）而当前在地面",
    E_INTERNAL: "未预期内部错误（审计堆栈）",
}

#: 允许出现在 telemetry.state 的状态（PROTOCOL.md 5）
FLIGHT_STATES = (
    "idle",
    "taking_off",
    "hovering",
    "mission",
    "returning",
    "landing",
    "aborted",
    "failsafe",
)

#: 允许出现在 telemetry.mode 的模式（PROTOCOL.md 5）
MODES = ("dry_run", "sim", "real")

#: 飞行中（离地）状态集合；idle 表示停机坪/地面
AIRBORNE_STATES = frozenset(
    {"taking_off", "hovering", "mission", "returning", "landing", "aborted", "failsafe"}
)


def message_for(code: str) -> str:
    """错误码的默认中文含义。"""
    return ERROR_MESSAGES.get(code, str(code))


def make_error(code: str, message: Optional[str] = None, details: Any = None) -> dict:
    """构造协议错误对象 {"code","message","details"}。"""
    err = {"code": code, "message": message or message_for(code)}
    if details is not None:
        err["details"] = details
    return err
