from __future__ import annotations

import json
from types import SimpleNamespace

import guardrail_bench.adapters as adapters
import httpx
import pytest
from guardrail_bench.models import Message, TaskDefinition

CONVERSATION = (Message(role="user", content="hello"),)
TASK = TaskDefinition(task_id="task", version="1", question="Is this harmful?", label_mapping={})


class _Response:
    status_code = 200
    is_error = False

    def __init__(self, decision: object = False) -> None:
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
