"""
LLM 通用客户端
支持 DeepSeek / OpenAI 兼容的 API 调用，用于搜索分析和内容提取。
"""
import json
from typing import Optional
from loguru import logger
from config.settings import settings


class LLMClient:
    """LLM 调用客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 2,
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.api_base = (api_base or settings.LLM_API_BASE).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat_completion(
        self,
        prompt: str,
        system_message: str = "",
        temperature: float = 0.1,
    ) -> str:
        """
        调用 LLM chat completion API。

        Args:
            prompt: 用户消息
            system_message: 系统消息
            temperature: 温度参数

        Returns:
            LLM 响应文本

        Raises:
            RuntimeError: API 调用失败
        """
        if not self.enabled:
            raise RuntimeError("LLM_API_KEY 未配置")

        import httpx

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug(f"LLM 响应 ({len(content)} chars)")
                return content
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"LLM 调用超时 (尝试 {attempt + 1}/{self.max_retries + 1})")
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}/{self.max_retries + 1}): {e}")

        raise RuntimeError(f"LLM 调用失败（已重试 {self.max_retries} 次）: {last_error}")

    def chat_completion_json(
        self,
        prompt: str,
        system_message: str = "",
        temperature: float = 0.1,
    ) -> dict:
        """
        调用 LLM 并解析 JSON 响应。

        Args:
            prompt: 用户消息
            system_message: 系统消息
            temperature: 温度参数

        Returns:
            解析后的 JSON dict

        Raises:
            RuntimeError: API 调用失败或 JSON 解析失败
        """
        raw = self.chat_completion(prompt, system_message, temperature)

        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        json_str = raw.strip()
        if json_str.startswith("```"):
            # 移除 markdown 代码块标记
            lines = json_str.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            json_str = "\n".join(lines)

        # 尝试找到 JSON 对象的起止位置
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start != -1 and end != -1:
            json_str = json_str[start:end + 1]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 返回非 JSON 内容: {raw[:200]}")
            raise RuntimeError(f"无法解析 LLM 响应为 JSON: {e}")


# 全局 LLM 客户端实例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取全局 LLM 客户端实例（懒加载）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
