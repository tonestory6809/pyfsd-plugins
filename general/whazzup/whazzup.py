"""General plugin, whazzup.py, 3, 0.1.0."""

from datetime import datetime
from json import JSONEncoder, dumps
from typing import TYPE_CHECKING, Any, Optional

from dependency_injector.wiring import Provide, inject

from pyfsd.define.utils import asyncify
from pyfsd.dependencies import Container
from pyfsd.plugin import PreventEvent, SimplePlugin

if TYPE_CHECKING:
    from aiohttp.web import Request, Response

    from pyfsd.factory.client import ClientFactory
    from pyfsd.object.client import Client
    from pyfsd.protocol.client import ClientProtocol


atis: dict[bytes, list[bytes]] = {}
pyfsd_plugin = SimplePlugin(
    "whazzup",
    (5, 0),
    (3, "0.1.0"),
    {
        "use_heading": bool,
        "client_coding": str,
        "register_httpapi": bool,
    },
)


class WhazzupEncoder(JSONEncoder):
    """Helper to encode whazzup dict include bytes to json."""

    @inject
    def default(self, o: object, config: dict = Provide[Container.config]) -> object:
        """Helper to decode bytes."""
        if isinstance(o, bytes):
            return o.decode(
                encoding=config["plugin"]["whazzup"]["client_coding"], errors="replace"
            )
        return super().default(o)


@pyfsd_plugin.audit("new_client_created")
async def fetch_atis(protocol: "ClientProtocol") -> None:
    """Ask new ATCs send their ATISs."""
    if protocol.client and protocol.client.is_controller:
        protocol.send_line(b"$CQatis_collector:%s:ATIS" % protocol.client.callsign)


@pyfsd_plugin.audit("client_disconnected")
async def clear_atis(_: "ClientProtocol", client: Optional["Client"]) -> None:
    """Remove ATCs' ATISs that are disconnected."""
    if client and client.is_controller and client.callsign in atis:
        del atis[client.callsign]


@pyfsd_plugin.handle("line_received_from_client")
async def collect_atis(protocol: "ClientProtocol", line: bytes) -> None:
    """Collect ATIS infoline.

    How it works:
        server: "$CQserver:<callsign>:ATIS" --> ATC
        ATC:    "#TM<callsign>:server:(ATIS infoline)" --> server (EuroScope ~3.2a)
        ATC:    "$CR<callsign>:server:ATIS:T:(ATIS infoline)" --> server (EuroScope ~3.2.9)
        ------
        (ATC changed infoline)
        ATC:    "$CQ<callsign>:@<frequency>:NEWINFO" --> server (EuroScope ~3.2.9)
    """

    def add_atis(line: bytes, callsign: bytes) -> None:
        if callsign not in atis:
            # If the statement (^) is false when executing if statement and
            atis[callsign] = []
            # ^ when this statement, self.atis[callsign] exists, then ATISs before
            # maybe overrode FIXME
        atis[callsign].append(line)

    if (
        (command := line[:3]) in (b"#TM", b"$CR", b"$CQ")
        and (packet_len := len(parts := line.split(b":", maxsplit=6))) >= 3
        and protocol.client
        and protocol.client.callsign == (callsign := parts[0][3:])
    ):
        if parts[1] == b"atis_collector":
            if command == b"#TM":
                add_atis(parts[2], callsign)
                raise PreventEvent
            if (
                command == b"$CR"
                and packet_len >= 5
                and parts[2] == b"ATIS"
                and parts[3] == b"T"
            ):
                add_atis(parts[4], callsign)
                raise PreventEvent
        if parts[2] == b"NEWINFO":
            atis[callsign] = []
            protocol.send_line(b"$CQatis_collector:%s:ATIS" % protocol.client.callsign)


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
    utc_now = datetime.utcnow()
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
            "logon_time": datetime.fromtimestamp(client.start_time).strftime(
                "%Y-%m-%dT%H:%M:%S.%f0Z"
            ),
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
    )


@pyfsd_plugin.setuper
@inject
async def startup(config: dict = Provide[Container.config]) -> None:
    plugin_config = config["plugin"]["whazzup"]
    # ===============
    if plugin_config["register_httpapi"]:
        from aiohttp.web import Response, get

        from .httpapi import app  # This may raise

        async def generate_whazzup(_: "Request") -> "Response":
            return Response(
                text=await asyncify(whazzup_json_string)(
                    heading_instead_pbh=plugin_config["use_heading"],
                ),
                content_type="application/json",
            )

        app.add_routes([get("/whazzup.json", generate_whazzup)])
