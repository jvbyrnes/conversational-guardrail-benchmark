from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import guardrail_bench.adapters as adapters
import httpx
import pytest
from guardrail_bench.budget import CostBudget
from guardrail_bench.models import Message, PredictionError, TaskDefinition, Usage

CONVERSATION = (Message(role="user", content="hello"),)
TASK = TaskDefinition(task_id="task", version="1", question="Is this harmful?", label_mapping={})


class _Response:
    def __init__(self, decision: object = False, status_code: int = 200) -> None:
        self.status_code = status_code
        self.is_error = status_code >= 400
        self.payload = {
            "choices": [{"message": {"content": json.dumps({"decision": decision})}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }

    def json(self) -> dict[str, object]:
        return self.payload


class _Client:
    response: _Response = _Response()
    calls: list[dict[str, object]] = []
    raise_error = False

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, _: str, *, headers: dict[str, str], json: dict[str, object]) -> _Response:
        self.calls.append({"headers": headers, "json": json})
        if self.raise_error:
            raise httpx.ConnectError("connection reset", request=httpx.Request("POST", "https://example.test"))
        return self.response


@pytest.mark.parametrize(
    ("adapter_type", "api_key"),
    [(adapters.OpenRouterAdapter, "OPENROUTER_API_KEY")],
)
@pytest.mark.asyncio
async def test_openai_compatible_adapters_protect_payload_and_reject_non_boolean(
    monkeypatch: pytest.MonkeyPatch,
    adapter_type: type[adapters.OpenRouterAdapter],
    api_key: str,
) -> None:
    monkeypatch.setenv(api_key, "test-key")
    _Client.calls = []
    _Client.response = _Response("false")
    monkeypatch.setattr(adapters.httpx, "AsyncClient", _Client)

    adapter = adapter_type(
        "adapter",
        "configured-model",
        parameters={"model": "attacker-model", "messages": [], "response_format": {}, "temperature": 0},
    )
    result = await adapter.classify(CONVERSATION, TASK)

    assert result.decision is None
    assert result.error is not None
    assert result.error.kind == "invalid_response"
    sent = _Client.calls[0]["json"]
    assert sent["model"] == "configured-model"
    assert sent["messages"] != []
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["temperature"] == 0


@pytest.mark.parametrize(
    ("adapter_type", "api_key"),
    [(adapters.OpenRouterAdapter, "OPENROUTER_API_KEY")],
)
@pytest.mark.asyncio
async def test_openai_compatible_transport_failures_are_retryable(
    monkeypatch: pytest.MonkeyPatch,
    adapter_type: type[adapters.OpenRouterAdapter],
    api_key: str,
) -> None:
    monkeypatch.setenv(api_key, "test-key")
    _Client.calls = []
    _Client.raise_error = True
    monkeypatch.setattr(adapters.httpx, "AsyncClient", _Client)

    result = await adapter_type("adapter", "model").classify(CONVERSATION, TASK)

    assert result.error is not None
    assert result.error.kind == "provider"
    assert result.error.retryable is True
    _Client.raise_error = False


@pytest.mark.asyncio
async def test_openrouter_reports_insufficient_funds_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _Client.calls = []
    _Client.response = _Response(status_code=402)
    monkeypatch.setattr(adapters.httpx, "AsyncClient", _Client)

    result = await adapters.OpenRouterAdapter("adapter", "model").classify(CONVERSATION, TASK)

    assert result.error is not None
    assert result.error.kind == "insufficient_funds"
    assert result.error.retryable is False


@pytest.mark.asyncio
async def test_jev_adapter_uses_typesafe_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.request: dict[str, object] | None = None

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def system_one(self, **kwargs: object) -> SimpleNamespace:
            self.request = kwargs
            return SimpleNamespace(
                nouls={"decision": SimpleNamespace(noul=0.75)},
                usage=SimpleNamespace(
                    input_tokens=4,
                    output_tokens=1,
                    model_dump=lambda **_: {"input_tokens": 4, "output_tokens": 1},
                ),
            )

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setitem(__import__("sys").modules, "typesafe_sdk", SimpleNamespace(AsyncTypeSafeClient=_Client))

    result = await adapters.JevAdapter("jev", "system-one").classify(CONVERSATION, TASK)

    assert result.error is None
    assert result.decision is True
    assert result.score == 0.75
    assert result.usage.input_tokens == 4
    assert result.usage.provider_fields["estimated_cost"] == pytest.approx(4 * 0.042 / 1_000_000)
    assert result.usage.provider_fields["pricing_source"] == "typesafe-published-input-only"


class _CountingAdapter:
    adapter_id = "paid"
    model_id = "model"

    def __init__(self, results: list[adapters.AdapterResult]) -> None:
        self.results = results
        self.calls = 0

    async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> adapters.AdapterResult:
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]


