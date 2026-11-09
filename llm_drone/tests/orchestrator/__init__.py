"""tests/orchestrator 包（unittest discover 以 tests 为顶层目录，故本目录会被命名为 `orchestrator`）。

为了不遮蔽真实实现包 llm_drone/orchestrator，这里把真实目录追加进 __path__：
  - `from orchestrator import planner/llm_client/run_demo/...` -> 命中真实实现
  - `orchestrator.test_planner` 等测试模块 -> 命中本目录
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LLM_DRONE = os.path.dirname(os.path.dirname(_HERE))
_REAL_ORCH = os.path.join(_LLM_DRONE, "orchestrator")
if _REAL_ORCH not in __path__:
    __path__ = list(__path__) + [_REAL_ORCH]
