from functools import lru_cache
from typing import Literal
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq
from app.core.config import get_settings


ModelTier = Literal["fast","reasoning"]

@lru_cache
def get_llm(tier : ModelTier = 'fast', temperature: float = 0.0) ->  BaseChatModel :

    settings = get_settings()

    fast_llm = ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.FAST_MODEL_NAME,
        temperature=temperature,
        max_retries=3,
        timeout=30.0,
    )

    if tier == "fast" :
        return fast_llm

    reasoning_llm = ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.REASONING_MODEL_NAME,
        temperature=temperature,
        max_retries=3,
        timeout=45.0,
    )



    return reasoning_llm.with_fallbacks([fast_llm])