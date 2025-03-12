import logging
import weakref

from pathlib import Path
from typing import Callable, Union, Optional, Dict, Type

from aiohttp import web
from netfere import Result, datetime, utils
from .middleware import ignore_auth, middleware_factory
from .router import Router
from .websocket import Socket

log = logging.getLogger(__name__)

routes = web.RouteTableDef()


class KitHttp:
    """异步Web服务器框架

    Args:
        host: 服务器主机地址
        port: 服务器端口
        secret_key: JWT密钥，如果为None则不启用认证
        client_max_size: 客户端请求最大大小（字节）
        jwt_class: JWT数据类，用于解析JWT数据
        route_prefix: 路由前缀，会添加到所有路由路径前面
        static_path: 静态文件目录路径，如果为None则不提供静态文件服务
        static_prefix: 静态文件URL前缀


    基于aiohttp的异步Web服务器框架，提供了简化的路由系统、中间件机制、
    WebSocket支持和统一的响应格式。

    特点:
    - 简化的路由系统：通过方法命名约定自动注册路由
    - 中间件机制：参数合并、认证和WebSocket支持
    - WebSocket支持：事件驱动的消息处理模式
    - 统一的响应格式：使用Result类封装API响应
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        secret_key: Optional[str] = None,
        client_max_size: int = 1024**2 * 10,
        jwt_class: Optional[Type] = None,
        route_prefix: str = "",
        static_path: Optional[str] = None,
        static_prefix: str = "/static",
    ) -> None:

        self.secret_key = secret_key
        self._host = host
        self._port = port
        self._socket_clients = (
            weakref.WeakValueDictionary()
        )  # 初始化WebSocket客户端字典

        # 创建路由器
        router = Router(self, prefix=route_prefix)

        # 添加静态文件路由
        if static_path:
            router.add_static_routes(static_prefix, static_path)

        # 创建应用
        self.aio = web.Application(
            router=router,
            middlewares=middleware_factory(self, jwt_class),
            client_max_size=client_max_size,
        )

    def json_response(
        self, result: Result, headers: Optional[Dict[str, str]] = None, **kwargs
    ):
        """返回JSON响应

        Args:
            result: 结果对象
            headers: 响应头
            **kwargs: 传递给web.json_response的其他参数

        Returns:
            JSON响应对象
        """
        return web.json_response(result.json, headers=headers, **kwargs)

    def html_response(self, html_content: str, **kwargs):
        """返回HTML响应

        Args:
            html_content: HTML内容
            **kwargs: 传递给web.Response的其他参数

        Returns:
            HTML响应对象
        """
        return web.Response(text=html_content, content_type="text/html", **kwargs)
    
    def status_response(self, status: int=200, **kwargs):
        """返回状态响应

        Args:
            status: 状态码
            **kwargs: 传递给web.Response的其他参数
        """
        return web.Response(status=status, **kwargs)

    async def indexGet(self, _, **kwargs):
        """处理根路径的GET请求"""
        return self.html_response("<h1>欢迎使用 aioServer!</h1>")

    async def favicon_icoGet(self, _):
        """处理favicon.ico请求"""
        return web.Response(status=204)  # 返回204 No Content状态码

    @ignore_auth
    async def loginAction(self, _, **kwargs):
        """默认登录处理方法

        子类应该重写此方法以提供实际的登录逻辑

        Args:
            request: HTTP请求对象
            **kwargs: 请求参数

        Returns:
            登录失败的结果
        """
        return Result(success=False, msg="登录失败")

    async def broadcast(
        self,
        event: str,
        data: Union[dict, str],
        filter: Optional[Callable[[Socket], bool]] = None,
    ):
        for io in [
            io for io in self._socket_clients.values() if filter is None or filter(io)
        ]:
            await io.emit(event, data)

    async def save_file(
        self,
        files: list[web.FileField],
        path: Path,
        limit_size: Optional[int] = None,
        limit_formats: Optional[list[str]] = None,
    ) -> list[Path]:
        """保存文件到指定路径，返回保存的文件路径列表"""
        result = []
        curr_date = datetime().strftime("%Y%m%d")
        path = path / curr_date
        if not path.exists():
            path.mkdir(parents=True)

        for file in files:
            file_size = 0
            if limit_formats and file.content_type not in limit_formats:
                continue

            ext = file.content_type.split("/")[-1]
            filename = f"{utils.randomStr(10)}.{ext}"
            location = path / filename

            try:
                with open(location, "wb") as f:
                    while True:
                        chunk = file.file.read(1024)  # 每次读取 1024 字节
                        if not chunk:
                            break
                        f.write(chunk)
                        file_size += len(chunk)
                        if limit_size and limit_size < file_size:
                            location = None
                            break
                    if location:
                        result.append(location)
            except Exception as e:
                log.exception(e)
        return result

    def run(self):
        """运行服务器（阻塞）

        使用aiohttp的run_app函数运行服务器，会阻塞当前线程
        """
        web.run_app(self.aio, host=self._host, port=self._port)

    async def start(self):
        """异步启动服务器

        适用于需要在其他异步代码中启动服务器的场景
        """
        runner = web.AppRunner(self.aio)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()
        print(
            f"======== Running on http://{self._host}:{self._port} ========\n{datetime()} (Press CTRL+C to quit)"
        )

    async def stop(self):
        """异步停止服务器

        关闭所有WebSocket连接并清理资源
        """
        # 关闭所有WebSocket连接
        if hasattr(self, "_socket_clients") and self._socket_clients:
            for io in [io for io in self._socket_clients.values() if not io.ws.closed]:
                await io.close("Server shutdown")

        # 关闭应用
        await self.aio.shutdown()
        await self.aio.cleanup()
