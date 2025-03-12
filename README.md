# aioServer

aioServer是一个基于aiohttp的轻量级异步Web服务器框架，旨在简化常见Web应用和WebSocket服务的开发。它提供了简洁的API接口、自动路由注册、中间件机制、WebSocket支持和统一的响应格式，同时还包含了客户端组件，方便以客户端身份进行HTTP请求和WebSocket通信。

## 特点

- **简化的路由系统**：通过方法命名约定自动注册路由，无需手动配置
- **中间件机制**：内置参数合并、认证和WebSocket支持的中间件
- **WebSocket支持**：基于事件的WebSocket通信，支持服务端和客户端
- **统一的响应格式**：使用Result类封装API响应，保持一致性
- **异常处理**：统一的错误处理机制，简化错误响应
- **客户端组件**：内置HTTP客户端和WebSocket客户端，方便调用外部服务
- **类型提示**：完善的类型注解，提高代码可读性和IDE支持

## 安装

```bash
pip install -e .
```

## 服务端使用示例

### 基本HTTP服务器

```python
from aioServer import KitHttp
from netfere import Result

class MyServer(KitHttp):
    # 处理根路径 GET 请求 - 访问 / 或 /index
    async def indexGet(self, request):
        return self.html_response("<h1>欢迎使用 aioServer!</h1>")
    
    # 处理 /api GET 请求
    async def apiGet(self, request, name=None):
        return Result(True, data={"message": f"你好, {name or '世界'}!"})
    
    # 处理 /user/info GET 请求 (下划线会转换为路径分隔符)
    async def user_infoGet(self, request, user_id=None):
        return Result(True, data={"user_id": user_id, "name": "测试用户"})
    
    # 处理 /login POST 请求
    async def loginPost(self, request, username, password):
        if username == "admin" and password == "123456":
            return Result(True, data={"token": "sample_token"})
        return Result(False, msg="用户名或密码错误")

if __name__ == "__main__":
    server = MyServer(port=8000)
    server.run()
```

### WebSocket服务器

```python
from aioServer import KitHttp
from netfere import Result
from aioServer.websocket import Socket

class ChatServer(KitHttp):
    # WebSocket 连接处理 - 访问 /chat
    async def chatSocket(self, request, socket: Socket, **kwargs):
        # 这个方法只在连接建立时调用一次
        await socket.emit("welcome", {"message": "欢迎加入聊天室!"})
        
    # 处理 message 事件
    async def messageEvent(self, request, socket: Socket, data, **kwargs):
        # 广播消息给所有客户端
        await self.broadcast("new_message", {
            "user": data.get("user", "匿名"),
            "content": data.get("content", ""),
            "time": "2023-01-01 12:00:00"
        })
        return Result(True, msg="消息已发送")
    
    # 处理 join_room 事件
    async def join_roomEvent(self, request, socket: Socket, data, callback=None, **kwargs):
        room_id = data.get("room_id")
        # 如果提供了回调，则调用它
        if callback:
            await callback({"room_id": room_id, "status": "joined"}, socket, request)
        return Result(True, data={"room": room_id})

if __name__ == "__main__":
    server = ChatServer(port=8000)
    server.run()
```

## 客户端使用示例

### HTTP客户端

```python
import asyncio
from aioServer.clientrequest import ClientRequest

async def main():
    # 基本GET请求
    result = await ClientRequest.get("https://api.example.com/users")
    if result.success:
        print(f"用户数据: {result.data}")
    else:
        print(f"请求失败: {result.msg}")
    
    # 带参数的POST请求
    result = await ClientRequest.post(
        "https://api.example.com/login",
        data={"username": "admin", "password": "123456"},
        headers={"Content-Type": "application/json"}
    )
    
    # 自定义请求
    request = ClientRequest(
        "https://api.example.com/users",
        method="PUT",
        data={"name": "张三", "email": "zhangsan@example.com"},
        timeout=30,  # 30秒超时
    )
    result = await request.fetch()

asyncio.run(main())
```

### WebSocket客户端

```python
import asyncio
from aioServer.clientsocket import ClientSocket

async def main():
    # 创建WebSocket客户端
    client = ClientSocket("chat_client", "ws://localhost:8000/chat")
    
    # 注册事件处理函数
    @client.on("welcome")
    async def on_welcome(data):
        print(f"收到欢迎消息: {data['message']}")
        # 加入聊天室
        await client.emit("join_room", {"room_id": "general"})
    
    @client.on("new_message")
    async def on_message(data):
        print(f"{data['user']}: {data['content']}")
    
    # 监听连接状态
    async def connection_status(connected, error):
        if connected:
            print("已连接到服务器")
        else:
            print(f"连接断开: {error}")
    
    client.add_status_listener(connection_status)
    
    # 启动客户端
    try:
        # 连接到服务器
        connect_task = asyncio.create_task(client.connect())
        
        # 等待用户输入并发送消息
        await asyncio.sleep(2)  # 等待连接建立
        
        # 发送消息
        await client.emit("message", {
            "user": "张三",
            "content": "大家好!"
        })
        
        # 使用请求-响应模式
        response = await client.emit_with_timeout("join_room", {"room_id": "vip"}, 5.0)
        if response:
            print(f"加入房间响应: {response}")
        
        # 运行一段时间后关闭
        await asyncio.sleep(30)
        await client.close()
        
    except KeyboardInterrupt:
        await client.close()

asyncio.run(main())
```

## 高级功能

### 文件上传处理

```python
from aioServer import KitHttp
from netfere import Result
from pathlib import Path

class FileServer(KitHttp):
    async def uploadPost(self, request):
        reader = await request.multipart()
        
        # 获取表单字段
        field = await reader.next()
        assert field.name == "file"
        
        # 保存文件
        files = await self.save_file(
            [field],
            Path("./uploads"),
            limit_size=1024 * 1024 * 5,  # 限制5MB
            limit_formats=["image/jpeg", "image/png"]
        )
        
        if files:
            return Result(True, data={"filename": files[0].name})
        return Result(False, msg="文件上传失败")

```

### 中间件和认证

```python
from aioServer import KitHttp
from aioServer.middleware import ignore_auth
from netfere import Result

class SecureServer(KitHttp):
    def __init__(self):
        super().__init__(
            port=8000,
            secret_key="your-secret-key",  # 启用JWT认证
        )
    
    # 登录接口 - 不需要认证
    @ignore_auth
    async def loginAction(self, request, username, password):
        if username == "admin" and password == "123456":
            # 返回JWT令牌
            return Result(True, data={"token": "sample_token"})
        return Result(False, msg="用户名或密码错误")
    
    # 需要认证的接口
    async def profileGet(self, request, user):
        # user参数由中间件自动注入
        return Result(True, data={"id": user.id, "name": user.name})
```

## 依赖

- aiohttp=3.11.11
- netfere (内部工具库)

## 许可证

MIT
