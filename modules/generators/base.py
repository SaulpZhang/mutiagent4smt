from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum
from typing import Any

from core.schemas import ConstraintsList, SMTLibCode


class GenMode(IntEnum):
    """SMT代码生成模式

    模式说明:
        PURE_LLM = 0
            纯LLM路径：完全由LLM生成SMT代码，不使用任何程序化生成器。
            适用于测试LLM自身的代码生成能力，或作为baseline对比。

        GENERATOR_LLM = 1
            Generator + LLM回退：优先匹配程序化生成器（GeneratorRegistry），
            匹配成功则直接生成（无LLM调用），匹配失败或fallback条件触发时走LLM。
            当前默认行为，覆盖125/126用例。

        LLM_MANAGED = 2
            LLM-Managed Generator：通过LLM分发将指令与用户定义的生成器匹配。
            生成器以 spec.json + generator.py 形式存储在 user_defined/ 目录，
            由LLM根据验证指令判断是否使用生成器（无需关键词匹配）。
            无匹配时回退到纯LLM生成。

    扩展方式（后续新增）:
        3 = RAG增强生成: 从用例库检索相似case的SMT代码作为few-shot示例
        4 = Grammar-guided: 基于SMT语法模板的约束引导生成
        ...
    """

    PURE_LLM = 0
    GENERATOR_LLM = 1
    LLM_MANAGED = 2


class SMTGenerator(ABC):
    """SMT代码生成器基类

    继承者需实现：
    - name / description / examples (类属性)
    - can_handle(instruction)   — 判断能否处理某类指令
    - generate(config, constraints) — 生成 SMT-LIB V2 代码
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """生成器唯一标识"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """描述该生成器处理哪类验证"""
        ...

    @property
    def examples(self) -> list[str]:
        """可匹配的示例指令（用于 can_handle 关键词匹配）"""
        return []

    @abstractmethod
    def can_handle(self, instruction: str) -> bool:
        """判断此生成器能否处理给定的验证指令"""
        ...

    @abstractmethod
    def generate(self, config: dict, constraints: ConstraintsList) -> SMTLibCode:
        """根据 IAM 配置和约束列表生成 SMT-LIB V2 代码"""
        ...

    def __repr__(self) -> str:
        return f"<SMTGenerator:{self.name}>"


class GeneratorRegistry:
    """生成器注册中心：管理所有可用的 SMTGenerator"""

    def __init__(self) -> None:
        self._generators: list[SMTGenerator] = []

    def register(self, generator: SMTGenerator) -> None:
        """注册一个生成器"""
        # 不重复注册同名生成器
        for g in self._generators:
            if g.name == generator.name:
                return
        self._generators.append(generator)

    def find(self, instruction: str) -> SMTGenerator | None:
        """根据验证指令找到最匹配的生成器（best-effort）"""
        for generator in self._generators:
            if generator.can_handle(instruction):
                return generator
        return None

    def list_generators(self) -> list[SMTGenerator]:
        """列出所有已注册的生成器"""
        return list(self._generators)
