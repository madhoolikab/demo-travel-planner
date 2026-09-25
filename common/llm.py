"""Builds the chat model client from .env, so every stage uses the same
settings and a different OpenAI-compatible provider can be tried by editing
.env only.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

DEFAULT_MODEL_NAME = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0


@lru_cache(maxsize=8)
def get_llm(temperature: float = DEFAULT_TEMPERATURE) -> ChatOpenAI:
    """Returns a cached chat model client. The model must support tool
    calling and structured output; that's all every stage assumes.
    """
    model_name = os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME)
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or None

    kwargs = {"model": model_name, "temperature": temperature}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def model_name() -> str:
    return os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME)
