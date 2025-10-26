"""General plugin, debug.py, 4, 1.1.2."""

from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from structlog import get_logger

from pyfsd.dependencies import Container
from pyfsd.plugin import EventListenersDict, Plugin

if TYPE_CHECKING:
    from pyfsd.protocol.client import ClientProtocol

logger = get_logger()


class DebugPlugin(Plugin):
    name = "debug"
    api = (5, 0)
    version = (4, "1.1.2")
    expected_config = {"enabled": bool}

    @inject
    async def setup(
        self, config: dict = Provide[Container.config]
    ) -> "EventListenersDict | None":
        return {
            "handlers": {
                "line_received_from_client": [self.log_line_from_client]
            },
            "auditers": {
                "new_connection_established": [self.mock_write],
            }
        }

    async def mock_write(self, protocol: "ClientProtocol") -> None:
        write = protocol.transport.write

        def writer(data: "bytes | bytearray | memoryview[bytes]") -> None:
            host: str = protocol.transport.get_extra_info("peername")[0]
            line = data.decode("ascii", "backslashreplace")
            callsign = (
                protocol.client.callsign.decode("ascii", "backslashreplace")
                if protocol.client is not None
                else host
            )
            logger.debug(f'"{line}" ===> {callsign}')
            write(data)

        protocol.transport.write = writer  # type: ignore[method-assign]

    async def log_line_from_client(
        self, protocol: "ClientProtocol", line: bytes
    ) -> None:
        host: str = protocol.transport.get_extra_info("peername")[0]
        line_str = line.decode("ascii", "backslashreplace")
        callsign = (
            protocol.client.callsign.decode("ascii", "backslashreplace")
            if protocol.client is not None
            else host
        )

        await logger.adebug(f'"{line_str}" <=== "{callsign}"')

pyfsd_plugin = DebugPlugin()
