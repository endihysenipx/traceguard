"""Controlled local runbook and transparent deterministic retrieval."""

import re
from types import MappingProxyType
from typing import Mapping

from pydantic import Field

from traceguard.domain.enums import CanonicalErrorCode
from traceguard.domain.models import DomainModel


class RunbookEntry(DomainModel):
    entry_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    tags: tuple[str, ...] = Field(min_length=1, max_length=8)
    symptoms: str = Field(min_length=1, max_length=400)
    diagnostic_guidance: str = Field(min_length=1, max_length=500)
    recovery_guidance: str = Field(min_length=1, max_length=500)
    prohibited_actions: str = Field(min_length=1, max_length=400)


_ENTRIES = {
    "RB-EXTRACTION-PROVIDER": RunbookEntry(
        entry_id="RB-EXTRACTION-PROVIDER",
        title="Extraction provider failure",
        tags=(CanonicalErrorCode.EXTRACTION_MODEL_ERROR.value, "extraction", "provider"),
        symptoms="Extraction terminates before a usable candidate is returned.",
        diagnostic_guidance=(
            "Inspect the extraction event and artifact for a sanitized provider failure. "
            "Do not infer missing order fields when no usable extraction exists."
        ),
        recovery_guidance=(
            "Request human review of provider configuration or availability; a later "
            "workflow run may be submitted after the provider issue is resolved."
        ),
        prohibited_actions="Do not expose provider secrets or claim that extraction succeeded.",
    ),
    "RB-ORDER-STRUCTURE": RunbookEntry(
        entry_id="RB-ORDER-STRUCTURE",
        title="Structurally invalid extracted order",
        tags=(CanonicalErrorCode.ORDER_STRUCTURE_INVALID.value, "structure", "type"),
        symptoms="The extraction output has an invalid field shape or type.",
        diagnostic_guidance=(
            "Inspect the structural-validation event and artifact. Distinguish malformed "
            "types from missing but nullable business data."
        ),
        recovery_guidance="Request corrected input or human review; do not retry unchanged blindly.",
        prohibited_actions="Do not coerce or invent values to bypass structural validation.",
    ),
    "RB-MISSING-REQUIRED-INPUT": RunbookEntry(
        entry_id="RB-MISSING-REQUIRED-INPUT",
        title="Missing required business input",
        tags=(
            CanonicalErrorCode.CUSTOMER_NUMBER_MISSING.value,
            CanonicalErrorCode.PRODUCT_CODE_MISSING.value,
            CanonicalErrorCode.QUANTITY_MISSING.value,
            "domain",
            "missing",
        ),
        symptoms="A structurally valid candidate lacks a required business field.",
        diagnostic_guidance=(
            "Inspect domain-validation evidence and the candidate artifact to identify "
            "which required value is absent."
        ),
        recovery_guidance="Request input correction or human review and create a new run.",
        prohibited_actions="Do not invent missing identifiers or quantities; do not retry unchanged.",
    ),
    "RB-QUANTITY-NON-POSITIVE": RunbookEntry(
        entry_id="RB-QUANTITY-NON-POSITIVE",
        title="Non-positive order quantity",
        tags=(CanonicalErrorCode.QUANTITY_NON_POSITIVE.value, "quantity", "business"),
        symptoms="Business-rule validation rejects a zero or negative quantity.",
        diagnostic_guidance="Inspect the business-validation event and artifact for the rejected rule.",
        recovery_guidance="Request corrected input; identical execution cannot repair the quantity.",
        prohibited_actions="Do not retry the same input or silently change the quantity.",
    ),
    "RB-ERP-UNAVAILABLE": RunbookEntry(
        entry_id="RB-ERP-UNAVAILABLE",
        title="ERP service unavailable",
        tags=(CanonicalErrorCode.ERP_UNAVAILABLE.value, "erp", "503", "unavailable"),
        symptoms="The terminal ERP request returns service unavailable, commonly HTTP 503.",
        diagnostic_guidance=(
            "Confirm the terminal ERP event and external-call artifact. Treat continued "
            "warnings and recovered cache failures as non-causal context."
        ),
        recovery_guidance=(
            "Recommend a bounded same-input retry only if deterministic recovery policy "
            "later authorizes it with idempotency and attempt limits."
        ),
        prohibited_actions="Do not execute a retry or treat recovered cache noise as the root cause.",
    ),
}

RUNBOOK_ENTRIES: Mapping[str, RunbookEntry] = MappingProxyType(_ENTRIES)


class LocalRunbook:
    @property
    def entry_ids(self) -> frozenset[str]:
        return frozenset(RUNBOOK_ENTRIES)

    def search(
        self,
        query: str,
        *,
        error_code: CanonicalErrorCode | None = None,
        limit: int = 3,
    ) -> tuple[RunbookEntry, ...]:
        query_tokens = _tokens(query)
        ranked: list[tuple[int, int, str, RunbookEntry]] = []
        for entry in RUNBOOK_ENTRIES.values():
            exact = int(
                error_code is not None and error_code.value in entry.tags
            )
            searchable = " ".join(
                (
                    entry.title,
                    " ".join(entry.tags),
                    entry.symptoms,
                    entry.diagnostic_guidance,
                    entry.recovery_guidance,
                    entry.prohibited_actions,
                )
            )
            overlap = len(query_tokens & _tokens(searchable))
            if exact or overlap:
                ranked.append((-exact, -overlap, entry.entry_id, entry))
        ranked.sort(key=lambda item: item[:3])
        return tuple(item[3].model_copy(deep=True) for item in ranked[:limit])


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.lower()))
