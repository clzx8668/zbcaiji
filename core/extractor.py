"""
内容提取器
支持 LLM 智能提取和传统 CSS/XPath 提取（BS4），自动降级。
"""
import json
from typing import Optional
from loguru import logger
from config.settings import settings


class Extractor:
    """内容提取器，优先使用 LLM 直接分析 HTML，降级到 BS4"""

    # 默认提取指令
    DEFAULT_LIST_INSTRUCTION = """
你是一个网页数据分析助手。请从以下网页文本中提取招标/中标公告的搜索结果列表。
返回 JSON 数组，每个元素包含：
- title: 公告标题
- url: 详情页链接（完整 URL，如果是相对路径请拼接域名）
只返回 JSON 数组，不要其他内容。如果没有找到任何公告，返回空数组 []。"""

    DEFAULT_DETAIL_INSTRUCTION = """
你是一个网页数据分析助手。请从以下网页文本中提取一份招标/中标公告的详细信息。
返回一个 JSON 对象，包含以下字段：
- title: 公告标题
- publish_date: 发布日期（YYYY-MM-DD 格式）
- amount: 预算金额或中标金额（如有，保留原始格式）
- source_org: 采购单位或招标代理机构
- content_summary: 公告内容摘要（取前 500 字）
只返回 JSON 对象，不要其他内容。"""

    def __init__(self):
        pass

    def _dump_debug_html(self, html: str, url: str = ""):
        """保存失败的 HTML 到调试目录用于排查"""
        from pathlib import Path
        from hashlib import md5
        from datetime import datetime

        debug_dir = Path("data/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        url_hash = md5(url.encode()).hexdigest()[:8] if url else "unknown"
        html_path = debug_dir / f"extract_fail_{ts}_{url_hash}.html"
        html_path.write_text(html, encoding="utf-8", errors="replace")
        logger.warning(f"提取失败的 HTML 已保存到: {html_path}")

    def extract_from_html(self, html: str, url: str = "",
                          instruction: str = "") -> list[dict]:
        """
        使用 LLM 从 HTML 中提取信息。

        Args:
            html: 页面 HTML 内容
            url: 页面 URL（用于 LLM 上下文）
            instruction: 自定义提取指令（为空则根据页面类型自动选择）

        Returns:
            提取结果列表
        """
        if not settings.llm_enabled:
            logger.debug("LLM 未配置，跳过 AI 提取")
            return []

        if not instruction:
            instruction = self.DEFAULT_LIST_INSTRUCTION

        try:
            from core.llm_client import get_llm_client
            from bs4 import BeautifulSoup

            # 提取纯文本
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text(separator="\n")
            # 清理多余空行
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)

            if not text:
                logger.debug("页面无文本内容")
                return []

            # 截取内容（优先取主体区域文本）
            text_snippet = text[:20000]
            if len(text_snippet) < 100:
                logger.debug("页面文本过短（可能为 SPA 页面）")
                # 尝试从 body 直接取 innerText
                body = soup.find("body")
                if body:
                    body_text = body.get_text(separator="\n")
                    body_lines = [line.strip() for line in body_text.split("\n") if line.strip()]
                    text_snippet = "\n".join(body_lines)[:20000]

            # 构建 prompt
            prompt = f"页面 URL: {url}\n\n页面文本:\n{text_snippet}"

            llm = get_llm_client()
            result = llm.chat_completion_json(
                prompt=prompt,
                system_message=instruction,
            )

            if isinstance(result, list):
                if result:
                    logger.info(f"AI 提取到 {len(result)} 条记录")
                else:
                    logger.info("AI 提取到 0 条记录")
                    self._dump_debug_html(html, url)
                return result
            elif isinstance(result, dict):
                # 详情页提取返回单对象
                if result.get("title"):
                    logger.info(f"AI 提取到详情: {result.get('title', '')[:30]}")
                    return [result]
                self._dump_debug_html(html, url)
                return []
            else:
                logger.warning(f"AI 返回非预期格式: {type(result)}")
                self._dump_debug_html(html, url)
                return []

        except ImportError:
            logger.warning("LLM 客户端未安装")
            return []
        except Exception as e:
            logger.warning(f"AI 提取失败: {e}")
            return []

    def extract_with_css(self, html: str) -> list[dict]:
        """
        使用 BeautifulSoup + CSS 选择器提取（降级方案）
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        results = []

        selectors = [
            "table tbody tr",
            ".result-list li",
            ".list-item",
            ".search-result-item",
            "ul.list li",
            ".article-list li",
            "tr[data-id]",
        ]

        for selector in selectors:
            items = soup.select(selector)
            if items:
                logger.debug(f"CSS 选择器 '{selector}' 匹配到 {len(items)} 条记录")
                for item in items:
                    link = item.select_one("a")
                    title = link.get_text(strip=True) if link else ""
                    url = link.get("href", "") if link else ""
                    date_el = item.select_one("[class*='date'], [class*='time'], span.time")
                    date_text = date_el.get_text(strip=True) if date_el else ""

                    if title:
                        results.append({
                            "title": title,
                            "url": url,
                            "publish_date": date_text,
                            "amount": "",
                            "source_org": "",
                            "content_summary": "",
                        })
                break

        return results

    def extract(self, html: str = "", url: str = "",
                instruction: str = "") -> list[dict]:
        """
        统一提取入口：先 CSS，后 LLM。

        Args:
            html: 页面 HTML
            url: 页面 URL（LLM 模式用）
            instruction: 自定义提取指令

        Returns:
            结构化提取结果
        """
        if not html:
            logger.warning("无 HTML 内容")
            return []

        # 1. 先尝试 CSS 提取
        results = self.extract_with_css(html)
        if results:
            logger.info(f"CSS 提取到 {len(results)} 条记录")
            return results

        # 2. CSS 未匹配，尝试 LLM
        if settings.llm_enabled:
            logger.info("CSS 未匹配，降级到 AI 提取模式")
            results = self.extract_from_html(html, url, instruction)
            if results:
                return results

        logger.debug("无法提取任何内容")
        # Debug：保存失败的 HTML 到调试目录
        self._dump_debug_html(html, url)
        return []
