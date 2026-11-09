"""兼容入口（旧文件名）：Drone Agent HTTP 服务。

规范启动方式是 `python -m sim.server`；本模块保留 `create_server()` / `main()`
以兼容旧调用方（tests/helpers.py 等）和 `python llm_drone/sim/drone_agent.py` 直接运行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_LLM_DRONE = Path(__file__).resolve().parents[1]
if str(_LLM_DRONE) not in sys.path:
    sys.path.insert(0, str(_LLM_DRONE))

from safety.audit import AuditManager  # noqa: E402
from safety.config import load_config  # noqa: E402

from .config import SimConfig  # noqa: E402
from .server import AgentApp, ServerHandle, create_agent_server  # noqa: E402
from .server import main as _server_main  # noqa: E402

SERVICE_NAME = "llm-drone-sim"


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    sim_config: Optional[SimConfig] = None,
    safety_config: Optional[Any] = None,
    audit: Optional[Any] = None,
    verbose: bool = False,
    start_tick: bool = True,
) -> ServerHandle:
    """兼容旧接口：创建（未启动）Drone Agent 服务器，port=0 时由系统分配。"""
    config = sim_config or SimConfig()
    config.host = host
    config.port = int(port)
    config.echo_audit = bool(verbose)
    safety = safety_config or load_config()
    if audit is None:
        audit = AuditManager(config.audit_dir, config.run_id, echo=bool(verbose))
    elif not isinstance(audit, AuditManager):
        class _Adapter:
            """把 AuditLogger 适配成 AuditManager 的最小接口。"""

            def __init__(self, logger: Any):
                self._logger = logger
                self.run_id = getattr(logger, "run_id", "default")
                self.path = getattr(logger, "path", "<audit>")

            def log(self, event, **fields):
                return self._logger.log(event, **fields)

            def read_events(self, since_seq=0):
                return self._logger.read_events(since_seq)

            def last_seq(self):
                return self._logger.last_seq()

            def switch_run(self, run_id):
                return self.path

            def close(self):
                return self._logger.close()

        audit = _Adapter(audit)
    app = AgentApp(config=config, safety_config=safety, audit=audit)
    handle = create_agent_server(config.host, config.port, config, safety, audit, app=app)
    if not start_tick:
        handle.httpd.stop_event.set()
    return handle


def main(argv=None) -> int:
    return _server_main(argv)


if __name__ == "__main__":
    sys.exit(main())
