"""Strict public contract for the exact reviewed WildJailbreak case sample."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from guardrail_bench.comparison import canonical_json, fingerprint
from guardrail_bench.models import StrictModel

_EXPECTED_REVIEWED_PAYLOAD_FINGERPRINT = "sha256:e6514befb0c26fd18a1d3cee82df981ded40b349c9a33276ed57b037c540a709"


class ReviewSourceRuns(StrictModel):
    jev: Literal["20260925T004541177372Z-a4c027600058"]
    luna: Literal["20260925T014904391035Z-ba0833bb4475"]


class ReviewSelection(StrictModel):
    method: Literal["uniform_random_without_replacement"]
    seed: Literal[20261004]
    provider_errors_excluded: Literal[True]


class ReviewSample(StrictModel):
    case_id: str = Field(pattern=r"^(jev-luna|both-wrong)-0[1-5]$")
    source_label: Literal["adversarial_harmful", "adversarial_benign"]
    ground_truth: bool
    jev_decision: bool
    jev_score: float = Field(ge=0, le=1)
    luna_decision: bool
    prompt: str


class ReviewGroup(StrictModel):
    id: Literal["jev_correct_luna_wrong", "both_wrong"]
    title: Literal["Jev correct, Luna incorrect", "Both incorrect"]
    samples: list[ReviewSample] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def decisions_match_the_group(self) -> ReviewGroup:
        expected_title = {
            "jev_correct_luna_wrong": "Jev correct, Luna incorrect",
            "both_wrong": "Both incorrect",
        }[self.id]
        if self.title != expected_title:
            raise ValueError("review group title does not match its ID")
        for sample in self.samples:
            jev_correct = sample.jev_decision == sample.ground_truth
            luna_correct = sample.luna_decision == sample.ground_truth
            if self.id == "jev_correct_luna_wrong" and not (jev_correct and not luna_correct):
                raise ValueError("sample decisions do not match the Jev-correct group")
            if self.id == "both_wrong" and (jev_correct or luna_correct):
                raise ValueError("sample decisions do not match the both-incorrect group")
        return self


class ReviewedCaseSamples(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["reviewed_sample"]
    task_id: Literal["harmful_jailbreak"]
    task_version: Literal["1.0.0"]
    source_runs: ReviewSourceRuns
    selection: ReviewSelection
    groups: list[ReviewGroup] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def groups_are_complete_unique_and_exact(self) -> ReviewedCaseSamples:
        if [group.id for group in self.groups] != ["jev_correct_luna_wrong", "both_wrong"]:
            raise ValueError("review groups must use the reviewed canonical order")
        case_ids = [sample.case_id for group in self.groups for sample in group.samples]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("review sample case IDs must be unique")
        if fingerprint(self.model_dump(mode="json")) != _EXPECTED_REVIEWED_PAYLOAD_FINGERPRINT:
            raise ValueError("review sample payload does not match the exact reviewed cases")
        return self


def review_sample_bytes(samples: ReviewedCaseSamples) -> bytes:
    """Return deterministic public bytes for the exact reviewed sample."""
    return canonical_json(samples.model_dump(mode="json")) + b"\n"
