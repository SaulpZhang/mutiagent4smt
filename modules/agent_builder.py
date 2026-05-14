from __future__ import annotations

from agent.llm_client import LLMClient
from modules.agents.intent_agent import IntentUnderstandingAgent
from modules.agents.code_gen_agent import CodeGenerationAgent
from modules.agents.eval_agent import EvaluationAgent


class AgentBuilder:
    """Agent装配器：创建并配置所有三个Agent"""

    SYSTEM_PROMPTS = {
        "intent": (
            "你是一个IAM策略分析专家。你的任务是根据用户的验证指令和IAM配置，"
            "生成结构化的约束列表。请以JSON格式输出，包含constraints数组，"
            "每个约束包含id、description、category字段。"
        ),
        "code_gen": (
            "你是一个SMT-LIB V2代码生成专家。你的任务是根据验证指令、IAM配置和约束列表，"
            "生成可执行的SMT-LIB V2代码。代码必须使用SMT-LIB V2语法，"
            "包含变量定义、断言和check-sat命令。"
        ),
        "eval": (
            "你是一个SMT-LIB V2代码评估专家。你的任务是根据约束列表逐项评估生成的代码。"
            "请以JSON格式输出，包含items数组（每项含constraint_id、status、reason）"
            "和all_satisfied字段。保持评估客观中立。"
        ),
        "syntax_fix": (
            "你是一个SMT-LIB V2代码调试专家。你的任务是修复SMT-LIB V2代码中的语法错误。"
            "只修复语法问题，不改变代码逻辑。输出完整的修正后的代码。"
        ),
        "code_mod": (
            "你是一个SMT-LIB V2代码优化专家。你的任务是根据评估反馈修改SMT-LIB V2代码，"
            "使其满足所有约束要求。不要破坏已满足的部分。输出完整的修改后的代码。"
        ),
    }

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def build_intent_agent(self) -> IntentUnderstandingAgent:
        return IntentUnderstandingAgent(
            name="intent_understanding",
            system_prompt=self.SYSTEM_PROMPTS["intent"],
            llm_client=self.llm_client,
        )

    def build_code_gen_agent(self) -> CodeGenerationAgent:
        return CodeGenerationAgent(
            name="code_generation",
            system_prompt=self.SYSTEM_PROMPTS["code_gen"],
            llm_client=self.llm_client,
        )

    def build_eval_agent(self) -> EvaluationAgent:
        return EvaluationAgent(
            name="evaluation",
            system_prompt=self.SYSTEM_PROMPTS["eval"],
            llm_client=self.llm_client,
        )

    def build_syntax_fix_agent(self) -> CodeGenerationAgent:
        """语法修正使用CodeGenerationAgent，但使用专门的system prompt"""
        return CodeGenerationAgent(
            name="syntax_fix",
            system_prompt=self.SYSTEM_PROMPTS["syntax_fix"],
            llm_client=self.llm_client,
        )

    def build_code_mod_agent(self) -> CodeGenerationAgent:
        """语义修正使用CodeGenerationAgent，但使用专门的system prompt"""
        return CodeGenerationAgent(
            name="code_modification",
            system_prompt=self.SYSTEM_PROMPTS["code_mod"],
            llm_client=self.llm_client,
        )
