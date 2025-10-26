"""General plugin, httpapi.py, 4, 0.1.2."""

from collections.abc import Awaitable
from json import JSONDecodeError, loads
from typing import (
    TYPE_CHECKING,
    Callable,
    Optional,
    TypeVar,
    cast,
)

from aiohttp import web
from argon2 import PasswordHasher
from dependency_injector.wiring import Provide, inject
from sqlalchemy import exists, select
from structlog import get_logger
from typing_extensions import NotRequired

from pyfsd.db_tables import users_table
from pyfsd.define.check_dict import VerifyKeyError, check_dict
from pyfsd.dependencies import Container
from pyfsd.plugin import SimplePlugin

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from pyfsd.factory.client import ClientFactory

# =============== Decorator
C = TypeVar("C", bound=Callable)
hasher = PasswordHasher()


def check(auth: bool = False, body_format: Optional[dict] = None) -> Callable[[C], C]:
    """Annotate a handler."""

    def decorator(func: C) -> C:
        setattr(func, "auth", auth)  # noqa: B010
        setattr(func, "body_format", body_format)  # noqa: B010
        return func

    return decorator


# =============== Misc

logger = get_logger(__name__)
routes = web.RouteTableDef()
problem_json_mime = "application/problem+json"


@web.middleware
async def middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Middleware, helper to check body format & auth."""
    if format_ := getattr(handler, "body_format", None):
        try:
            body = loads(await request.read())
        except JSONDecodeError:
            return web.json_response(
                {"type": "invaild-body", "title": "Excepted JSON body"},
                status=400,
                content_type=problem_json_mime,
            )
        errors = tuple(check_dict(body, format_, name="body"))
        if errors:
            invalid_params = []
            for error in errors:
                if isinstance(error, VerifyKeyError):
                    invalid_params.append({"name": error.key, "reason": error.type})
                else:
                    invalid_params.append({"name": error.name, "reason": str(error)})
            return web.json_response(
                {
                    "type": "invaild-body",
                    "title": "Some parameters isn't vaild.",
                    "invalid-params": invalid_params,
                },
                status=400,
                content_type=problem_json_mime,
            )
    if getattr(handler, "auth", False):
        authorization = request.headers.get("Authorization", None)
        if authorization is None:
            return web.json_response(
                {
                    "type": "auth-failure",
                    "title": "Authorization failure",
                    "detail": "Must specify token by 'Authorization: Bearer' header",
                },
                status=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="token"',
                },
                content_type=problem_json_mime,
            )
        if not authorization.startswith("Bearer "):
            return web.json_response(
                {
                    "type": "auth-failure",
                    "title": "Authorization failure",
                    "detail": "Accept 'Authorization: Bearer' header only",
                },
                status=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="token", error="invalid_token",'
                    ' error_description="Only Bearer authorization accepted"',
                },
                content_type=problem_json_mime,
            )
        if authorization[7:] != plugin_config["token"]:
            return web.json_response(
                {
                    "type": "auth-failure",
                    "title": "Authorization failure",
                    "detail": "Invaild token",
                },
                status=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="token", error="invalid_token", '
                    'error_description="Token incorrect"',
                },
                content_type=problem_json_mime,
            )

    try:
        return await handler(request)
    except web.HTTPException as ex:
        if ex.status == 404:
            return web.json_response(
                {"type": "not-found", "title": ex.reason},
                status=404,
                content_type=problem_json_mime,
            )
        raise


app = web.Application(logger=logger, middlewares=(middleware,))

plugin_config: dict


# =============== API
@routes.get("/users")
@inject
async def get_all_users_rating(
    _: web.Request, db_engine: "AsyncEngine" = Provide[Container.db_engine]
) -> web.Response:
    """Get all users' rating."""
    users: dict[int, list[str]] = {}
    async with db_engine.begin() as conn:
        for user in await conn.execute(
            select(users_table.c.callsign, users_table.c.rating)
        ):
            callsign, rating = cast("tuple[str, int]", user)
            if rating not in users:
                users[rating] = []
            users[rating].append(callsign)
    return web.json_response(users)


