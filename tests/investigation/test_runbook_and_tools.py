from uuid import uuid4

import pytest

from traceguard.domain.enums import CanonicalErrorCode, EventOutcome, RecoveryState
from traceguard.investigation.runbook import LocalRunbook
from traceguard.investigation.tools import (
    DiagnosticToolRegistry,
    TOOL_NAMES,
    ToolInvocationError,
)
from traceguard.workflow.models import EventType, PresetId, StageArtifactType

from tests.investigation.support import execute_fixture


def test_runbook_exact_error_tag_ranks_before_lexical_matches() -> None:
    results = LocalRunbook().search(
        "provider extraction words that match another entry",
        error_code=CanonicalErrorCode.ERP_UNAVAILABLE,
        limit=3,
    )

    assert results[0].entry_id == "RB-ERP-UNAVAILABLE"


def test_runbook_lexical_retrieval_is_deterministic_and_transparent() -> None:
    runbook = LocalRunbook()
    first = runbook.search("negative non positive quantity business validation")
    second = runbook.search("negative non positive quantity business validation")

    assert [entry.entry_id for entry in first] == [entry.entry_id for entry in second]
    assert first[0].entry_id == "RB-QUANTITY-NON-POSITIVE"
    assert "Do not retry" in first[0].prohibited_actions


def test_registry_exposes_exactly_four_allowlisted_tools() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    registry = DiagnosticToolRegistry(repository, LocalRunbook(), run.run_id)

    assert registry.names == TOOL_NAMES == (
        "get_run_overview",
        "get_run_events",
        "get_stage_artifact",
        "search_runbook",
    )
    assert tuple(item["name"] for item in registry.definitions()) == TOOL_NAMES


def test_overview_omits_hidden_canonical_failure_facts() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    output = DiagnosticToolRegistry(repository, LocalRunbook(), run.run_id).invoke(
        "get_run_overview", {"run_id": run.run_id}
    ).output

    assert "canonical_failure_code" not in output
    assert "canonical_failure_category" not in output
    assert "root_cause" not in output
    assert output["erp_attempt_count"] == 1
    assert StageArtifactType.ERP.value in output["available_artifact_types"]


def test_event_tool_preserves_noise_and_terminal_outcomes_in_order() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    output = DiagnosticToolRegistry(repository, LocalRunbook(), run.run_id).invoke(
        "get_run_events",
        {"run_id": run.run_id, "stage": "ERP_CALLING", "limit": 50},
    ).output
    relevant = [
        event
        for event in output["events"]
        if event["event_type"]
        in {
            EventType.OPTIONAL_FIELD_DEFAULTED.value,
            EventType.CACHE_LOOKUP_FAILED.value,
            EventType.CACHE_FALLBACK_SUCCEEDED.value,
            EventType.ERP_REQUEST_FAILED.value,
        }
    ]

    assert [event["event_type"] for event in relevant] == [
        EventType.OPTIONAL_FIELD_DEFAULTED.value,
        EventType.CACHE_LOOKUP_FAILED.value,
        EventType.CACHE_FALLBACK_SUCCEEDED.value,
        EventType.ERP_REQUEST_FAILED.value,
    ]
    assert [event["outcome"] for event in relevant] == [
        EventOutcome.CONTINUED.value,
        EventOutcome.RECOVERED.value,
        EventOutcome.SUCCESS.value,
        EventOutcome.TERMINAL.value,
    ]


def test_cross_run_and_invalid_arguments_fail_without_data_exposure() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    other, _ = execute_fixture(PresetId.MISSING_CUSTOMER)
    registry = DiagnosticToolRegistry(repository, LocalRunbook(), run.run_id)

    with pytest.raises(ToolInvocationError) as cross_run:
        registry.invoke("get_run_events", {"run_id": other.run_id, "stage": None, "limit": 5})
    assert cross_run.value.reason == "CROSS_RUN_ACCESS"

    with pytest.raises(ToolInvocationError) as invalid:
        registry.invoke("get_run_overview", {"run_id": run.run_id, "write": True})
    assert invalid.value.reason == "INVALID_TOOL_ARGUMENTS"


def test_all_four_tools_are_read_only_and_return_defensive_data() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    registry = DiagnosticToolRegistry(repository, LocalRunbook(), run.run_id)
    before_run = repository.get_run(run.run_id)
    before_events = repository.list_events(run.run_id)
    before_artifacts = repository.list_stage_artifacts(run.run_id)
    before_attempts = repository.list_erp_attempts(run.run_id)

    registry.invoke("get_run_overview", {"run_id": run.run_id})
    registry.invoke("get_run_events", {"run_id": run.run_id, "stage": None, "limit": 50})
    artifact = registry.invoke(
        "get_stage_artifact",
        {"run_id": run.run_id, "artifact_type": StageArtifactType.ERP},
    ).output
    registry.invoke(
        "search_runbook",
        {"query": "ERP unavailable", "error_code": None, "limit": 3},
    )
    artifact["data"]["status_code"] = 999

    after_run = repository.get_run(run.run_id)
    assert after_run == before_run
    assert after_run.recovery_state is RecoveryState.NONE
    assert repository.list_events(run.run_id) == before_events
    assert repository.list_stage_artifacts(run.run_id) == before_artifacts
    assert repository.list_erp_attempts(run.run_id) == before_attempts


def test_unknown_tool_is_rejected() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    registry = DiagnosticToolRegistry(repository, LocalRunbook(), run.run_id)
    with pytest.raises(ToolInvocationError) as raised:
        registry.invoke("retry_erp", {"run_id": run.run_id})
    assert raised.value.reason == "UNKNOWN_TOOL"
