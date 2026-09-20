from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from guardrail_bench.models import Message, PredictionError, TaskDefinition, Usage


def _is_insufficient_funds(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 402:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in ("insufficient funds", "insufficient credits", "payment required"))


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


class PaidCallBudget(Protocol):
    async def call(
        self,
        adapter: ModelAdapter,
        conversation: tuple[Message, ...],
        task: TaskDefinition,
        reservation_usd: float,
        timeout_seconds: float,
    ) -> AdapterResult: ...


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


class OpenRouterAdapter:
    """OpenRouter's OpenAI-compatible chat-completions API."""

    def __init__(self, adapter_id: str, model_id: str, parameters: dict[str, Any] | None = None) -> None:
        self.adapter_id = adapter_id
        self.model_id = model_id
        self.parameters = parameters or {}

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            return AdapterResult(
                None, error=PredictionError(kind="configuration", message="OPENROUTER_API_KEY is not set")
            )

        messages = [{"role": "system", "content": task.question}, *[m.model_dump(mode="json") for m in conversation]]
        payload = {
            **self.parameters,
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
            "usage": {"include": True},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if referer := os.environ.get("OPENROUTER_HTTP_REFERER"):
            headers["HTTP-Referer"] = referer
        if title := os.environ.get("OPENROUTER_APP_TITLE"):
            headers["X-Title"] = title
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload
                )
        except httpx.RequestError as exc:
            return AdapterResult(
                None, error=PredictionError(kind="provider", message=str(exc), retryable=True)
            )
        if response.status_code == 429:
            return AdapterResult(
                None, error=PredictionError(kind="rate_limit", message="provider rate limit", retryable=True)
            )
        if response.status_code == 402:
            return AdapterResult(
                None,
                error=PredictionError(kind="insufficient_funds", message="provider reported insufficient funds"),
            )
        if response.is_error:
            return AdapterResult(
                None,
                error=PredictionError(
                    kind="provider", message=f"HTTP {response.status_code}", retryable=response.status_code >= 500
                ),
            )
        try:
            body = response.json()
            decision_value = json.loads(body["choices"][0]["message"]["content"])["decision"]
            if not isinstance(decision_value, bool):
                raise TypeError("decision must be a boolean")
            usage = body.get("usage", {})
            return AdapterResult(
                decision_value,
                usage=Usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    provider_fields=usage,
                ),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return AdapterResult(None, error=PredictionError(kind="invalid_response", message=str(exc)))


class JevAdapter:
    """TypeSafe adapter using the official ``typesafe-sdk`` async client.

    Import is deliberately lazy so offline users do not need the optional SDK.
    TypeSafe's ``noul`` answer is a probability, which is retained as ``score``
    and thresholded at 0.5 for the benchmark's Boolean decision.
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
            AsyncTypeSafeClient = importlib.import_module("typesafe_sdk").AsyncTypeSafeClient
        except ImportError:
            return AdapterResult(
                None,
                error=PredictionError(kind="configuration", message="install the 'typesafe-sdk' package"),
            )
        state: dict[str, Any] = {
            "classifier_question": task.question,
            "conversation": [m.model_dump(mode="json") for m in conversation],
        }
        try:
            async with AsyncTypeSafeClient(
                api_key=os.environ["TYPESAFE_API_KEY"], model=self.model_id
            ) as client:
                response = await client.system_one(
                    state=state,
                    questions={"decision": {"type": "noul", "instructions": task.question}},
                    extra_body=self.parameters or None,
                )
            answer = response.nouls["decision"]
            score = float(answer.noul)
            usage = response.usage
            return AdapterResult(
                score >= 0.5,
                score=score,
                usage=Usage(
                    input_tokens=usage.input_tokens or 0,
                    output_tokens=usage.output_tokens or 0,
                    provider_fields=usage.model_dump(mode="json"),
                ),
            )
        except Exception as exc:
            if _is_insufficient_funds(exc):
                return AdapterResult(
                    None,
                    error=PredictionError(kind="insufficient_funds", message="provider reported insufficient funds"),
                )
            return AdapterResult(None, error=PredictionError(kind="provider", message=str(exc), retryable=True))


async def call_with_retry(
    adapter: ModelAdapter,
    conversation: tuple[Message, ...],
    task: TaskDefinition,
    *,
    retries: int,
    timeout_seconds: float,
    budget: PaidCallBudget | None = None,
    cost_reservation_usd: float | None = None,
) -> tuple[AdapterResult, float]:
    started = time.perf_counter()
    result: AdapterResult | None = None
    for attempt in range(retries + 1):
        try:
            if budget is None:
                result = await asyncio.wait_for(adapter.classify(conversation, task), timeout_seconds)
            else:
                if cost_reservation_usd is None:
                    raise ValueError("paid calls require a cost reservation")
                result = await budget.call(
                    adapter,
                    conversation,
                    task,
                    cost_reservation_usd,
                    timeout_seconds,
                )
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