@routes.get("/users/{callsign}")
@inject
async def get_user_rating(
    request: web.Request, db_engine: "AsyncEngine" = Provide[Container.db_engine]
) -> web.Response:
    """Get a user's rating."""
    async with db_engine.begin() as conn:
        for user in await conn.execute(
            select(users_table.c.rating).where(
                users_table.c.callsign == request.match_info["callsign"]
            )
        ):
            return web.json_response({"exist": True, "rating": user[0]})
    return web.json_response({"exist": False})


@routes.put("/users")
@check(auth=True, body_format={"callsign": str, "password": str})
@inject
async def create_user(
    request: web.Request, db_engine: "AsyncEngine" = Provide[Container.db_engine]
) -> web.Response:
    """Create user."""
    data = loads(await request.read())
    async with db_engine.begin() as conn:
        for result in await conn.execute(
            exists().where(users_table.c.callsign == data["callsign"]).select()
        ):
            if result[0]:
                return web.json_response(
                    {"type": "callsign-conflict", "title": "Callsign already exist"},
                    status=409,
                    content_type=problem_json_mime,
                )

        await conn.execute(
            users_table.insert().values(
                callsign=data["callsign"],
                password=hasher.hash(data["password"]),
                rating=1,
            )
        )
    raise web.HTTPNoContent


@routes.patch("/users/{callsign}")
@check(
    auth=True, body_format={"password": NotRequired[str], "rating": NotRequired[int]}
)
@inject
async def modify_user(
    request: web.Request, db_engine: "AsyncEngine" = Provide[Container.db_engine]
) -> web.Response:
    """Modify user."""
    data = loads(await request.read())
    if not data:
        return web.json_response(
            {
                "type": "invaild-body",
                "title": "Must modify password or rating",
            },
            content_type=problem_json_mime,
            status=400,
        )
    if "password" in data:
        data["password"] = hasher.hash(data["password"])
    async with db_engine.begin() as conn:
        for result in await conn.execute(
            exists()
            .where(users_table.c.callsign == request.match_info["callsign"])
            .select()
        ):
            if not result[0]:
                return web.json_response(
                    {"type": "user-not-found", "title": "User not found"},
                    status=404,
                    content_type=problem_json_mime,
                )
            await conn.execute(
                users_table.update()
                .where(users_table.c.callsign == request.match_info["callsign"])
                .values(**data)
            )
    raise web.HTTPNoContent


@routes.post("/users")
@check(auth=True, body_format={"callsign": str, "password": str})
@inject
async def check_auth(
    request: web.Request,
    client_factory: "ClientFactory" = Provide[Container.client_factory],
) -> web.Response:
    """Check password."""
    data = loads(await request.read())
    result = await client_factory.check_auth(*data.values())
    if result is None:
        raise web.HTTPForbidden
    return web.json_response({"rating": result})


@routes.delete("/users/{callsign}")
@check(auth=True)
@inject
async def delete_user(
    request: web.Request, db_engine: "AsyncEngine" = Provide[Container.db_engine]
) -> web.Response:
    """Create user."""
    async with db_engine.begin() as conn:
        for result in await conn.execute(
            exists()
            .where(users_table.c.callsign == request.match_info["callsign"])
            .select()
        ):
            if not result[0]:
                return web.json_response(
                    {"type": "user-not-found", "title": "User not found"},
                    status=404,
                    content_type=problem_json_mime,
                )
            await conn.execute(
                users_table.delete().where(
                    users_table.c.callsign == request.match_info["callsign"]
                )
            )
    raise web.HTTPNoContent


app.add_routes(routes)


# =============== Launcher
pyfsd_plugin = SimplePlugin(
    "httpapi",
    (5, 0),
    (4, "0.1.2"),
    {
        "port": int,
        "token": str,
    },
)
runner: "web.AppRunner | None" = None


@pyfsd_plugin.audit("before_start")
@inject
async def run(config: dict = Provide[Container.config]) -> None:
    global plugin_config, runner
    plugin_config = config["plugin"]["httpapi"]

    runner = web.AppRunner(app, access_log=logger)
    await runner.setup()
    site = web.TCPSite(
        runner,
        port=plugin_config["port"],
    )
    await site.start()


@pyfsd_plugin.audit("before_stop")
async def stop() -> None:
    if runner:
        await runner.cleanup()
