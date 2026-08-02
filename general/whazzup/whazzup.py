"""General plugin, whazzup.py, 6, 0.3.1."""

import asyncio
from datetime import datetime, timezone
from json import JSONEncoder, dumps
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from dependency_injector.wiring import Provide, inject

from pyfsd.define.protocol import FSDClientCommand
from pyfsd.define.protocol.packet import MulticastPacket, ServerBoundPacket
from pyfsd.define.utils import asyncify
from pyfsd.dependencies import Container
from pyfsd.plugin import PreventEvent, SimplePlugin

if TYPE_CHECKING:
    from aiohttp.web import Request, Response

    from pyfsd.client.net.factory import ClientFactory
    from pyfsd.client.object import Client
    from pyfsd.client.session import ClientSession
    from pyfsd.plugin.manager import PluginManager


atis: dict[bytes, list[bytes]] = {}
aircraft: dict[bytes, dict[bytes, bytes]] = {}
pyfsd_plugin = SimplePlugin(
    "whazzup",
    (5, 0),
    (7, "0.3.2"),
    {
        "use_heading": bool,
        "encoding": str,
        "register_httpapi": bool,
        "httpapi_require_auth": bool,
    },
)


class WhazzupEncoder(JSONEncoder):
    """Helper to encode whazzup dict include bytes to json."""

    @inject
    def default(self, o: object, config: dict = Provide[Container.config]) -> object:
        """Helper to decode bytes."""
        if isinstance(o, bytes):
            return o.decode(
                encoding=config["plugin"]["whazzup"]["encoding"], errors="replace"
            )
        return super().default(o)


@pyfsd_plugin.audit("new_client_created")
async def fetch_atis_aircraft(client: "Client") -> None:
    """Ask new ATCs for ATISs and pilots for aircraft information."""
    if client.is_controller:
        client.session.send_packets(
            MulticastPacket(
                FSDClientCommand.CLIENT_QUERY,
                b"atis_collector",
                client.callsign,
                b"ATIS",
            )
        )
    else:
        client.session.send_packets(
            MulticastPacket(
                FSDClientCommand.SQUAWK_BOX, b"atis_collector", client.callsign, b"PIR"
            )
        )


@pyfsd_plugin.audit("client_disconnected")
async def clear_atis(_: "ClientSession", client: "Client | None") -> None:
    """Remove ATCs' ATISs that are disconnected."""
    if client and client.is_controller and client.callsign in atis:
        del atis[client.callsign]


# ========== new atis debouncer
lock = asyncio.Lock()
notify_tasks: dict[bytes, asyncio.Task] = {}


@inject
async def _notify(
    callsign: bytes, pm: "PluginManager" = Provide[Container.plugin_manager]
) -> None:
    await asyncio.sleep(0.5)
    async with lock:
        if (data := atis.get(callsign, None)) is not None:
            pm.trigger_event_auditers_nonblock(
                "plugin_whazzup_new_atis", (callsign, data), {}
            )


async def _add_atis(callsign: bytes, line: bytes) -> None:
    async with lock:
        atis.setdefault(callsign, []).append(line)
        if (task := notify_tasks.get(callsign, None)) is not None:
            task.cancel()
        task = asyncio.create_task(_notify(callsign))
        notify_tasks[callsign] = task
        task.add_done_callback(lambda _: notify_tasks.pop(callsign, None))


# ==========


@pyfsd_plugin.handle("packet_received")
@inject
async def collect_atis_aircraft(
    session: "ClientSession",
    packet: ServerBoundPacket,
    pm: "PluginManager" = Provide[Container.plugin_manager],
) -> None:
    """Collect ATIS infoline and pilot aircraft.

    How it works:
        server: "$CQserver:<callsign>:ATIS" --> ATC
        ATC:    "#TM<callsign>:server:(ATIS infoline)" --> server (EuroScope ~3.2a)
        ATC:    "$CR<callsign>:server:ATIS:T:(ATIS infoline)" --> server (EuroScope ~3.2.9)
        ------
        (ATC changed infoline)
        ATC:    "$CQ<callsign>:@<frequency>:NEWINFO" --> server (EuroScope ~3.2.9)
        ========
        server: "#SBserver:<callsign>:PIR" --> Pilot
        pilot:  "#SB<callsign>:server:PI:GEN:EQUIPMENT=...:AIRLINE=...:LIVERY=..." --> server
    """

    if (
        not isinstance(packet, MulticastPacket)
        or (client := session.get_client()) is None
        or packet.data is None
    ):
        return

    match packet.command:
        case FSDClientCommand.MESSAGE if (
            client.is_controller and packet.dest == b"atis_collector"
        ):
            await _add_atis(packet.source, packet.data)
            raise PreventEvent
        case FSDClientCommand.CLIENT_RESPONSE if (
            client.is_controller
            and packet.dest == b"atis_collector"
            and packet.data.startswith(b"ATIS:T:")
        ):
            await _add_atis(packet.source, packet.data.removeprefix(b"ATIS:T:"))
            raise PreventEvent
        case FSDClientCommand.CLIENT_QUERY if (
            client.is_controller and packet.data.startswith(b"NEWINFO")
        ):
            atis[client.callsign] = []
            session.send_packets(
                MulticastPacket(
                    FSDClientCommand.CLIENT_QUERY,
                    b"atis_collector",
                    client.callsign,
                    b"ATIS",
                )
            )
        case FSDClientCommand.SQUAWK_BOX if (
            not client.is_controller
            and packet.dest == b"atis_collector"
            and packet.data.startswith(b"PI:GEN:")
        ):
            data = parse_qs(packet.data.removeprefix(b"PI:GEN:"), separator=":")
            result = {}
            for key in data:
                result[key] = data[key][-1]
            aircraft[client.callsign] = result
            await pm.trigger_event_auditers(
                "plugin_whazzup_aircraft", (client.callsign, result), {}
            )
            raise PreventEvent


