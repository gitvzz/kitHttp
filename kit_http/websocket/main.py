import json
import logging

import aiohttp
from aiohttp import web
from kit_utils import utils

import kit_http

from .socket import Socket

log = logging.getLogger(__name__)


async def ask(data, socket: Socket, request):
    if not socket.ws.closed:
        await socket.ws.send_json(
            {
                "event": request["event"],
                "data": data,
                "callback": request["callback"],
            }
        )


async def todo(
    self: "kit_http.KitHttp",
    socket: Socket,
    payload,
    request: web.Request,
    handler,
    **kwargs,
):
    event = payload.get("event")
    data = payload.get("data")
    callback = payload.get("callback")

    # 更新 kwargs 以便在后续的处理程序中使用
    kwargs["event"] = event
    kwargs["data"] = data

    # 如果有回调，则将回调逻辑设置在 request 中
    if callback:
        request["event"] = event
        request["callback"] = callback
        kwargs["callback"] = ask

    try:
        if hasattr(self, f"{event}Event"):
            handler = getattr(self, f"{event}Event")

        params = utils.getParams(handler, kwargs)
        value = await handler(request, socket=socket, **params)
        if value:
            await socket.emit(event, value)
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        await socket.emit("error", {"message": str(e)})


async def websocket(self: "kit_http.KitHttp", request: web.Request, handler, **kwargs):

    _id = kwargs.pop("id", utils.randomStr(10, is_digits=True))

    ws = web.WebSocketResponse()
    socket = Socket(ws, _id)
    self._socket_clients[_id] = socket

    # 检查是否可以准备为 WebSocket
    if not ws.can_prepare(request):
        return web.json_response({"error": "Not a WebSocket request"}, status=400)

    await ws.prepare(request)

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    await todo(self, socket, payload, request, handler, **kwargs)
                except json.JSONDecodeError:
                    await socket.emit("error", {"message": "Invalid JSON format"})
                except Exception as e:
                    await socket.emit(
                        "error",
                        {"message": "An unexpected error occurred", "error": str(e)},
                    )

            elif msg.type == aiohttp.WSMsgType.BINARY:
                ...
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                log.debug("ws connection closed")

            elif msg.type == aiohttp.WSMsgType.ERROR:
                error = f"ws connection closed with exception {ws.exception()}"
                log.debug(error)

            else:
                log.debug("Unexpected message type: %s", msg.type)
    finally:
        if not ws.closed:
            await ws.close()
        self._socket_clients.pop(_id, None)

    return ws
