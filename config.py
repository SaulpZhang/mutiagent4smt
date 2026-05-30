from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API (全局默认)
    api_key: str = ""
    api_url: str = ""
    model_name: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096
    llm_request_timeout: int = 300
    llm_max_retries: int = 3

    # 各Agent独立模型配置（如不设置则使用 common_model）
    agent_1_model: str = ""   # Agent 1 意图理解
    agent_2_model: str = ""   # Agent 2 代码生成
    agent_3_model: str = ""   # Agent 3 评估

    # 非Agent通用模型（3个Agent以外的LLM调用使用此模型）
    common_model: str = ""

    # LLM推理设置（DeepSeek API 参数）
    reasoning_effort: str = "high"   # reasoning_effort: low / medium / high
    thinking: bool = True           # 是否启用thinking模式

    # Pipeline
    max_iterations: int = 3
    max_syntax_retries: int = 5

    # Data paths
    data_dir: str = str(Path(__file__).parent / "dataset" / "valid_permission")
    results_dir: str = str(Path(__file__).parent / "log" / "results")
    db_path: str = str(Path(__file__).parent / "log" / "experiments.db")

    # Prompt
    prompt_type: str = "default"

    # Experiment
    experiment_name: str = "default"


settings = Settings()
