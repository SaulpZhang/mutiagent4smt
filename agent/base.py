from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from agent.llm_client import LLMClient


class BaseAgent(ABC):
    """Agent抽象基类，所有Agent需继承此类并实现run方法

    每个agent实例维护 conversation_history（用例级隔离），
    在用例内累积历史对话，让LLM拥有跨轮次记忆。
    """

    def __init__(self, name: str, system_prompt: str, llm_client: LLMClient) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.conversation_history: list = [SystemMessage(content=system_prompt)]

    async def _chat(self, user_message: str, json_output: bool = False) -> str:
        """LLM调用（自动累积对话历史 + 速率限制重试）

        每次调用将新消息追加到 conversation_history，
        后续调用携带完整历史，使LLM拥有用例内的跨轮次记忆。
        遇到速率限制自动 sleep 60s 重试。
        """
        current_messages = self.conversation_history + [HumanMessage(content=user_message)]
        max_attempts = self.llm_client.max_retries + 1

        for attempt in range(max_attempts):
            try:
                response = await self.llm_client.chat(
                    messages=current_messages,
                    json_output=json_output,
                )
                self.conversation_history.append(HumanMessage(content=user_message))
                self.conversation_history.append(AIMessage(content=response))
                return response
            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = "429" in error_str or "rate limit" in error_str or "tpm limit" in error_str
                if is_rate_limit and attempt < max_attempts - 1:
                    print(f"  速率限制，60s后重试 (第{attempt+1}/{max_attempts}次, agent={self.name})")
                    await asyncio.sleep(60)
                    continue
                raise

    @abstractmethod
    async def run(self, **kwargs) -> BaseModel:
        """执行Agent任务，返回结构化输出"""
        ...
