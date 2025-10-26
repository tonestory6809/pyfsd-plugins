"""MetarFetcher plugin, awc_metar.py, 6, 1.1.1."""

from asyncio import get_event_loop
from gzip import decompress
from typing import TYPE_CHECKING
from xml.etree.ElementTree import ParseError, fromstring

from aiohttp import ClientSession
from dependency_injector.wiring import Provide, inject

from pyfsd.dependencies import Container
from pyfsd.metar.fetch import MetarInfoDict
from pyfsd.metar.profile import WeatherProfile
from pyfsd.plugin import SimplePlugin

if TYPE_CHECKING:
    from pyfsd.metar.manager import MetarManager, PyFSDMetarConfig


pyfsd_plugin = SimplePlugin("awc_metar", (5, 0), (6, "1.1.1"), None)


@pyfsd_plugin.setuper
@inject
async def register_fetcher(
    metar_manager: "MetarManager" = Provide[Container.metar_manager],
) -> None:
    metar_manager.register_once_fetcher("aviationweather", fetch)
    metar_manager.register_cron_fetcher("aviationweather", fetch_all)


async def fetch(
    config: "dict | PyFSDMetarConfig", icao: str
) -> "WeatherProfile | None":
    async with (
        ClientSession() as session,
        session.get(
            f"https://aviationweather.gov/cgi-bin/data/metar.php?ids={icao}"
        ) as resp,
    ):
        if resp.status != 200:
            return None
        lines = (await resp.text("ascii", "ignore")).splitlines()
        if not lines:
            return None
        return WeatherProfile(lines[0].rstrip("\n"))


async def fetch_all(config: "dict | PyFSDMetarConfig") -> "MetarInfoDict | None":
    async with (
        ClientSession() as session,
        session.get(
            "https://aviationweather.gov/data/cache/metars.cache.xml.gz"
        ) as resp,
    ):
        if resp.status != 200:
            return None
        try:
            root = fromstring(decompress(await resp.read()))
        except ParseError:
            return None

        data_section = root.find("data")
        if data_section is None:
            return None

        def parse() -> MetarInfoDict:
            result: MetarInfoDict = {}
            for metar in data_section:
                station_id = metar.findtext("station_id")
                raw_text = metar.findtext("raw_text")
                if station_id is None or raw_text is None:
                    continue

                result[station_id] = WeatherProfile(raw_text)
            return result

        return await get_event_loop().run_in_executor(None, parse)
