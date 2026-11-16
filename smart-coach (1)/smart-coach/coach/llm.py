"""Thin wrapper around the Groq API.

Kept tiny on purpose so tests can swap in a fake with the same two methods
(`chat_json`, `chat_text`). If no API key is configured, `get_llm()` returns
None and the app runs in offline (rule-based) mode.
"""
from __future__ import annotations

import json
import os

DEFAULT_MODEL = "llama-3.3-70b-versatile"  # override with GROQ_MODEL if it is retired


class GroqLLM:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        from groq import Groq  # imported lazily so the app works without the package

        self.client = Groq(api_key=api_key)
        self.model = model

    def chat_json(self, messages: list[dict], temperature: float = 0.3) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)

    def chat_text(self, messages: list[dict], temperature: float = 0.5) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature
        )
        return resp.choices[0].message.content.strip()


def get_llm(api_key: str | None = None, model: str | None = None) -> GroqLLM | None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        return None
    try:
        return GroqLLM(key, model or os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    except ImportError:
        return None


class BudgetedLLM:
    """Caps the number of LLM calls (protects your API quota on a public deployment).

    `box` is a mutable dict like {"left": 20} that survives Streamlit reruns.
    When the budget is spent it raises RuntimeError; the planner treats that as an
    API failure and falls back to the rule-based path.
    """

    def __init__(self, inner, box: dict):
        self.inner = inner
        self.box = box

    def _spend(self) -> None:
        if self.box.get("left", 0) <= 0:
            raise RuntimeError("LLM call budget exhausted for this session")
        self.box["left"] -= 1

    def chat_json(self, messages, temperature: float = 0.3):
        self._spend()
        return self.inner.chat_json(messages, temperature)

    def chat_text(self, messages, temperature: float = 0.5):
        self._spend()
        return self.inner.chat_text(messages, temperature)
