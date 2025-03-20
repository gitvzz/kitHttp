from typing import Any, Optional
import aiohttp
from aiohttp import web


class Socket:
    def __init__(self, ws: web.WebSocketResponse, _id) -> None:
        self.ws = ws
        self._id = _id

    async def emit(self, event: str, data: Any):
        if "Result" in str(type(data)):
            data = data.json
        await self.ws.send_json({"event": event, "data": data})

    async def close(self, message: Optional[str] = None):
        if not self.ws.closed:
            await self.ws.close(
                code=aiohttp.WSCloseCode.GOING_AWAY,
                message=message.encode() if message else b"",
            )
