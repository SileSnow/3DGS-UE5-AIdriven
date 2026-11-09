"""llm_drone.sim —— Phase-1 无人机仿真后端（纯标准库）。

启动：
    cd dji_ue5_3dgs/llm_drone && python -m sim.server --port 8765 --time-scale 20

模块：
    sim.config.SimConfig           仿真参数（PROTOCOL.md §10）
    sim.simulator.DroneSimulator   运动学/电量/状态机/任务执行器/任务记录
    sim.server.DroneAgent + SimHTTPServer   HTTP API（PROTOCOL.md §3）
    sim.export                     Mission record -> §7.3 metadata.json
"""

from .config import SIM_VERSION, SimConfig, parse_args
from .simulator import DroneSimulator, MissionRuntime, SimulatorError

__all__ = [
    "SIM_VERSION",
    "SimConfig",
    "parse_args",
    "DroneSimulator",
    "MissionRuntime",
    "SimulatorError",
]
