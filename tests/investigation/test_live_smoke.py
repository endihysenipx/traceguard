from types import SimpleNamespace

from traceguard.domain.enums import InvestigationFailureReason
from traceguard.investigation import live_smoke
from traceguard.investigation.investigator import InvestigationFailedError
from traceguard.workflow.models import InvestigationToolCall


def _model() -> SimpleNamespace:
    return SimpleNamespace(model="test-investigator-model")


def _record_tool(investigator, run_id, name: str, sequence: int) -> None:
    investigator._repository.append_investigation_tool_call(
        InvestigationToolCall(
            run_id=run_id,
            sequence_number=sequence,
            tool_name=name,
            arguments={},
            succeeded=True,
            result={},
        )
    )


def test_live_smoke_skips_cleanly_without_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        live_smoke,
        "OpenAIInvestigatorModel",
        lambda: (_ for _ in ()).throw(AssertionError("model must not be created")),
    )

    assert live_smoke.main() == 0
    output = capsys.readouterr().out
    assert output.startswith("SKIPPED:")
    assert "no external call was made" in output


def test_live_smoke_reports_safe_failure_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_smoke, "OpenAIInvestigatorModel", _model)

    def fail_grounding(investigator, run_id, model):
        del model
        _record_tool(investigator, run_id, "get_run_overview", 1)
        _record_tool(investigator, run_id, "get_run_events", 2)
        raise InvestigationFailedError(
            InvestigationFailureReason.REPORT_NOT_GROUNDED
        )

    monkeypatch.setattr(live_smoke.Investigator, "investigate", fail_grounding)

    assert live_smoke.main() == 1
    output = capsys.readouterr().out
    assert "MODEL: test-investigator-model" in output
    assert "SAFE_FAILURE: REPORT_NOT_GROUNDED" in output
    assert "TOOLS: 2 [get_run_overview, get_run_events]" in output
    assert "Traceback" not in output


def test_live_smoke_reports_completed_with_actual_tool_history(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_smoke, "OpenAIInvestigatorModel", _model)

    def complete(investigator, run_id, model):
        del model
        _record_tool(investigator, run_id, "get_run_overview", 1)
        return SimpleNamespace(
            model_dump_json=lambda **kwargs: '{"report":"completed"}'
        )

    monkeypatch.setattr(live_smoke.Investigator, "investigate", complete)

    assert live_smoke.main() == 0
    output = capsys.readouterr().out
    assert "MODEL: test-investigator-model" in output
    assert "COMPLETED" in output
    assert "TOOLS: 1 [get_run_overview]" in output
    assert '{"report":"completed"}' in output
