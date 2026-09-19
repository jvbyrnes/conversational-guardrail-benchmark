from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from guardrail_bench.models import Message, PredictionError, TaskDefinition, Usage


@dataclass(frozen=True)
class AdapterResult:
    decision: bool | None
    score: float | None = None
    usage: Usage = field(default_factory=Usage)
    error: PredictionError | None = None


class ModelAdapter(Protocol):
    adapter_id: str
    model_id: str

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult: ...


class FakeAdapter:
    def __init__(self, adapter_id: str = "fake", model_id: str = "deterministic-fake-v1") -> None:
        self.adapter_id = adapter_id
        self.model_id = model_id

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
        text = "\n".join(message.content for message in conversation).lower()
        if "[error]" in text:
            return AdapterResult(None, error=PredictionError(kind="provider", message="fixture failure"))
        positive = "[positive]" in text or "jailbreak" in text or "ignore previous" in text
        return AdapterResult(positive, score=0.9 if positive else 0.1)


class OpenAIAdapter:
    def __init__(self, adapter_id: str, model_id: str, parameters: dict[str, Any] | None = None) -> None:
        self.adapter_id = adapter_id
        self.model_id = model_id
        self.parameters = parameters or {}
        self.api_key = os.environ.get("OPENAI_API_KEY")

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
        if not self.api_key:
            return AdapterResult(None, error=PredictionError(kind="configuration", message="OPENAI_API_KEY is not set"))
        messages = [{"role": "system", "content": task.question}, *[m.model_dump(mode="json") for m in conversation]]
        payload = {
            "model": self.model_id,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"decision": {"type": "boolean"}},
                        "required": ["decision"],
                        "additionalProperties": False,
                    },
                },
            },
            **self.parameters,
        }
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code == 429:
            return AdapterResult(
                None, error=PredictionError(kind="rate_limit", message="provider rate limit", retryable=True)
            )
        if response.is_error:
            return AdapterResult(
                None,
                error=PredictionError(
                    kind="provider", message=f"HTTP {response.status_code}", retryable=response.status_code >= 500
                ),
            )
        body = response.json()
        try:
            decision = bool(json.loads(body["choices"][0]["message"]["content"])["decision"])
            usage = body.get("usage", {})
            return AdapterResult(
                decision,
                usage=Usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    provider_fields=usage,
                ),
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            return AdapterResult(None, error=PredictionError(kind="invalid_response", message=str(exc)))


class OpenRouterAdapter(OpenAIAdapter):
    """OpenRouter's OpenAI-compatible chat-completions API."""

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            return AdapterResult(
                None, error=PredictionError(kind="configuration", message="OPENROUTER_API_KEY is not set")
            )

        messages = [{"role": "system", "content": task.question}, *[m.model_dump(mode="json") for m in conversation]]
        payload = {
            "model": self.model_id,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"decision": {"type": "boolean"}},
                        "required": ["decision"],
                        "additionalProperties": False,
                    },
                },
            },
            **self.parameters,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if referer := os.environ.get("OPENROUTER_HTTP_REFERER"):
            headers["HTTP-Referer"] = referer
        if title := os.environ.get("OPENROUTER_APP_TITLE"):
            headers["X-Title"] = title
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 429:
            return AdapterResult(
                None, error=PredictionError(kind="rate_limit", message="provider rate limit", retryable=True)
            )
        if response.is_error:
            return AdapterResult(
                None,
                error=PredictionError(
                    kind="provider", message=f"HTTP {response.status_code}", retryable=response.status_code >= 500
                ),
            )
        body = response.json()
        try:
            decision = bool(json.loads(body["choices"][0]["message"]["content"])["decision"])
            usage = body.get("usage", {})
            return AdapterResult(
                decision,
                usage=Usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    provider_fields=usage,
                ),
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            return AdapterResult(None, error=PredictionError(kind="invalid_response", message=str(exc)))


class _JevAnswer(BaseModel):
    decision: bool = Field(description="The answer to the supplied semantic yes-or-no question")


class JevAdapter:
    """TypeSafe Jev adapter using its typed async `adecide` interface.

    Import is deliberately lazy so offline users do not need the optional SDK.
    The public Jev convenience package currently drops probability and usage data;
    those fields therefore remain unavailable rather than being inferred.
    """

    def __init__(self, adapter_id: str, model_id: str, parameters: dict[str, Any] | None = None) -> None:
        self.adapter_id = adapter_id
        self.model_id = model_id
        self.parameters = parameters or {}

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
        if not os.environ.get("TYPESAFE_API_KEY"):
            return AdapterResult(
                None, error=PredictionError(kind="configuration", message="TYPESAFE_API_KEY is not set")
            )
        try:
            import jev  # type: ignore[import-not-found]
        except ImportError:
            return AdapterResult(None, error=PredictionError(kind="configuration", message="install the 'jev' package"))
        state = {
            "classifier_question": task.question,
            "conversation": [m.model_dump(mode="json") for m in conversation],
        }
        try:
            answer = await jev.adecide(state, _JevAnswer, model=self.model_id, **self.parameters)
            return AdapterResult(bool(answer.decision))
        except Exception as exc:
            return AdapterResult(None, error=PredictionError(kind="provider", message=str(exc), retryable=True))


async def call_with_retry(
    adapter: ModelAdapter,
    conversation: tuple[Message, ...],
    task: TaskDefinition,
    *,
    retries: int,
    timeout_seconds: float,
) -> tuple[AdapterResult, float]:
    started = time.perf_counter()
    result: AdapterResult | None = None
    for attempt in range(retries + 1):
        try:
            result = await asyncio.wait_for(adapter.classify(conversation, task), timeout_seconds)
        except TimeoutError:
            result = AdapterResult(
                None,
                error=PredictionError(kind="timeout", message=f"timed out after {timeout_seconds}s", retryable=True),
            )
        if result.error is None or not result.error.retryable or attempt == retries:
            break
        await asyncio.sleep(min(0.1 * (2**attempt), 1.0))
    assert result is not None
    return result, (time.perf_counter() - started) * 1000
