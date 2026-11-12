import re
from typing import Literal

from pydantic import Field, model_validator

from backend.supervisor.contracts import CATALOGUE_VERSION, Contract, Intent
from backend.supervisor.policy import normalize_utterance

PII_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b",
    r"(?<!\w)\+?\d(?:[\s().-]*\d){6,}(?!\w)",
    r"\b\d{2}\s*[a-zçğıöşü]{1,3}\s*\d{2,5}\b",
    r"\b[a-hj-npr-z0-9]{17}\b",
    r"\b(?:adım|ismim|soyadım|adresim|plakam|telefonum|tc kimlik)\b[^.!?,;]*",
))


def redact_identifiers(text: str) -> str:
    for pattern in PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class TrainingExample(Contract):
    text: str = Field(min_length=1, max_length=1200)
    intents: tuple[Intent, ...]
    group_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    split: Literal["train", "validation", "test"]
    source: Literal["synthetic", "human_review"]
    catalogue_version: Literal["intent-v1"] = CATALOGUE_VERSION
    review_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    anonymity_attested: bool = False
    consent_attested: bool = False

    @model_validator(mode="after")
    def check_example(self):
        if not normalize_utterance(self.text) or len(set(self.intents)) != len(self.intents):
            raise ValueError("blank text or duplicate labels")
        if self.source == "human_review" and not (
            self.review_id and self.anonymity_attested and self.consent_attested
        ):
            raise ValueError("human examples require approved review, consent and anonymization")
        if redact_identifiers(self.text) != self.text:
            raise ValueError("unmasked identifiers")
        return self


def partition_examples(examples: list[TrainingExample]) -> dict[str, list[TrainingExample]]:
    partitions: dict[str, list[TrainingExample]] = {"train": [], "validation": [], "test": []}
    group_splits = {}
    texts = set()
    for example in examples:
        previous = group_splits.setdefault(example.group_id, example.split)
        if previous != example.split:
            raise ValueError("group occurs in more than one split")
        normalized = normalize_utterance(example.text)
        if normalized in texts:
            raise ValueError("duplicate normalized utterance")
        texts.add(normalized)
        partitions[example.split].append(example)
    for name, rows in partitions.items():
        present = {intent for row in rows for intent in row.intents}
        missing = set(Intent) - present
        if missing or not any(not row.intents for row in rows):
            labels = ", ".join(sorted(missing))
            raise ValueError(f"{name} needs every positive label and OOD rows; missing labels: {labels}")
    return partitions
