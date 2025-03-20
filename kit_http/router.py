import inspect
import re

from aiohttp import web


class Router(web.UrlDispatcher):
    """自定义路由分发器

    基于方法命名约定自动注册路由：
    - indexGet: 处理根路径的GET请求
    - xxxGet: 处理/xxx路径的GET请求
    - xxxPost: 处理/xxx路径的POST请求
    - xxxPut: 处理/xxx路径的PUT请求
    - xxxDelete: 处理/xxx路径的DELETE请求
    - xxxAction: 处理/xxx路径的GET和POST请求
    - xxxSocket: 处理/xxx路径的WebSocket连接

    下划线会被转换为路径分隔符，例如：
    - user_infoGet: 处理/user/info路径的GET请求
    """

    def __init__(self, cls, prefix: str = "") -> None:
        """初始化路由分发器

        Args:
            cls: 包含处理方法的类实例
            prefix: 路由前缀，会添加到所有路由路径前面
        """
        super().__init__()
        self.prefix = prefix.rstrip("/")  # 确保前缀不以斜杠结尾
        self._register_routes(cls)

    def _register_routes(self, cls) -> None:
        """注册所有符合命名约定的路由

        Args:
            cls: 包含处理方法的类实例
        """
        # 注册首页路由
        if hasattr(cls, "indexGet"):
            # 同时注册带斜杠和不带斜杠的根路径
            root_path_with_slash = f"{self.prefix}/" if self.prefix else "/"
            root_path_without_slash = self.prefix if self.prefix else ""
            root_path_without_index = (
                f"{self.prefix}/index" if self.prefix else "/index"
            )

            self.add_route("GET", root_path_with_slash, cls.indexGet)

            # 为空路径添加路由（不带尾部斜杠）
            self.add_route("GET", root_path_without_slash, cls.indexGet)

            # 为index添加路由
            self.add_route("GET", root_path_without_index, cls.indexGet)

        self.add_route("GET", "/favicon.ico", cls.favicon_icoGet)

        # 定义HTTP方法与后缀的映射
        method_suffixes = {
            "GET": ["Get", "Socket"],
            "POST": ["Post"],
            "PUT": ["Put"],
            "DELETE": ["Delete"],
            "ACTION": ["Action"],  # 特殊情况，会注册为GET和POST
        }

        # 编译正则表达式，匹配所有后缀
        all_suffixes = [
            suffix for suffixes in method_suffixes.values() for suffix in suffixes
        ]
        regex = re.compile(f"({'|'.join(all_suffixes)})$")

        # 遍历所有异步方法
        for name, method in inspect.getmembers(
            cls, predicate=inspect.iscoroutinefunction
        ):
            if regex.search(name) is None or name == "indexGet":  # 跳过已处理的indexGet
                continue

            # 提取路径并替换下划线为斜杠
            path_name = regex.sub("", name)
            path = f"{self.prefix}/{path_name}".replace("_", "/")

            # 根据后缀注册不同的HTTP方法
            for http_method, suffixes in method_suffixes.items():
                for suffix in suffixes:
                    if name.endswith(suffix):
                        if http_method == "ACTION":
                            self.add_route("GET", path, method)
                            self.add_route("POST", path, method)
                        else:
                            self.add_route(http_method, path, method)

    def add_static_routes(self, prefix: str, path: str) -> None:
        """添加静态文件路由

        Args:
            prefix: 静态文件URL前缀
            path: 静态文件目录路径
        """
        self.add_static(prefix, path)
