"""General plugin, bug_workaround.py, 3, 1.1."""

from asyncio import sleep
from typing import TYPE_CHECKING

from dependency_injector.wiring import Provide, inject
from structlog import get_logger

from pyfsd.define.packet import break_packet
from pyfsd.dependencies import Container
from pyfsd.plugin import SimplePlugin

if TYPE_CHECKING:
    from pyfsd.factory.client import ClientFactory
    from pyfsd.protocol.client import ClientProtocol

logger = get_logger()
pyfsd_plugin = SimplePlugin("bug_workaround", (5, 0), (3, "1.1"), None)


@pyfsd_plugin.handle("line_received_from_client")
@inject
async def handle_line(
    __: "ClientProtocol",
    line: bytes,
    factory: "ClientFactory" = Provide[Container.client_factory],
) -> None:
    if line.startswith(b"#AA"):
        _, packet = break_packet(line, (b"#AA",))
        if len(packet) >= 7:
            (
                callsign,
                _,
                _,
                cid,
                password,
            ) = packet[:5]
        else:
            return
    elif line.startswith(b"#AP"):
        _, packet = break_packet(line, (b"#AP",))
        if len(packet) >= 8:
            (
                callsign,
                _,
                cid,
                password,
            ) = packet[:4]
        else:
            return
    else:
        return
    if callsign in factory.clients and await factory.check_auth(
        cid.decode("utf-8"), password.decode("utf-8")
    ):
        transport = factory.clients[callsign].transport
        await logger.awarning(
            f"*** Kicking {callsign!r} {transport.is_closing()} {transport.is_reading()}"
        )
        transport.close()
        while callsign in factory.clients:
            await sleep(0.05)


@pyfsd_plugin.audit("new_connection_established")
async def send_loading(protocol: "ClientProtocol") -> None:
    protocol.send_line(b"#TMserver:unknown:Loading...")
