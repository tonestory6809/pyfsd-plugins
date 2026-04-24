"""MetarFetcher plugin, xmairavt7_metar.py, 8, 1.2."""

from html.parser import HTMLParser
from typing import TYPE_CHECKING

from aiohttp import ClientSession
from dependency_injector.wiring import Provide, inject

from pyfsd.dependencies import Container
from pyfsd.metar.profile import WeatherProfile
from pyfsd.plugin import SimplePlugin

if TYPE_CHECKING:
    from pyfsd.metar.manager import MetarManager, PyFSDMetarConfig


class MetarPageParser(HTMLParser):
    metar_text: str | None = None

    def handle_data(self, data: str) -> None:
        if self.lasttag == "font" and data.startswith(("METAR ", "SPECI ")):
            self.metar_text = data[6:]


async def fetch(_: "PyFSDMetarConfig | dict", icao: str) -> WeatherProfile | None:
    async with (
        ClientSession() as session,
        session.get(
            f"http://xmairavt7.xiamenair.com/WarningPage?WarningAirports={icao}"
        ) as resp,
    ):
        parser = MetarPageParser()
        parser.feed(await resp.text(errors="ignore"))
        if parser.metar_text is None:
            return None
        return WeatherProfile(parser.metar_text)


pyfsd_plugin = SimplePlugin("xmairavt7_metar", (5, 0), (8, "1.2"), None)


@pyfsd_plugin.setuper
@inject
async def register(
    metar_manager: "MetarManager" = Provide[Container.metar_manager],
) -> None:
    metar_manager.register_once_fetcher("xmairavt7", fetch)
