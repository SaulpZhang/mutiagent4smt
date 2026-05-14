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

    # LLM API
    api_key: str = ""
    api_url: str = ""
    model_name: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096
    llm_request_timeout: int = 120
    llm_max_retries: int = 3

    # Pipeline
    max_iterations: int = 10
    max_syntax_retries: int = 5

    # Data paths
    data_dir: str = str(Path(__file__).parent / "valid_permission")
    results_dir: str = str(Path(__file__).parent / "data" / "results")
    db_path: str = str(Path(__file__).parent / "data" / "experiments.db")

    # Experiment
    experiment_name: str = "default"


settings = Settings()
