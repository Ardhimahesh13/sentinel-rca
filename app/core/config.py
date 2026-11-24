import os
from functools import lru_cache
from pydantic_settings import BaseSettings,SettingsConfigDict

class Settings(BaseSettings) :
    APP_NAME : str = "SentinelRCA"
    ENVIRONMENT : str = "development"


    # Groq
    GROQ_API_KEY : str
    FAST_MODEL_NAME : str = "openai/gpt-oss-20b"
    REASONING_MODEL_NAME: str = "openai/gpt-oss-120b"

    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "sentinel-rca-runbooks"
    PINECONE_EMBED_MODEL: str = "multilingual-e5-large"

    # LangSmith Observability
    LANGSMITH_TRACING: str = "true"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: str
    LANGSMITH_PROJECT: str = "sentinel-rca-prod"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def export_tracing_env(self) -> None:
        os.environ["LANGSMITH_TRACING"] = self.LANGSMITH_TRACING
        os.environ["LANGSMITH_ENDPOINT"] = self.LANGSMITH_ENDPOINT
        os.environ["LANGSMITH_API_KEY"] = self.LANGSMITH_API_KEY
        os.environ["LANGSMITH_PROJECT"] = self.LANGSMITH_PROJECT

@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.export_tracing_env()
    return settings




