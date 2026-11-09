"""tests/safety 包（unittest discover 以 tests 为顶层目录，故本目录会被命名为 `safety`）。

把真实实现目录 llm_drone/safety 追加进 __path__，并把公开 API 重新导出，
避免遮蔽真实包（import safety.validator -> llm_drone/safety/validator.py）。
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LLM_DRONE = os.path.dirname(os.path.dirname(_HERE))
_REAL_SAFETY = os.path.join(_LLM_DRONE, "safety")
if _REAL_SAFETY not in __path__:
    __path__ = list(__path__) + [_REAL_SAFETY]

# 重新导出真实 safety 包公开 API（测试模块也统一用 from safety.xxx import ...）
from . import errors, geo, schemas  # noqa: E402,F401
from .audit import AuditLogger, AuditManager, NullAuditLogger, now_iso  # noqa: E402,F401
from .config import (  # noqa: E402,F401
    DEFAULT_NO_FLY_POLYGON,
    DEFAULT_NO_FLY_ZONES,
    Fence,
    NFZ,
    SafetyConfig,
    default_config,
    load_config,
    load_safety_config,
)
from .validator import (  # noqa: E402,F401
    BUSY_ALLOWED_TOOLS,
    SafetyDecision,
    SafetyValidator,
    estimate_mission_energy_pct,
    nominal_state,
    preflight_checks,
    validate_command,
)
