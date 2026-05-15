from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings
from core.exceptions import LLMError


class LLMClient:
    """LLM API客户端，封装LangChain的ChatOpenAI（兼容DeepSeek API）"""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        model_name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_timeout: int | None = None,
        max_retries: int | None = None,
        reasoning_effort: str | None = None,
        thinking: bool | None = None,
    ) -> None:
        self.api_key = api_key or settings.api_key
        self.api_url = api_url or settings.api_url
        self.model_name = model_name or settings.common_model or settings.model_name
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.request_timeout = request_timeout or settings.llm_request_timeout
        self.max_retries = max_retries or settings.llm_max_retries
        self.reasoning_effort = reasoning_effort if reasoning_effort is not None else settings.reasoning_effort
        self.thinking = thinking if thinking is not None else settings.thinking

        if not self.api_key:
            raise LLMError("API_KEY未设置，请检查.env文件")
        if not self.api_url:
            raise LLMError("API_URL未设置，请检查.env文件")

    def _build_model(self, json_output: bool = False) -> ChatOpenAI:
        kwargs: dict[str, Any] = dict(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.api_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.request_timeout,
            max_retries=self.max_retries,
        )

        model_kwargs: dict[str, Any] = {}
        if json_output:
            model_kwargs["response_format"] = {"type": "json_object"}

        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs

        # DeepSeek 推理参数（顶层参数，避免 LangChain 警告）
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        return ChatOpenAI(**kwargs)

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        json_output: bool = False,
    ) -> str:
        """发送对话请求并返回响应文本"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        model = self._build_model(json_output=json_output)
        request_start = time.perf_counter()
        try:
            response = await model.ainvoke(
                messages,
                temperature=temperature if temperature is not None else self.temperature,
            )
            elapsed_ms = (time.perf_counter() - request_start) * 1000
            content = response.content if hasattr(response, "content") else str(response)
            result = content.strip()

            if json_output and result:
                # 验证JSON可解析
                try:
                    json.loads(result)
                except json.JSONDecodeError as e:
                    raise LLMError(f"LLM未返回合法JSON: {e}\n原始响应: {result[:200]}") from e

            return result
        except Exception as e:
            elapsed_ms = (time.perf_counter() - request_start) * 1000
            raise LLMError(f"LLM调用失败（耗时{elapsed_ms:.0f}ms）: {e}") from e
