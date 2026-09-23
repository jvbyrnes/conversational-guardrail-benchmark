from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from guardrail_bench.adapters import AdapterResult, ModelAdapter
from guardrail_bench.models import Message, PredictionError, TaskDefinition, Usage


def _reported_cost(result: AdapterResult) -> Decimal | None:
    value = result.usage.provider_fields.get("cost")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("provider-reported cost must be a finite non-negative number")
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("provider-reported cost must be a finite non-negative number") from exc
    if not cost.is_finite() or cost < 0:
        raise ValueError("provider-reported cost must be a finite non-negative number")
    return cost


@dataclass
class CostBudget:
    """Conservative dispatch gate for paid adapter attempts.

    A reservation is held before each paid call so the configured cap bounds every
    admitted attempt. A trustworthy provider-reported cost then replaces that
    reservation in the current commitment, making unused allowance available to later
    calls. Missing or untrustworthy billing data keeps the reservation held and stops
    the run when it cannot be safely reconciled. The gate remains held during a paid
    call, making admission and reconciliation atomic.
    """

    cap_usd: Decimal
    # Current amount consuming the cap: valid reported spend plus unreconciled
    # reservations. This is the value used for admission checks.
    reserved_usd: Decimal = Decimal("0")
    # Sum of all reservations admitted before provider calls, retained for reporting.
    admitted_usd: Decimal = Decimal("0")
    # Sum of valid provider-reported costs reconciled so far.
    actual_usd: Decimal = Decimal("0")
    _breach: str | None = None
    _gate: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    def from_float(cls, cap_usd: float) -> CostBudget:
        if not math.isfinite(cap_usd) or cap_usd <= 0:
            raise ValueError("cost cap must be a finite positive number")
        return cls(Decimal(str(cap_usd)))

    async def call(
        self,
        adapter: ModelAdapter,
        conversation: tuple[Message, ...],
        task: TaskDefinition,
        reservation_usd: float,
        timeout_seconds: float,
    ) -> tuple[AdapterResult, float]:
        reservation = Decimal(str(reservation_usd))
        async with self._gate:
            if self._breach is not None:
                return self._error(self._breach), 0.0
            remaining = self.cap_usd - self.reserved_usd
            if reservation > remaining:
                return (
                    self._error(
                        f"cost cap exhausted: {remaining} USD remains but this attempt requires "
                        f"a {reservation} USD reservation"
                    ),
                    0.0,
                )
            self.reserved_usd += reservation
            self.admitted_usd += reservation
            request_started = time.perf_counter()
            try:
                result = await asyncio.wait_for(adapter.classify(conversation, task), timeout_seconds)
            except TimeoutError:
                latency_ms = (time.perf_counter() - request_started) * 1000
                return (
                    AdapterResult(
                        None,
                        error=PredictionError(
                            kind="timeout", message=f"timed out after {timeout_seconds}s", retryable=True
                        ),
                    ),
                    latency_ms,
                )
            latency_ms = (time.perf_counter() - request_started) * 1000
            if result.error is not None and result.error.kind == "insufficient_funds":
                self._breach = "provider reported insufficient funds; no further paid calls were started"
                return result, latency_ms
            try:
                reported = _reported_cost(result)
            except ValueError as exc:
                self._breach = str(exc)
                return self._error(self._breach, result, sanitize_reported_cost=True), latency_ms
            if reported is not None and reported > reservation:
                # Keep the cap fail-closed, but account for the trustworthy overage
                # so artifacts reflect the provider-reported spend.
                self.reserved_usd += reported - reservation
                self.actual_usd += reported
                self._breach = (
                    f"provider-reported cost {reported} USD exceeded the configured "
                    f"{reservation} USD reservation; no further paid calls were started"
                )
                return self._error(self._breach, result), latency_ms
            if reported is not None:
                self.reserved_usd -= reservation - reported
                self.actual_usd += reported
            return result, latency_ms

    @staticmethod
    def _error(
        message: str,
        result: AdapterResult | None = None,
        *,
        sanitize_reported_cost: bool = False,
    ) -> AdapterResult:
        usage = result.usage if result is not None else Usage()
        if sanitize_reported_cost:
            usage = usage.model_copy(
                update={
                    "provider_fields": {key: value for key, value in usage.provider_fields.items() if key != "cost"}
                }
            )
        return AdapterResult(
            None,
            usage=usage,
            error=PredictionError(kind="cost_cap", message=message),
        )
