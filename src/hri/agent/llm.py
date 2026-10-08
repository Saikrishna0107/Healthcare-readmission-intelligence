"""A local LLM through Ollama's HTTP API (D-010: local only, no API keys, no data leaves the PC).

The model is asked for JSON matching a schema. Ollama turns the schema into a grammar, so the
reply can only contain the allowed metric and dimension names: the model cannot invent one.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol

import requests

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "granite4.1:3b"


class LLMError(RuntimeError):
    """The model server could not be reached or did not answer."""


@dataclass
class Call:
    """One model call, kept for the latency numbers in the answer and the evaluation."""
    seconds: float
    prompt_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    calls: list[Call]

    def chat(self, messages: list[dict], schema: dict) -> str: ...


@dataclass
class OllamaClient:
    model: str = DEFAULT_MODEL
    url: str = OLLAMA_URL
    timeout: float = 300  # the first call loads the model and reads the whole prompt on the CPU
    calls: list[Call] = field(default_factory=list)

    def chat(self, messages: list[dict], schema: dict) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "format": schema,
            "stream": False,
            # Same question, same plan: no sampling randomness.
            "options": {"temperature": 0, "seed": 0, "num_ctx": 8192},
            "keep_alive": "15m",  # keep the model in memory between questions
        }
        start = time.perf_counter()
        try:
            response = requests.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
        except requests.ConnectionError as exc:
            raise LLMError(f"Ollama is not running at {self.url}; start the Ollama app.") from exc
        if response.status_code == 404:
            raise LLMError(f"Model {self.model!r} is not installed. Run: ollama pull {self.model}")
        response.raise_for_status()
        reply = response.json()
        self.calls.append(Call(time.perf_counter() - start, reply.get("prompt_eval_count", 0),
                               reply.get("eval_count", 0)))
        return reply["message"]["content"]
