import asyncio
import logging
from typing import Any, Dict, Literal, Optional, Union

import aiohttp
from kit_utils import Result, utils
from kit_utils.vars import seconds

log = logging.getLogger(__name__)

# 支持的HTTP方法
HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


def format(response: Result) -> Result:
    if response.success and response.data:
        success = response.data.get("success")
        msg = response.data.get("msg")
        data = response.data.get("data")
        code = response.data.get("code", 0 if success else -1)
        return Result(success, msg=msg, data=data, code=code)
    return response


class ClientRequest:
    """
     HTTP客户端请求类

     Args:
        url: 请求URL
        method: HTTP方法，支持GET、POST、PUT、DELETE、PATCH
        data: 请求数据，用于POST、PUT等方法
        params: URL参数，可以是字典或字符串
        headers: 请求头
        timeout: 超时时间（秒）
        proxy: 代理服务器URL
        verify_ssl: 是否验证SSL证书

    提供简单易用的HTTP请求接口，支持GET、POST、PUT、DELETE、PATCH等方法，
    自动处理JSON数据、超时和错误情况。

    """

    def __init__(
        self,
        url: str,
        method: HttpMethod = "GET",
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Union[str, Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: seconds = seconds(10),
        proxy: Optional[str] = None,
        verify_ssl: bool = True,
    ):
        self.url = url.rstrip("/")
        self.method = method
        self.data = data
        self.params = params
        self.headers = headers or {}
        self.timeout = timeout
        self.proxy = proxy
        self.verify_ssl = verify_ssl

    async def invoke(self) -> Result:
        """
        发送HTTP请求并获取响应

        Returns:
            Result对象，包含请求结果
        """
        # 处理URL参数
        url = self.url
        if isinstance(self.params, dict):
            url = f"{url}{utils.parse_params_to_str(self.params)}"
        elif isinstance(self.params, str) and self.params:
            if not self.params.startswith("?"):
                url = f"{url}?{self.params}"
            else:
                url = f"{url}{self.params}"
                
        # 设置超时
        timeout_settings = aiohttp.ClientTimeout(total=self.timeout)

        # 创建会话并发送请求
        try:
            async with aiohttp.ClientSession(timeout=timeout_settings) as session:
                method_func = getattr(session, self.method.lower())

                # 准备请求参数
                request_kwargs = {
                    "headers": self.headers,
                    "proxy": self.proxy,
                    "ssl": None if not self.verify_ssl else True,
                }

                # 根据请求方法添加数据
                if self.method != "GET" and self.data is not None:
                    request_kwargs["json"] = self.data

                # 发送请求
                async with method_func(url, **request_kwargs) as response:
                    # 处理响应状态
                    if response.status >= 400:
                        error_text = await response.text()
                        return Result(
                            success=False,
                            msg=f"HTTP错误 {response.status}: {error_text[:100]}...",
                            code=response.status,
                        )

                    # 根据内容类型处理响应
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        return Result(True, data=await response.json())
                    elif "text/" in content_type:
                        return Result(True, data=await response.text())
                    else:
                        return Result(True, data=await response.read())

        except asyncio.TimeoutError:
            return Result(success=False, msg=f"请求超时 ({self.timeout}秒)", code=-1)
        except aiohttp.ClientConnectorError as e:
            return Result(success=False, msg=f"连接错误: {str(e)}", code=-2)
        except aiohttp.ClientError as e:
            return Result(success=False, msg=f"客户端错误: {str(e)}", code=-3)
        except Exception as e:
            log.exception(f"请求异常: {url}")
            return Result(success=False, msg=f"请求异常: {str(e)}", code=-4)

    @staticmethod
    async def get(
        url: str,
        params: Optional[Union[str, Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: seconds = seconds(10),
        proxy: Optional[str] = None,
        verify_ssl: bool = True,
    ) -> Result:
        """
        发送GET请求的便捷方法

        Args:
            url: 请求URL
            params: URL参数
            headers: 请求头
            timeout: 超时时间（秒）
            proxy: 代理服务器URL
            verify_ssl: 是否验证SSL证书

        Returns:
            Result对象，包含请求结果
        """
        request = ClientRequest(
            url=url,
            method="GET",
            params=params,
            headers=headers,
            timeout=timeout,
            proxy=proxy,
            verify_ssl=verify_ssl,
        )
        return format(await request.invoke())

    @staticmethod
    async def post(
        url: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: seconds = seconds(10),
        proxy: Optional[str] = None,
        verify_ssl: bool = True,
    ) -> Result:
        """
        发送POST请求的便捷方法

        Args:
            url: 请求URL
            data: 请求数据
            headers: 请求头
            timeout: 超时时间（秒）
            proxy: 代理服务器URL
            verify_ssl: 是否验证SSL证书

        Returns:
            Result对象，包含请求结果
        """
        request = ClientRequest(
            url=url,
            method="POST",
            data=data,
            headers=headers,
            timeout=timeout,
            proxy=proxy,
            verify_ssl=verify_ssl,
        )
        return format(await request.invoke())

    @staticmethod
    async def put(
        url: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: seconds = seconds(10),
        proxy: Optional[str] = None,
        verify_ssl: bool = True,
    ) -> Result:
        """
        发送PUT请求的便捷方法

        Args:
            url: 请求URL
            data: 请求数据
            headers: 请求头
            timeout: 超时时间（秒）
            proxy: 代理服务器URL
            verify_ssl: 是否验证SSL证书

        Returns:
            Result对象，包含请求结果
        """
        request = ClientRequest(
            url=url,
            method="PUT",
            data=data,
            headers=headers,
            timeout=timeout,
            proxy=proxy,
            verify_ssl=verify_ssl,
        )
        return format(await request.invoke())

    @staticmethod
    async def delete(
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: seconds = seconds(10),
        proxy: Optional[str] = None,
        verify_ssl: bool = True,
    ) -> Result:
        """
        发送DELETE请求的便捷方法

        Args:
            url: 请求URL
            headers: 请求头
            timeout: 超时时间（秒）
            proxy: 代理服务器URL
            verify_ssl: 是否验证SSL证书

        Returns:
            Result对象，包含请求结果
        """
        request = ClientRequest(
            url=url,
            method="DELETE",
            headers=headers,
            timeout=timeout,
            proxy=proxy,
            verify_ssl=verify_ssl,
        )
        return format(await request.invoke())


# 兼容旧版的方法


async def fetch(
    url: str,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Union[str, Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: seconds = seconds(10),
    proxy: Optional[str] = None,
    verify_ssl: bool = True,
) -> Result:
    method = "GET" if data is None else "POST"
    request = ClientRequest(
        url=url,
        method=method,
        data=data,
        params=params,
        headers=headers,
        timeout=timeout,
        proxy=proxy,
        verify_ssl=verify_ssl,
    )
    return format(await request.invoke())


async def query(
    url: str,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Union[str, Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: seconds = seconds(10),
    proxy: Optional[str] = None,
    verify_ssl: bool = True,
) -> Result:
    res = await fetch(url, data, params, headers, timeout, proxy, verify_ssl)
    return format(res)
