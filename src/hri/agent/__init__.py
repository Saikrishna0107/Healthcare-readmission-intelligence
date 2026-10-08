"""The question-answering agent (step 8b, D-010): a local LLM writes a query plan, the semantic
layer runs it, code writes the answer."""

from hri.agent.agent import Agent, Answer, Plan, format_metric, plan_schema, render, resolve_value
from hri.agent.llm import DEFAULT_MODEL, LLMError, OllamaClient

__all__ = ["Agent", "Answer", "Plan", "format_metric", "plan_schema", "render", "resolve_value",
           "DEFAULT_MODEL", "LLMError", "OllamaClient"]
