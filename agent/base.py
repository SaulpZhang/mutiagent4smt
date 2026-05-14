from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from agent.llm_client import LLMClient


class BaseAgent(ABC):
    """Agent抽象基类，所有Agent需继承此类并实现run方法"""

    def __init__(self, name: str, system_prompt: str, llm_client: LLMClient) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.llm_client = llm_client

    @abstractmethod
    async def run(self, **kwargs) -> BaseModel:
        """执行Agent任务，返回结构化输出"""
        ...
