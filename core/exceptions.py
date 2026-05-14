class CodeVError(Exception):
    """系统基础异常"""
    pass


class ConfigError(CodeVError):
    """配置相关异常"""
    pass


class LLMError(CodeVError):
    """LLM调用相关异常"""
    pass


class LLMRetryExhaustedError(LLMError):
    """LLM重试耗尽异常"""
    pass


class LLMTimeoutError(LLMError):
    """LLM调用超时异常"""
    pass


class SchemaError(CodeVError):
    """数据验证异常"""
    pass


class PipelineError(CodeVError):
    """流水线执行异常"""
    pass


class ModuleError(CodeVError):
    """模块执行异常"""
    pass


class SyntaxCheckError(ModuleError):
    """语法检查异常"""
    pass


class Z3ExecutionError(ModuleError):
    """Z3执行异常"""
    pass


class ExperimentError(CodeVError):
    """实验记录异常"""
    pass
