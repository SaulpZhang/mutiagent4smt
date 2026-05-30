from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings
from core.exceptions import LLMError


class LLMClient:
    """LLM API客户端，封装LangChain的ChatOpenAI（兼容DeepSeek API）

    每个LLM调用受总超时保护（asyncio.wait_for + httpx严格超时双层保护）。
    复用ChatOpenAI实例以避免连接泄漏。
    """

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

        # 缓存ChatOpenAI实例，按json_output分别缓存
        self._model_normal: ChatOpenAI | None = None
        self._model_json: ChatOpenAI | None = None

    # 类级共享httpx客户端，避免每个LLMClient实例独立创建连接池泄漏信号量
    _shared_async_client: httpx.AsyncClient | None = None

    @classmethod
    def _get_shared_async_client(cls) -> httpx.AsyncClient:
        """获取类级共享的httpx客户端（所有实例共用一个连接池）"""
        if cls._shared_async_client is None:
            cls._shared_async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=15.0,
                    read=45.0,
                    write=30.0,
                    pool=10.0,
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=2,
                    max_connections=4,
                ),
            )
        return cls._shared_async_client

    @classmethod
    async def close_all(cls) -> None:
        """释放共享httpx客户端连接（实验结束时调用）"""
        if cls._shared_async_client is not None:
            await cls._shared_async_client.aclose()
            cls._shared_async_client = None

    def _get_model(self, json_output: bool = False) -> ChatOpenAI:
        """获取或创建缓存的ChatOpenAI实例"""
        cache_attr = "_model_json" if json_output else "_model_normal"
        cached = getattr(self, cache_attr)
        if cached is not None:
            return cached

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

        # DeepSeek 推理参数
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        elif self.thinking is not None and not self.thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        # 传递共享httpx异步客户端（类级复用，避免连接泄漏）
        kwargs["http_async_client"] = self._get_shared_async_client()

        model = ChatOpenAI(**kwargs)
        setattr(self, cache_attr, model)
        return model

    async def chat(
        self,
        system_prompt: str | None = None,
        user_message: str | None = None,
        messages: list | None = None,
        temperature: float | None = None,
        json_output: bool = False,
    ) -> str:
        """发送对话请求并返回响应文本（含限流自动重试）

        Args:
            system_prompt: 系统提示词（与 user_message 配对使用）
            user_message: 用户消息（与 system_prompt 配对使用）
            messages: 完整消息列表（替代 system_prompt+user_message）
            temperature: 温度参数
            json_output: 是否要求 JSON 输出

        必须提供 system_prompt+user_message 或 messages 之一。
        """
        if messages is not None:
            final_messages = messages
        else:
            if system_prompt is None or user_message is None:
                raise ValueError("必须提供 system_prompt+user_message 或 messages")
            final_messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]

        model = self._get_model(json_output=json_output)

        max_attempts = self.max_retries + 1

        last_error: Exception | None = None
        elapsed_ms: float = 0.0
        for attempt in range(max_attempts):
            request_start = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    model.ainvoke(
                        final_messages,
                        temperature=temperature if temperature is not None else self.temperature,
                    ),
                    timeout=self.request_timeout,
                )
                elapsed_ms = (time.perf_counter() - request_start) * 1000
                content = response.content if hasattr(response, "content") else str(response)
                result = content.strip()

                if json_output and result:
                    try:
                        json.loads(result)
                    except json.JSONDecodeError as e:
                        raise LLMError(f"LLM未返回合法JSON: {e}\n原始响应: {result}") from e

                return result
            except Exception as e:
                elapsed_ms = (time.perf_counter() - request_start) * 1000
                last_error = e
                if attempt < max_attempts - 1:
                    err_preview = str(e)[:60]
                    print(f"  LLM调用失败，60s后重试 (第{attempt+1}/{max_attempts}次): {err_preview}")
                    await asyncio.sleep(60)
                    continue
                break

        raise LLMError(f"LLM调用失败（耗时{elapsed_ms:.0f}ms）: {last_error}") from last_error
