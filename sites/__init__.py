"""
站点适配器注册表
自动发现并注册所有站点适配器。
"""
from typing import Dict, Type, Optional
from sites.base import BaseSiteAdapter

# 注册表：站点名称 -> 适配器类
_registry: Dict[str, Type[BaseSiteAdapter]] = {}


def register(adapter_cls: Type[BaseSiteAdapter]):
    """注册站点适配器"""
    # 兼容两类适配器：
    # 1) site_name 非空：精确注册
    # 2) site_name 为空、通过 matches() 匹配多站点（如政采云系）：按类名占位注册，模糊匹配时逐个调用 matches()
    key = adapter_cls.site_name or adapter_cls.__name__
    _registry[key] = adapter_cls
    return adapter_cls


def get_adapter(site_name: str) -> Optional[Type[BaseSiteAdapter]]:
    """根据站点名称获取适配器类"""
    # 精确匹配
    if site_name in _registry:
        return _registry[site_name]
    # 模糊匹配
    for name, cls in _registry.items():
        if cls.matches(site_name):
            return cls
    return None


def list_adapters() -> list:
    """列出所有已注册的适配器"""
    return list(_registry.keys())


# 在这里导入并注册所有适配器
# from sites.example_site import ExampleSiteAdapter
# register(ExampleSiteAdapter)
from sites.zcy import ZcySiteAdapter
register(ZcySiteAdapter)
