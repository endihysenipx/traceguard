import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from traceguard.domain.enums import (
    CanonicalErrorCode,
    InvestigationState,
    RecoveryAction,
    RecoveryState,
    ProviderMode,
)
from traceguard.investigation import Investigator, LocalRunbook
from traceguard.investigation.models import (
    InvestigationStartContext,
    InvestigatorModelError,
    InvestigatorModelResponseError,
    InvestigatorModelTimeoutError,
    ToolCallResult,
)
from traceguard.investigation.openai_model import (
    INVESTIGATOR_INSTRUCTIONS,
    OpenAIInvestigatorModel,
)
from traceguard.investigation.tools import DiagnosticToolRegistry
from traceguard.workflow.models import EventType, PresetId

from tests.investigation.support import execute_fixture, report_for_event


class FakeResponses:
    def __init__(self, responses=None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses=None, error: Exception | None = None) -> None:
        self.responses = FakeResponses(responses, error)


def function_call(call_id: str, name: str, arguments: dict[str, object]):
    return SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=json.dumps(arguments),
    )


def response(*, output=(), report=None):
    return SimpleNamespace(output=list(output), output_parsed=report)


def test_live_adapter_sends_bounded_secure_responses_request_and_tool_output() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    call = function_call(
        "events-call",
        "get_run_events",
        {"run_id": str(run.run_id), "stage": None, "limit": 20},
    )
    client = FakeClient([response(output=[call])])
    model = OpenAIInvestigatorModel(
        client=client, model="configured-investigator", timeout_seconds=8
    )
    definitions = DiagnosticToolRegistry(
        repository, LocalRunbook(), run.run_id
    ).definitions()
    context = InvestigationStartContext(
        run_id=run.run_id, max_model_turns=3, max_tool_calls=6
    )
    model.start(context, definitions)

    turn = model.next_turn()
    model.submit_tool_results(
        (
            ToolCallResult(
                provider_call_id="events-call",
                name="get_run_events",
                output={"events": []},
            ),
        )
    )

    request = client.responses.calls[0]
    assert request["model"] == "configured-investigator"
    assert request["instructions"] == INVESTIGATOR_INSTRUCTIONS
    assert request["store"] is False
    assert request["parallel_tool_calls"] is False
    assert request["timeout"] == 8
    assert len(request["tools"]) == 4
    initial_text = request["input"][0]["content"]
    assert str(run.run_id) in initial_text
    assert run.canonical_failure_code.value not in initial_text
    assert EventType.ERP_REQUEST_FAILED.value not in initial_text
    assert turn.tool_calls[0].arguments["run_id"] == str(run.run_id)
    assert model._input_items[-1]["type"] == "function_call_output"


def test_live_openai_path_runs_real_bounded_loop_with_fake_client() -> None:
    run, repository = execute_fixture(PresetId.ERP_UNAVAILABLE)
    terminal = next(
        event for event in repository.list_events(run.run_id)
        if event.event_type is EventType.ERP_REQUEST_FAILED
    )
    report = report_for_event(
        run.run_id,
        terminal,
        code=CanonicalErrorCode.ERP_UNAVAILABLE,
        runbook_references=["RB-ERP-UNAVAILABLE"],
    ).model_copy(update={"recommended_action": RecoveryAction.RETRY_SAME_INPUT})
    responses = [
        response(
            output=[
                function_call("overview", "get_run_overview", {"run_id": str(run.run_id)}),
                function_call(
                    "events",
                    "get_run_events",
                    {"run_id": str(run.run_id), "stage": None, "limit": 50},
                ),
            ]
        ),
        response(
            output=[
                function_call(
                    "artifact",
                    "get_stage_artifact",
                    {"run_id": str(run.run_id), "artifact_type": "ERP"},
                ),
                function_call(
                    "runbook",
                    "search_runbook",
                    {"query": "ERP unavailable HTTP 503", "error_code": "ERP_UNAVAILABLE", "limit": 3},
                ),
            ]
        ),
        response(report=report),
    ]
    client = FakeClient(responses)

    completed = Investigator(repository, LocalRunbook()).investigate(
        run.run_id, OpenAIInvestigatorModel(client=client)
    )

    assert completed.report_id == report.report_id
    assert len(client.responses.calls) == 3
    assert [call.tool_name for call in repository.list_investigation_tool_calls(run.run_id)] == [
        "get_run_overview",
        "get_run_events",
        "get_stage_artifact",
        "search_runbook",
    ]
    final = repository.get_run(run.run_id)
    assert final.investigation_state is InvestigationState.COMPLETED
    assert final.investigation_provider_mode is ProviderMode.LIVE
    assert final.recovery_state is RecoveryState.NONE


def test_investigator_specific_model_override_falls_back_cleanly(monkeypatch) -> None:
    monkeypatch.setenv("TRACEGUARD_OPENAI_MODEL", "shared-model")
    monkeypatch.delenv("TRACEGUARD_OPENAI_INVESTIGATOR_MODEL", raising=False)
    shared = OpenAIInvestigatorModel(client=FakeClient())
    assert shared.model == "shared-model"

    monkeypatch.setenv("TRACEGUARD_OPENAI_INVESTIGATOR_MODEL", "investigator-model")
    specific = OpenAIInvestigatorModel(client=FakeClient())
    assert specific.model == "investigator-model"


def test_missing_key_refusal_timeout_request_and_malformed_outputs_fail_safely(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(InvestigatorModelError, match="OPENAI_API_KEY"):
        OpenAIInvestigatorModel()

    context = InvestigationStartContext(run_id=uuid4(), max_model_turns=3, max_tool_calls=6)
    for error, expected in [
        (TimeoutError("secret"), InvestigatorModelTimeoutError),
        (RuntimeError("api_key=secret"), InvestigatorModelError),
    ]:
        model = OpenAIInvestigatorModel(client=FakeClient(error=error))
        model.start(context, ())
        with pytest.raises(expected) as raised:
            model.next_turn()
        assert "secret" not in str(raised.value)

    refusal = response(
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])]
    )
    refused_model = OpenAIInvestigatorModel(client=FakeClient([refusal]))
    refused_model.start(context, ())
    assert refused_model.next_turn().refused

    malformed = response(report={"unexpected": True})
    malformed_model = OpenAIInvestigatorModel(client=FakeClient([malformed]))
    malformed_model.start(context, ())
    with pytest.raises(InvestigatorModelResponseError):
        malformed_model.next_turn()