@inject
def generate_whazzup(
    heading_instead_pbh: bool = False,
    client_factory: "ClientFactory" = Provide[Container.client_factory],
) -> dict:
    """Generate whazzup.

    Args:
        heading_instead_pbh: Use heading instead of PitchBankingHeading.
    """
    whazzup: dict[str, Any] = {"pilot": [], "controllers": []}
    utc_now = datetime.now(timezone.utc)
    whazzup["general"] = {
        "version": 3,
        "reload": 1,
        "update": utc_now.strftime("%Y%m%d%H%M%S"),
        "update_timestamp": utc_now.strftime("%Y-%m-%dT%H:%M:%S.%f0Z"),
    }
    for client in client_factory.clients.values():
        client_info = {
            "cid": client.cid,
            "name": client.realname,
            "callsign": client.callsign,
            "logon_time": datetime.fromtimestamp(
                client.start_time, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.%f0Z"),
            "rating": client.rating,
            "last_updated": client.last_updated,
        }
        if client.position_ok:
            lat, lon = client.position
            client_info["latitude"] = lat
            client_info["longitude"] = lon
            if not client.is_controller:
                client_info["altitude"] = client.altitude
                if heading_instead_pbh:
                    # https://github.com/xpilot-project/xpilot \
                    # /blob/b7a2375be88e8201c2c3fd8a353ace86f7ef49c3 \
                    # /client/src/fsd/pdu/pdu_base.cpp#L73-L82
                    heading = ((client.pbh >> 2) & 0x3FF) / 1024 * 360
                    if heading < 0:
                        heading += 360
                    elif heading >= 360:
                        heading -= 360
                    client_info["heading"] = round(heading)
                else:
                    client_info["pbh"] = client.pbh

        if not client.is_controller:
            client_info["groundspeed"] = client.ground_speed
            client_info["transponder"] = f"{client.transponder:04d}"
            if client.flight_plan is not None:
                client_info["flight_plan"] = {
                    "flight_rules": client.flight_plan.type,
                    "aircraft": client.flight_plan.aircraft,
                    "departure": client.flight_plan.dep_airport,
                    "arrival": client.flight_plan.dest_airport,
                    "alternate": client.flight_plan.alt_airport,
                    "cruise_tas": client.flight_plan.tascruise,
                    "altitude": client.flight_plan.alt,
                    "deptime": client.flight_plan.dep_time,
                    "hrs_enroute_time": client.flight_plan.hrs_enroute,
                    "min_enroute_time": client.flight_plan.min_enroute,
                    "hrs_fuel_time": client.flight_plan.hrs_fuel,
                    "min_fuel_time": client.flight_plan.min_fuel,
                    "remarks": client.flight_plan.remarks,
                    "route": client.flight_plan.route,
                    "revision_id": client.flight_plan.revision,
                }
            if (data := aircraft.get(client.callsign, None)) is not None:
                client_info["aircraft_info"] = {
                    "equipment": data.get(b"EQUIPMENT", None),
                    "airline": data.get(b"AIRLINE", None),
                    "livery": data.get(b"LIVERY", None),
                }
        else:
            if client.frequency_ok:
                client_info["frequency"] = (
                    f"1{client.frequency // 1000:02d}.{client.frequency % 1000:03d}"
                )
            client_info["facility"] = client.facility_type
            client_info["visual_range"] = client.visual_range
            if client.callsign in atis:
                client_info["atis"] = atis[client.callsign]

        whazzup["controllers" if client.is_controller else "pilot"].append(client_info)
    return whazzup


def whazzup_json_string(heading_instead_pbh: bool = False) -> str:
    """Generate whazzup json string.

    Args:
        heading_instead_pbh: Use heading instead of PitchBankingHeading.
    """
    return dumps(
        generate_whazzup(heading_instead_pbh=heading_instead_pbh),
        cls=WhazzupEncoder,
        ensure_ascii=False,
    )


@pyfsd_plugin.setuper
@inject
async def startup(config: dict = Provide[Container.config]) -> None:
    plugin_config = config["plugin"]["whazzup"]
    # ===============
    if plugin_config["register_httpapi"]:
        from aiohttp.web import Response, get

        from .httpapi import app, check  # This may raise

        async def generate_whazzup(_: "Request") -> "Response":
            return Response(
                text=await asyncify(whazzup_json_string)(
                    heading_instead_pbh=plugin_config["use_heading"],
                ),
                content_type="application/json",
            )

        app.add_routes(
            [
                get(
                    "/whazzup.json",
                    check(auth=True)(generate_whazzup)
                    if plugin_config["httpapi_require_auth"]
                    else generate_whazzup,
                )
            ]
        )
