"""
浏览器工厂
统一接口创建不同引擎的浏览器实例，支持 Playwright / Camoufox 切换。
"""
import random
from typing import Optional, Any
from loguru import logger
from config.settings import settings


class BrowserFactory:
    """浏览器工厂，根据配置创建浏览器实例"""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    ]

    @staticmethod
    def create_playwright(
        headless: bool = True,
        proxy: Optional[dict] = None,
        session_name: Optional[str] = None,
        **kwargs
    ):
        """
        创建 Playwright 浏览器实例（带 stealth 增强）

        Args:
            headless: 是否无头模式
            proxy: 代理配置 {"server": "..."}，None 表示直连
            session_name: 会话名，用于持久化浏览器状态（cookies/localStorage），
                         状态文件存储在 data/browser_sessions/{session_name}.json
            **kwargs: 其他 Playwright launch 参数

        Returns:
            (playwright, browser, context) 三元组
        """
        import os
        import json
        from pathlib import Path
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        # 强制直连：清除所有代理相关的环境变量，防止 Chromium 拾取系统代理
        if not proxy:
            for key in list(os.environ.keys()):
                if any(k in key.upper() for k in ("PROXY",)):
                    os.environ.pop(key, None)
            os.environ["NO_PROXY"] = "*"

        pw = sync_playwright().start()

        launch_args = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=TranslateUI",
                "--disable-ipc-flooding-protection",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
            **kwargs,
        }

        if proxy:
            launch_args["proxy"] = proxy
        else:
            # 禁止 Chromium 读取 Windows 系统代理 + 使用临时数据目录避免缓存残留
            launch_args["args"].extend([
                "--no-proxy-server",
            ])

        browser = pw.chromium.launch(**launch_args)

        w = random.randint(1840, 2000)
        h = random.randint(1000, 1160)

        context_options = {
            "viewport": {"width": w, "height": h},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "user_agent": random.choice(BrowserFactory.USER_AGENTS),
        }

        # 加载已保存的会话状态
        if session_name:
            session_dir = Path("data/browser_sessions")
            session_dir.mkdir(parents=True, exist_ok=True)
            session_path = session_dir / f"{session_name}.json"
            if session_path.exists():
                try:
                    context_options["storage_state"] = str(session_path.resolve())
                    logger.info(f"已加载会话状态: {session_name} ({session_path})")
                except Exception as e:
                    logger.warning(f"加载会话状态失败: {e}")

        if proxy:
            context_options["proxy"] = proxy

        context = browser.new_context(**context_options)

        # 应用 stealth 补丁到 context（所有新页面自动 stealth）
        try:
            Stealth().apply_stealth_sync(context)
            logger.debug("Stealth 已启用")
        except Exception as e:
            logger.warning(f"Stealth 启用失败（继续运行）: {e}")

        logger.info("Playwright 浏览器已启动 (Chromium + Stealth)")
        return pw, browser, context

    @staticmethod
    def save_session(context, session_name: str) -> bool:
        """
        保存浏览器会话状态到文件

        Args:
            context: Playwright browser context
            session_name: 会话名

        Returns:
            是否保存成功
        """
        import json
        from pathlib import Path

        try:
            session_dir = Path("data/browser_sessions")
            session_dir.mkdir(parents=True, exist_ok=True)
            session_path = session_dir / f"{session_name}.json"
            state = context.storage_state()

            # 深拷贝确保可序列化
            state_str = json.dumps(state, ensure_ascii=False, default=str)
            session_path.write_text(state_str, encoding="utf-8")
            logger.info(f"会话状态已保存: {session_name} ({session_path})")
            return True
        except Exception as e:
            logger.error(f"保存会话状态失败: {e}")
            return False

    @staticmethod
    def create_camoufox(
        headless: bool = True,
        proxy: Optional[dict] = None,
        **kwargs
    ):
        """
        创建 Camoufox 浏览器实例（高级反检测）

        Args:
            headless: 是否无头模式
            proxy: 代理配置 {"server": "..."}
            **kwargs: 其他参数

        Returns:
            (camoufox, browser, page) - 注意此处无 context 层
        """
        from camoufox.sync_api import Camoufox

        launch_args = {
            "headless": headless,
            "geoip": True,
            "user_agent": random.choice(BrowserFactory.USER_AGENTS),
            **kwargs,
        }

        if proxy:
            launch_args["proxy"] = proxy

        browser = Camoufox(**launch_args)
        # Camoufox 已内置 stealth，无需额外 patch
        logger.info("Camoufox 浏览器已启动 (Firefox + C++ 级反检测)")
        return None, browser, None  # 返回 None 占位保持接口统一

    @staticmethod
    def create(
        engine: Optional[str] = None,
        headless: bool = True,
        proxy_url: Optional[str] = None,
    ) -> tuple:
        """
        统一创建浏览器实例

        Args:
            engine: 引擎类型 (playwright | camoufox)，默认用 settings
            headless: 是否无头模式
            proxy_url: 代理地址 (http://user:pass@host:port)

        Returns:
            (driver, browser, context_or_page) 三元组
              - Playwright: (playwright, browser, context)
              - Camoufox: (None, browser, None)
        """
        engine = engine or settings.BROWSER_ENGINE

        proxy = None
        if proxy_url:
            proxy = {"server": proxy_url}
        elif settings.HTTP_PROXY:
            proxy = {"server": settings.HTTP_PROXY}

        if engine == "camoufox":
            return BrowserFactory.create_camoufox(headless=headless, proxy=proxy)
        else:
            return BrowserFactory.create_playwright(headless=headless, proxy=proxy)
