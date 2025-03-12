import json
import logging
from typing import Dict, List, Optional, Any, Tuple, cast

from aiohttp import web
from aiohttp.web_request import FileField
from aiohttp.multipart import BodyPartReader  # 导入正确的类型
from netfere import utils

import kitHttp

from .websocket import websocket

log = logging.getLogger(__name__)


def ignore_auth(func):
    func._no_auth_required = True  # 给函数添加一个自定义属性
    return func


async def extract_files_and_data(
    request: web.Request,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    从请求中提取文件和数据，返回文件对象和其他表单字段。

    Args:
        request: HTTP请求对象

    Returns:
        包含文件列表和表单数据的元组
    """
    reader = await request.multipart()
    files: List[Dict[str, Any]] = []
    data: Dict[str, str] = {}

    while True:
        part = await reader.next()
        if part is None:
            break

        # 使用cast确保类型检查器知道part是BodyPartReader类型
        part = cast(BodyPartReader, part)

        # 确保name不为None
        if part.name is None:
            continue

        if part.filename:
            # 读取文件内容到内存，也可以选择其他处理方式
            content = await part.read(decode=False)
            files.append(
                {
                    "name": part.name,
                    "filename": part.filename or "",  # 确保filename不为None
                    "content": content,
                    "content_type": part.headers.get(
                        "Content-Type", "application/octet-stream"
                    ),
                }
            )
        else:
            # 非文件字段
            text = await part.text()
            data[part.name] = text

    return files, data


def middleware_factory(self: "kitHttp.KitHttp", jwt_class: Optional[Any] = None):
    """
    创建中间件工厂

    Args:
        self: KitHttp实例
        jwt_class: JWT数据类，用于解析JWT数据

    Returns:
        中间件列表
    """

    @web.middleware
    async def merge_params(request: web.Request, handler):
        """
        合并请求参数中间件

        将查询参数、JSON数据、表单数据和路径参数合并到一个字典中

        参数处理流程:
        1. 从URL查询字符串中提取参数 (如 ?id=1&name=test)
        2. 如果请求内容类型是application/json，解析JSON数据
        3. 如果请求内容类型是multipart/form-data，处理表单数据和文件上传
           - 普通表单字段直接添加到参数字典
           - 文件字段收集到"files"列表中
        4. 提取URL路径中的参数 (如 /users/{id})
        5. 按优先级合并所有参数: 路径参数 > 表单数据 > JSON数据 > 查询参数
           - 后面的参数会覆盖前面的同名参数
        6. 从请求头中提取特殊参数:
           - Authorization: 用于身份验证
           - Upgrade: 用于检测WebSocket请求
           - Locale: 用于国际化
        7. 将处理后的参数存储在request对象中，供后续处理使用

        注意:
        - 如果参数同时出现在多个位置，优先使用后处理的值
        - 文件上传会被特殊处理并收集到"files"列表中
        - 特殊参数(Authorization, Locale)会从kwargs中移除，避免重复处理
        """
        # 获取 URL 查询参数并转换为字典
        query_params = dict(request.query)

        # 尝试获取 JSON 数据（如果有）
        try:
            if request.content_type == "application/json":
                json_params = await request.json()
            else:
                json_params = {}
        except json.JSONDecodeError:
            json_params = {}

        # 处理 multipart/form-data 参数
        form_params: Dict[str, Any] = {}
        if request.content_type == "multipart/form-data":
            form_data = await request.post()  # 获取表单数据
            for k, v in form_data.items():
                if isinstance(v, FileField):
                    if "files" in form_params:
                        form_params["files"].append(v)
                    else:
                        form_params["files"] = [v]
                else:
                    form_params[k] = v

        # 获取匹配的路径参数
        match_info_params = dict(request.match_info)

        # 合并所有参数
        kwargs = {**query_params, **json_params, **form_params, **match_info_params}

        upgrade = request.headers.get("Upgrade")
        is_websocket = upgrade and upgrade.lower() == "websocket"
        authorization = request.headers.get("Authorization") or kwargs.pop(
            "Authorization", None
        )

        locale = request.headers.get("Locale") or kwargs.pop("Locale", None)

        request["Authorization"] = authorization
        request["is_websocket"] = is_websocket
        request["locale"] = locale
        request["kwargs"] = kwargs

        return await handler(request)

    @web.middleware
    async def auth(request: web.Request, handler):
        """
        认证中间件

        验证请求中的JWT令牌
        """
        if not self.secret_key or getattr(handler, "_no_auth_required", False):
            return await handler(request)
        # 排除静态文件路径
        if request.path.startswith("/statics"):
            return await handler(request)

        authorization = request.get("Authorization")
        del request["Authorization"]

        if not authorization:
            return web.json_response({"error": "Forbidden"}, status=403)

        res = utils.jwt_decode(authorization, self.secret_key)
        if not res.success:
            return web.json_response({"error": f"Forbidden:{res.msg}"}, status=403)

        request["jwt"] = jwt_class(**res.data) if jwt_class else res.data

        return await handler(request)

    @web.middleware
    async def socketOrHandle(request: web.Request, handler):
        """
        WebSocket中间件 或 处理请求
        """
        is_websocket = request["is_websocket"]
        kwargs = request["kwargs"]
        kwargs["jwt"] = request.get("jwt")
        kwargs["locale"] = request.get("locale")
        del request["is_websocket"]
        del request["kwargs"]
        del request["locale"]

        if is_websocket:
            return await websocket(self, request, handler, **kwargs)
        else:
            params = utils.getParams(handler, kwargs)
            try:
                resp = await handler(request, **params)
            except Exception as e:
                if isinstance(e, ValueError):
                    return web.json_response(
                        {"success": False, "msg": f"Invalid value: {str(e)}"}
                    )
                else:
                    log.error(e)
                    return web.json_response(
                        {"success": False, "msg": f"Internal Server Error: {str(e)}"},
                        status=500,
                    )
            else:
                return (
                    web.json_response(resp.json)
                    if "Result" in str(type(resp))
                    else resp
                )

    return [merge_params, auth, socketOrHandle]


__all__ = ["middleware_factory", "ignore_auth"]
