from __future__ import annotations

from agent.base import BaseAgent
from agent.llm_client import LLMClient


class AgentFactory:
    """Agent工厂，根据配置创建不同的Agent实例"""

    @staticmethod
    def create_agent(
        name: str,
        system_prompt: str,
        llm_client: LLMClient | None = None,
    ) -> type[BaseAgent]:
        """创建指定类型的Agent类（返回类本身，实例化时需调用）"""
        raise NotImplementedError("AgentFactory会在具体Agent实现后提供")

    @staticmethod
    def build_llm_client(
        model_name: str | None = None,
        temperature: float | None = None,
    ) -> LLMClient:
        """便捷方法：创建LLM客户端"""
        return LLMClient(
            model_name=model_name,
            temperature=temperature,
        )