@pytest.mark.asyncio
async def test_cost_budget_reconciles_valid_cost_and_reopens_allowance() -> None:
    adapter = _CountingAdapter(
        [
            adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004})),
            adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004})),
            adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004})),
            adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004})),
            adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004})),
        ]
    )
    budget = CostBudget.from_float(0.02)

    first, _ = await budget.call(adapter, CONVERSATION, TASK, 0.006, 1)
    second, _ = await budget.call(adapter, CONVERSATION, TASK, 0.006, 1)
    third, _ = await budget.call(adapter, CONVERSATION, TASK, 0.006, 1)
    fourth, _ = await budget.call(adapter, CONVERSATION, TASK, 0.006, 1)
    blocked, _ = await budget.call(adapter, CONVERSATION, TASK, 0.006, 1)

    assert first.error is None
    assert second.error is None
    assert third.error is None
    assert fourth.error is None
    assert blocked.error is not None and blocked.error.kind == "cost_cap"
    assert adapter.calls == 4
    assert budget.reserved_usd == Decimal("0.016")
    assert budget.admitted_usd == Decimal("0.024")
    assert budget.actual_usd == Decimal("0.016")


@pytest.mark.asyncio
async def test_cost_budget_keeps_missing_cost_reservation() -> None:
    adapter = _CountingAdapter(
        [
            adapters.AdapterResult(False),
            adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004})),
        ]
    )
    budget = CostBudget.from_float(0.02)

    first, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)
    second, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)
    blocked, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)

    assert first.error is None
    assert second.error is None
    assert blocked.error is not None and blocked.error.kind == "cost_cap"
    assert budget.reserved_usd == Decimal("0.014")
    assert budget.admitted_usd == Decimal("0.02")
    assert budget.actual_usd == Decimal("0.004")


@pytest.mark.asyncio
async def test_cost_budget_trips_when_reported_cost_exceeds_reservation() -> None:
    adapter = _CountingAdapter([adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.011}))])
    budget = CostBudget.from_float(0.03)

    breach, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)
    blocked, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)

    assert breach.error is not None and breach.error.kind == "cost_cap"
    assert "exceeded" in breach.error.message
    assert blocked.error is not None and blocked.error.kind == "cost_cap"
    assert adapter.calls == 1
    assert budget.reserved_usd == Decimal("0.011")
    assert budget.actual_usd == Decimal("0.011")


@pytest.mark.asyncio
async def test_cost_budget_releases_only_unused_valid_reservation() -> None:
    adapter = _CountingAdapter([adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0}))])
    budget = CostBudget.from_float(0.01)

    result, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)

    assert result.error is None
    assert budget.reserved_usd == Decimal("0")
    assert budget.admitted_usd == Decimal("0.01")
    assert budget.actual_usd == Decimal("0")


@pytest.mark.asyncio
async def test_retries_each_require_a_fresh_cost_reservation() -> None:
    adapter = _CountingAdapter(
        [
            adapters.AdapterResult(
                None,
                usage=Usage(provider_fields={"cost": 0.006}),
                error=PredictionError(kind="provider", message="retry", retryable=True),
            )
        ]
    )
    budget = CostBudget.from_float(0.02)

    result, _ = await adapters.call_with_retry(
        adapter,
        CONVERSATION,
        TASK,
        retries=2,
        timeout_seconds=1,
        budget=budget,
        cost_reservation_usd=0.01,
    )

    assert result.error is not None and result.error.kind == "cost_cap"
    assert adapter.calls == 2
    assert budget.reserved_usd == Decimal("0.012")
    assert budget.admitted_usd == Decimal("0.02")
    assert budget.actual_usd == Decimal("0.012")


@pytest.mark.asyncio
async def test_insufficient_funds_trips_budget_gate() -> None:
    adapter = _CountingAdapter(
        [
            adapters.AdapterResult(
                None,
                error=PredictionError(kind="insufficient_funds", message="no credit"),
            )
        ]
    )
    budget = CostBudget.from_float(0.03)

    first, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)
    blocked, _ = await budget.call(adapter, CONVERSATION, TASK, 0.01, 1)

    assert first.error is not None and first.error.kind == "insufficient_funds"
    assert blocked.error is not None and blocked.error.kind == "cost_cap"
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_budget_gate_wait_is_excluded_from_request_latency() -> None:
    class SerializedAdapter:
        adapter_id = "paid"
        model_id = "model"

        def __init__(self) -> None:
            self.calls = 0
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> adapters.AdapterResult:
            self.calls += 1
            if self.calls == 1:
                self.first_started.set()
                await self.release_first.wait()
            return adapters.AdapterResult(False, usage=Usage(provider_fields={"cost": 0.001}))

    adapter = SerializedAdapter()
    budget = CostBudget.from_float(0.02)

    first_task = asyncio.create_task(
        adapters.call_with_retry(
            adapter,
            CONVERSATION,
            TASK,
            retries=0,
            timeout_seconds=1,
            budget=budget,
            cost_reservation_usd=0.01,
        )
    )
    await adapter.first_started.wait()
    second_task = asyncio.create_task(
        adapters.call_with_retry(
            adapter,
            CONVERSATION,
            TASK,
            retries=0,
            timeout_seconds=1,
            budget=budget,
            cost_reservation_usd=0.01,
        )
    )
    await asyncio.sleep(0.05)
    adapter.release_first.set()

    (_, first_latency_ms), (_, second_latency_ms) = await asyncio.gather(first_task, second_task)

    assert first_latency_ms >= 40
    assert second_latency_ms < 20
