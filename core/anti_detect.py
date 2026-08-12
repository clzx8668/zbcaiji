"""
反检测行为模拟
提供类人操作模拟与验证码检测，降低 Playwright 爬虫被识别的风险。
"""
import random
import time
from loguru import logger


def random_delay(min_s: float = 0.5, max_s: float = 3.0):
    """
    随机延迟，模拟人类操作间隔

    Args:
        min_s: 最小延迟秒数
        max_s: 最大延迟秒数
    """
    delay = random.uniform(min_s, max_s)
    logger.debug(f"随机延迟 {delay:.2f}s")
    time.sleep(delay)


def human_type(page, selector: str, text: str, min_delay: int = 50, max_delay: int = 200):
    """
    模拟人类输入：逐字符键入，带随机间隔

    Args:
        page: Playwright Page 对象
        selector: 目标元素选择器
        text: 要输入的文本
        min_delay: 字符间最小延迟(ms)
        max_delay: 字符间最大延迟(ms)
    """
    locator = page.locator(selector).first
    locator.click()
    delay_ms = random.randint(min_delay, max_delay)
    logger.debug(f"模拟输入 selector={selector}, text={text[:20]}..., delay={delay_ms}ms")
    page.keyboard.type(text, delay=delay_ms)


def human_mouse_move(page):
    """
    模拟人类鼠标移动：将鼠标移动到页面上的 2-4 个随机位置

    Args:
        page: Playwright Page 对象
    """
    vp = page.viewport_size or {"width": 1920, "height": 1080}
    w, h = vp["width"], vp["height"]
    moves = random.randint(2, 4)
    positions = [(random.randint(0, w), random.randint(0, h)) for _ in range(moves)]
    logger.debug(f"模拟鼠标移动 {moves} 次, viewport={w}x{h}, 目标={positions}")
    for x, y in positions:
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.05, 0.2))


def random_scroll(page):
    """
    随机滚动页面（主要向下），模拟人类浏览行为

    Args:
        page: Playwright Page 对象
    """
    direction = random.choice([1, 1, 1, -1])  # 3/4 概率向下
    amount = random.randint(200, 800)
    delta = direction * amount
    logger.debug(f"随机滚动 delta={delta}px (direction={'down' if direction > 0 else 'up'})")
    page.evaluate(f"window.scrollBy({{top: {delta}, behavior: 'smooth'}})")
    time.sleep(random.uniform(0.5, 1.5))


def detect_captcha(page) -> bool:
    """
    检测页面是否包含验证码

    通过页面文本内容和特定选择器判断当前页面是否触发了验证码。

    Args:
        page: Playwright Page 对象

    Returns:
        True 表示检测到验证码，False 表示未检测到
    """
    content = page.content()

    # 1. 关键词检测
    keywords = ["验证码", "captcha", "滑块", "slider", "verify", "点选", "拼图"]
    content_lower = content.lower()
    found_keywords = []
    for kw in keywords:
        if kw.lower() in content_lower:
            found_keywords.append(kw)

    # 2. 选择器检测
    selectors = [
        '[class*="captcha"]',
        '[class*="verify"]',
        '[id*="captcha"]',
        'iframe[src*="captcha"]',
        '.geetest',
        '#nc_1_n1z',
    ]
    found_selectors = []
    for sel in selectors:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                found_selectors.append(sel)
        except Exception:
            pass

    detected = found_keywords or found_selectors
    if detected:
        parts = []
        if found_keywords:
            parts.append(f"关键词: {found_keywords}")
        if found_selectors:
            parts.append(f"选择器: {found_selectors}")
        logger.warning(f"检测到验证码 — {', '.join(parts)}")

    return bool(detected)


# ── 自动安全验证检测与等待 ──

