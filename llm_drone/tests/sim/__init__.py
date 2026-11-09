"""tests/sim 包（unittest discover 以 tests 为顶层目录，故本目录会被命名为 `sim`）。

为了不遮蔽真实实现包 llm_drone/sim，这里把真实目录追加进 __path__：
  - `import sim.server` / `from sim.simulator import ...`  -> 命中真实实现
  - `sim.test_protocol` 等测试模块 -> 命中本目录
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LLM_DRONE = os.path.dirname(os.path.dirname(_HERE))
_REAL_SIM = os.path.join(_LLM_DRONE, "sim")
if _REAL_SIM not in __path__:
    __path__ = list(__path__) + [_REAL_SIM]
