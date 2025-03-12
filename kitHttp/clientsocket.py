import asyncio
import json
import logging
from typing import Callable, Dict, Optional, Any, Union, Awaitable, List

import aiohttp

log = logging.getLogger(__name__)


class ClientSocket:
    """WebSocket客户端

    Args:
        name: 客户端名称，用于日志标识
        url: WebSocket服务器URL
        re_delay: 重连延迟时间（秒）
        heartbeat: 心跳时间（秒）


    该类提供了基于事件的WebSocket通信机制，支持自动重连、心跳检测和请求-响应模式。

    用法示例:

    1. 基本连接和事件监听:
    ```python
    # 创建客户端实例
    client = ClientSocket("my_client", "ws://localhost:8080/socket")

    # 注册事件处理函数
    @client.on("message")
    def handle_message(data):
        print(f"收到消息: {data}")

    # 或者使用方法形式注册
    def handle_notification(data):
        print(f"收到通知: {data}")
    client.on("notification", handle_notification)

    # 启动客户端
    await client.run()
    ```

    2. 发送事件:
    ```python
    # 发送简单事件
    await client.emit("chat", {"message": "Hello, world!", "user": "Alice"})

    # 使用回调接收响应
    async def handle_response(response):
        print(f"服务器响应: {response}")

    await client.emit("get_users", {"group_id": 123}, handle_response)
    ```

    3. 请求-响应模式(带超时):
    ```python
    # 发送请求并等待响应，超时时间为5秒
    response = await client.emit_with_timeout("get_user_info", {"user_id": 456}, 5.0)
    if response:
        print(f"用户信息: {response}")
    else:
        print("请求超时或失败")
    ```

    4. 监听连接状态:
    ```python
    async def connection_status(connected, error):
        if connected:
            print("已连接到服务器")
        else:
            print(f"连接断开: {error}")

    client.add_status_listener(connection_status)
    ```

    5. 关闭连接:
    ```python
    # 手动关闭连接
    await client.close()
    ```

    6. 自定义连接后行为:
    ```python
    class MyClient(ClientSocket):
        async def after_connect(self):
            # 连接后自动加入聊天室
            await self.emit("join_room", {"room_id": "general"})
            print("已加入聊天室")
    ```

    注意事项:
    - 客户端会自动处理重连，无需手动重连
    - 事件处理函数可以是同步或异步函数
    - 使用emit_with_timeout可以实现类似RPC的调用模式
    - 可以通过继承并重写after_connect方法来自定义连接后的行为


    """

    def __init__(self, name: str, url: str, re_delay: int = 2, heartbeat: float = 30.0):

        self.name = name
        self.url = url
        self.re_delay = re_delay  # 重连延迟时间（秒）
        self.heartbeat = heartbeat  # 心跳时间（秒）
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.listener: Dict[str, Callable[[Any], Any]] = {}
        self._status_listeners: List[
            Callable[[bool, Optional[str]], Awaitable[None]]
        ] = []
        self._running = False
        self._reconnect_task = None

    async def after_connect(self):
        """连接后调用的钩子方法，可在子类中覆盖实现"""
        pass

    @property
    def connected(self) -> bool:
        """检查 WebSocket 是否已连接"""
        return self.ws is not None and not self.ws.closed

    def on(self, event: str, callback: Callable[[Any], Any]):
        """
        注册事件监听器

        Args:
            event: 事件名称
            callback: 回调函数，可以是同步或异步函数
        """
        self.listener[event] = callback
        return self  # 支持链式调用

    def un(self, event: str):
        """
        移除事件监听器

        Args:
            event: 要移除的事件名称
        """
        self.listener.pop(event, None)
        return self  # 支持链式调用

    def add_status_listener(
        self, listener: Callable[[bool, Optional[str]], Awaitable[None]]
    ):
        """
        添加连接状态监听器

        Args:
            listener: 状态变化回调函数，参数为(connected, error_message)
        """
        self._status_listeners.append(listener)
        return self  # 支持链式调用

    async def _notify_status_change(self, connected: bool, error: Optional[str] = None):
        """通知所有状态监听器连接状态变化"""
        for listener in self._status_listeners:
            try:
                await listener(connected, error)
            except Exception as e:
                log.error(f"[{self.name}] 状态监听器调用出错: {e}")

    async def connect(self):
        """建立 WebSocket 连接并开始监听消息"""
        if self._running:
            log.warning(f"[{self.name}] 已经在运行中，忽略重复的连接请求")
            return

        self._running = True

        # 确保旧会话已关闭
        if self.session and not self.session.closed:
            await self.session.close()

        self.session = aiohttp.ClientSession(conn_timeout=10)

        while self._running:
            try:
                log.info(f"[{self.name}] 正在连接到 {self.url}...")
                self.ws = await self.session.ws_connect(
                    self.url,
                    heartbeat=self.heartbeat,  # 使用配置的心跳时间
                )

                log.info(f"[{self.name}] 连接成功")
                await self._notify_status_change(True)
                await self.after_connect()
                await self.listen_messages()

                # 如果listen_messages正常退出，也应该尝试重连
                log.info(f"[{self.name}] WebSocket连接已关闭，准备重连")

            except (
                aiohttp.ClientConnectorError,
                aiohttp.ClientError,
                asyncio.TimeoutError,
                aiohttp.WSServerHandshakeError,
            ) as e:
                error_msg = f"连接失败 ({type(e).__name__}): {e}"
                log.warning(
                    f"[{self.name}] {error_msg}, 尝试在 {self.re_delay} 秒后重连..."
                )
                await self._notify_status_change(False, error_msg)

            except Exception as e:
                error_msg = f"发生未知错误: {e}"
                log.error(f"[{self.name}] {error_msg}")
                await self._notify_status_change(False, error_msg)

            # 清理旧连接
            if self.ws and not self.ws.closed:
                await self.ws.close()
            self.ws = None

            # 等待重连
            if self._running:
                await asyncio.sleep(self.re_delay)

    async def close(self):
        """关闭 WebSocket 和会话"""
        self._running = False

        if self.ws and not self.ws.closed:
            await self.ws.close()
            self.ws = None

        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

        log.info(f"[{self.name}] 客户端已关闭")

    async def listen_messages(self):
        """监听 WebSocket 消息"""
        if not self.ws:
            return

        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self.handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    log.info(f"[{self.name}] 服务端断开连接")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.info(f"[{self.name}] 服务端出错了: {self.ws.exception()}")
                    break
        except Exception as e:
            log.error(f"[{self.name}] 监听消息时出错: {e}")

    async def handle_message(self, message: str):
        """处理接收到的WebSocket消息"""
        try:
            response = json.loads(message)
            event = response.get("event")
            data = response.get("data")
            callback_id = response.get("callback")

            if callback_id and callback_id in self.listener:
                callback = self.listener[callback_id]
                result = callback(data)
                # 支持同步和异步回调
                if asyncio.iscoroutine(result):
                    await result
                self.un(callback_id)

            elif event in self.listener:
                callback = self.listener[event]
                result = callback(data)
                if asyncio.iscoroutine(result):
                    await result
            else:
                log.debug(f"[{self.name}] 收到未注册的事件: {event}")

        except json.JSONDecodeError:
            log.debug(f"[{self.name}] 无法解析JSON数据: {message}")
        except Exception as e:
            log.exception(f"[{self.name}] 处理消息时出错: {e}")

    async def emit(
        self,
        event: str,
        data: Optional[dict] = None,
        callback: Optional[Callable[[Any], Any]] = None,
    ) -> bool:
        """
        发送事件到 WebSocket 服务端

        Args:
            event: 事件名称
            data: 要发送的数据
            callback: 回调函数，当收到服务器响应时调用

        Returns:
            bool: 发送是否成功
        """
        if not self.connected or self.ws is None:
            log.warning(f"[{self.name}] 尝试发送事件 {event} 时WebSocket未连接")
            return False

        try:
            message = {"event": event, "data": data}

            if callback:
                _evt = f"{event}_ask"
                count = len([k for k in self.listener.keys() if k.startswith(_evt)])
                _evt += f"_{count}"
                self.on(_evt, callback)
                message["callback"] = _evt

            await self.ws.send_json(message)
            return True
        except Exception as e:
            log.error(f"[{self.name}] 发送事件 {event} 时出错: {e}")
            return False

    async def emit_with_timeout(
        self, event: str, data: Optional[dict] = None, timeout: float = 10.0
    ) -> Optional[Any]:
        """
        发送事件并等待响应，带超时机制

        Args:
            event: 事件名称
            data: 要发送的数据
            timeout: 超时时间（秒）

        Returns:
            服务器响应数据，超时则返回None
        """
        if not self.connected:
            log.warning(f"[{self.name}] 尝试发送事件 {event} 时WebSocket未连接")
            return None

        response_future = asyncio.Future()

        def callback(result):
            if not response_future.done():
                response_future.set_result(result)

        success = await self.emit(event, data, callback)
        if not success:
            return None

        try:
            return await asyncio.wait_for(response_future, timeout)
        except asyncio.TimeoutError:
            log.warning(f"[{self.name}] 等待事件 {event} 响应超时")
            return None

    async def run(self):
        """运行客户端，连接服务器并保持连接"""
        try:
            await self.connect()
        except Exception as e:
            log.error(f"[{self.name}] 运行时出错: {e}")
            await self.close()
            raise