# 自动验证页面特征（JS 挑战、semLogin、Cloudflare Turnstile 等）
AUTO_VERIFY_PATTERNS = [
    # semLogin / Security Layer 验证
    ("sl-challenge-server", "cookie"),
    ("semLogin", "url"),
    ("checkSemLoginStatus", "url"),
    # Cloudflare / 通用 JS 挑战
    ("challenge-platform", "class"),
    ("challenge-running", "class"),
    ("spacer-challenge", "id"),
    ("turnstile", "src"),
    # 通用安全验证元素
    ("请稍候", "text"),
    ("安全检测", "text"),
    ("安全检查", "text"),
    ("正在验证", "text"),
]

# 验证完成后出现的正常页面特征
NORMAL_PAGE_SELECTORS = [
    "table tbody tr",
    "ul[class*='result'] li",
    ".result-list",
    ".list-item",
    ".search-result",
    "[class*='srch-result']",
]


def detect_auto_verify(page) -> bool:
    """
    检测页面是否处于自动安全验证状态（如 semLogin、JS 挑战等会自动完成的验证）。
    与 detect_captcha 不同，这类验证无需手动干预，等待即可。

    Returns:
        True 表示当前页面正在自动验证中
    """
    try:
        url = page.url.lower()
        html = page.content().lower()

        for pattern, ptype in AUTO_VERIFY_PATTERNS:
            if ptype == "url" and pattern.lower() in url:
                logger.info(f"检测到自动安全验证（URL 特征）: {pattern}")
                return True
            if ptype == "text" and pattern in html:
                logger.info(f"检测到自动安全验证（文本特征）: {pattern}")
                return True
            if ptype in ("class", "id", "src"):
                try:
                    if page.locator(f'[class*="{pattern}"], [id*="{pattern}"], [src*="{pattern}"]').count() > 0:
                        logger.info(f"检测到自动安全验证（元素特征）: {pattern}")
                        return True
                except Exception:
                    pass

        # Cookie 检测
        if ptype == "cookie":
            for pattern, _ in [(p, t) for p, t in AUTO_VERIFY_PATTERNS if t == "cookie"]:
                try:
                    cookies = page.context.cookies()
                    for c in cookies:
                        if pattern in c.get("name", "").lower():
                            logger.info(f"检测到自动安全验证（Cookie 特征）: {pattern}")
                            return True
                except Exception:
                    pass

    except Exception as e:
        logger.debug(f"自动验证检测出错: {e}")

    return False


def wait_for_auto_verify(page, timeout: int = 30) -> bool:
    """
    等待自动安全验证完成。策略：
    1. 等待验证容器消失
    2. 等待正常页面元素出现
    3. 兜底：等待固定时间

    Returns:
        True 表示验证已完成，False 表示超时
    """
    logger.info("正在等待自动安全验证完成...")
    start = time.time()

    # Strategy 1: 等待正常内容出现（结果表格 / 列表）
    for sel in NORMAL_PAGE_SELECTORS:
        try:
            page.wait_for_selector(sel, timeout=min(10000, (timeout * 1000) // 2))
            elapsed = time.time() - start
            logger.info(f"自动验证已完成（检测到正常内容: {sel}），耗时 {elapsed:.1f}s")
            time.sleep(1)  # 额外等 1s 确保渲染完成
            return True
        except Exception:
            continue

    # Strategy 2: 等待 verify/challenge 相关元素消失
    for sel in [
        '[class*="challenge"]',
        '[class*="verify"]',
        '[id*="challenge"]',
        '[id*="verify"]',
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0:
                logger.info(f"检测到验证元素 {sel}，等待消失...")
                el.first.wait_for(state="detached", timeout=timeout * 1000)
                elapsed = time.time() - start
                logger.info(f"验证元素已消失，耗时 {elapsed:.1f}s")
                time.sleep(2)
                return True
        except Exception:
            pass

    # Strategy 3: 等待固定时间（兜底）
    remaining = timeout - (time.time() - start)
    if remaining > 0:
        logger.info(f"无明显特征，等待 {remaining:.0f}s...")
        time.sleep(remaining)
        return True

    logger.warning(f"自动验证等待超时（{timeout}s）")
    return False
