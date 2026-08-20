import json

import pytest
from fastapi.testclient import TestClient

from traceguard.api import create_app, create_services
from traceguard.domain.enums import DiagnosticToolName, ProviderMode
from traceguard.extraction import ScriptedExtractionProvider
from traceguard.investigation import TOOL_NAMES
from traceguard.workflow.fixtures import SCENARIO_FIXTURES
from traceguard.workflow.models import PresetId


@pytest.fixture
def api():
    services = create_services(sleeper=lambda _: None)
    with TestClient(create_app(services)) as client:
        yield client, services


def _run_fixture(client: TestClient, preset_id: PresetId):
    fixture = SCENARIO_FIXTURES[preset_id]
    response = client.post(
        "/api/runs",
        json={
            "order_request_text": fixture.order_request_text,
            "preset_id": fixture.preset_id.value,
            "mock_erp_behavior": fixture.mock_erp_behavior.value,
            "extraction_provider_mode": "SCRIPTED",
        },
    )
    assert response.status_code == 201
    return response.json()


def _investigate(client: TestClient, run_id: str):
    response = client.post(
        f"/api/runs/{run_id}/investigate",
        json={"investigation_provider_mode": "SCRIPTED"},
    )
    assert response.status_code == 200
    return response.json()


def test_page_and_assets_expose_single_thin_ui_contract(api):
    client, _ = api
    page = client.get("/")
    script = client.get("/assets/app.js")
    styles = client.get("/assets/styles.css")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "TraceGuard" in page.text
    assert "Agent recommends" in page.text
    assert "Deterministic policy authorizes" in page.text
    assert "Workflow" in page.text and "Investigation" in page.text and "Recovery" in page.text
    retired_term = "REQUIRE_" + "APPROVAL"
    assert retired_term not in page.text + script.text
    assert "get_run_overview" not in script.text
    assert "data-outcome" in script.text
    assert '[data-outcome="TERMINAL"]' in styles.text
    assert "npm" not in page.text.lower()


def test_presets_expose_exactly_four_editable_fixture_payloads(api):
    client, _ = api
    response = client.get("/api/presets")
    assert response.status_code == 200
    presets = response.json()["presets"]
    assert [item["preset_id"] for item in presets] == [item.value for item in PresetId]
    assert len(presets) == 4
    for item in presets:
        fixture = SCENARIO_FIXTURES[PresetId(item["preset_id"])]
        assert item["order_request_text"] == fixture.order_request_text
        assert item["mock_erp_behavior"] == fixture.mock_erp_behavior.value


@pytest.mark.parametrize(
    ("preset_id", "workflow", "error", "stage", "attempts"),
    [
        (PresetId.SUCCESS, "SUCCEEDED", None, None, 1),
        (PresetId.MISSING_CUSTOMER, "FAILED", "CUSTOMER_NUMBER_MISSING", "DOMAIN_VALIDATING", 0),
        (PresetId.INVALID_QUANTITY, "FAILED", "QUANTITY_NON_POSITIVE", "BUSINESS_VALIDATING", 0),
        (PresetId.ERP_UNAVAILABLE, "FAILED", "ERP_UNAVAILABLE", "ERP_CALLING", 1),
    ],
)
def test_all_four_scripted_workflows(preset_id, workflow, error, stage, attempts, api):
    client, _ = api
    run = _run_fixture(client, preset_id)
    assert run["workflow_state"] == workflow
    assert run["canonical_failure_code"] == error
    assert run["failure_stage"] == stage
    assert run["erp_attempt_count"] == attempts
    assert run["extraction_provider_mode"] == "SCRIPTED"


def test_submitted_text_and_explicit_behavior_are_retained(api):
    client, _ = api
    fixture = SCENARIO_FIXTURES[PresetId.SUCCESS]
    run = _run_fixture(client, PresetId.SUCCESS)
    aggregate = client.get(f"/api/runs/{run['run_id']}").json()
    assert aggregate["run"]["order_request_text"] == fixture.order_request_text
    assert aggregate["run"]["mock_erp_behavior"] == "SUCCEED"
    assert aggregate["run"]["preset_id"] == "SUCCESS"


def test_edited_fixture_in_scripted_mode_requires_live_and_is_not_reset(api):
    client, _ = api
    fixture = SCENARIO_FIXTURES[PresetId.SUCCESS]
    edited = fixture.order_request_text + "!"
    response = client.post(
        "/api/runs",
        json={
            "order_request_text": edited,
            "preset_id": "SUCCESS",
            "mock_erp_behavior": "SUCCEED",
            "extraction_provider_mode": "SCRIPTED",
        },
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": "LIVE_PROVIDER_REQUIRED",
        "message": "Scripted extraction supports exact demo fixtures only. Edited or custom input requires LIVE mode.",
    }
    assert edited not in response.text


def test_live_missing_key_fails_safely_without_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    services = create_services(sleeper=lambda _: None)
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/runs",
            json={
                "order_request_text": "A genuine custom order for one item.",
                "preset_id": None,
                "mock_erp_behavior": "SUCCEED",
                "extraction_provider_mode": "LIVE",
            },
        )
    assert response.status_code == 503
    assert response.json()["error"] == "LIVE_PROVIDER_UNAVAILABLE"
    assert "OPENAI_API_KEY" not in response.text
    assert "sk-" not in response.text


def test_custom_live_text_reaches_injected_provider_unchanged():
    captured = []

    class FakeLiveProvider:
        mode = ProviderMode.LIVE

        def extract(self, order_request_text: str) -> object:
            captured.append(order_request_text)
            return {
                "customer_number": "C-LIVE",
                "product_code": "SKU-LIVE",
                "quantity": 2,
                "delivery_instructions": None,
            }

    services = create_services(
        sleeper=lambda _: None,
        extraction_provider_factories={
            ProviderMode.SCRIPTED: ScriptedExtractionProvider,
            ProviderMode.LIVE: FakeLiveProvider,
        },
    )
    custom = "  Custom text with preserved spacing and punctuation?!  "
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/runs",
            json={
                "order_request_text": custom,
                "preset_id": "MISSING_CUSTOMER",
                "mock_erp_behavior": "SUCCEED",
                "extraction_provider_mode": "LIVE",
            },
        )
        aggregate = client.get(f"/api/runs/{response.json()['run_id']}").json()
    assert response.status_code == 201
    assert response.json()["workflow_state"] == "SUCCEEDED"
    assert captured == [custom]
    assert aggregate["run"]["order_request_text"] == custom


def test_provider_secret_exception_is_not_exposed_or_stored():
    class FailingLiveProvider:
        mode = ProviderMode.LIVE

        def extract(self, order_request_text: str) -> object:
            raise RuntimeError("sk-secret-provider-body")

    services = create_services(
        sleeper=lambda _: None,
        extraction_provider_factories={
            ProviderMode.SCRIPTED: ScriptedExtractionProvider,
            ProviderMode.LIVE: FailingLiveProvider,
        },
    )
    with TestClient(create_app(services)) as client:
        response = client.post(
            "/api/runs",
            json={
                "order_request_text": "Custom failing live input",
                "preset_id": None,
                "mock_erp_behavior": "SUCCEED",
                "extraction_provider_mode": "LIVE",
            },
        )
        aggregate = client.get(f"/api/runs/{response.json()['run_id']}").json()
    assert response.status_code == 201
    assert response.json()["canonical_failure_code"] == "EXTRACTION_MODEL_ERROR"
    assert "sk-secret" not in json.dumps(aggregate)


def test_scripted_investigation_exposes_actual_tool_history_and_report(api):
    client, _ = api
    run = _run_fixture(client, PresetId.ERP_UNAVAILABLE)
    _investigate(client, run["run_id"])
    aggregate = client.get(f"/api/runs/{run['run_id']}").json()

    assert aggregate["run"]["investigation_state"] == "COMPLETED"
    assert aggregate["run"]["investigation_provider_mode"] == "SCRIPTED"
    assert [call["tool_name"] for call in aggregate["investigation_tool_calls"]] == [
        "get_run_overview", "get_run_events", "get_stage_artifact", "search_runbook"
    ]
    assert aggregate["investigation_report"]["diagnosed_error_code"] == "ERP_UNAVAILABLE"
    evidence = aggregate["investigation_report"]["evidence"]
    assert any(item["role"] == "TERMINAL_CAUSE" for item in evidence)
    assert any(item["role"] == "NON_CAUSAL_CONTEXT" for item in evidence)
    event_outcomes = {item["event_type"]: item["outcome"] for item in aggregate["events"]}
    assert event_outcomes["CACHE_LOOKUP_FAILED"] == "RECOVERED"
    assert event_outcomes["ERP_REQUEST_FAILED"] == "TERMINAL"
    assert [item["timestamp"] for item in aggregate["events"]] == sorted(
        item["timestamp"] for item in aggregate["events"]
    )


def test_completed_investigation_cannot_mutate_history_with_second_request(api):
    client, _ = api
    run = _run_fixture(client, PresetId.ERP_UNAVAILABLE)
    _investigate(client, run["run_id"])
    before = client.get(f"/api/runs/{run['run_id']}").json()

    repeated = client.post(
        f"/api/runs/{run['run_id']}/investigate",
        json={"investigation_provider_mode": "SCRIPTED"},
    )
    after = client.get(f"/api/runs/{run['run_id']}").json()

    assert repeated.status_code == 409
    assert after["investigation_tool_calls"] == before["investigation_tool_calls"]
    assert after["investigation_report"] == before["investigation_report"]


def test_successful_run_cannot_be_investigated(api):
    client, _ = api
    run = _run_fixture(client, PresetId.SUCCESS)
    response = client.post(
        f"/api/runs/{run['run_id']}/investigate",
        json={"investigation_provider_mode": "SCRIPTED"},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "OPERATION_CONFLICT"


def test_live_investigation_missing_key_fails_safely(monkeypatch, api):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, _ = api
    run = _run_fixture(client, PresetId.ERP_UNAVAILABLE)
    response = client.post(
        f"/api/runs/{run['run_id']}/investigate",
        json={"investigation_provider_mode": "LIVE"},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "LIVE_PROVIDER_UNAVAILABLE"
    assert "OPENAI_API_KEY" not in response.text


def test_erp_recovery_evaluation_execution_and_duplicate_http_idempotency(api):
    client, _ = api
    run = _run_fixture(client, PresetId.ERP_UNAVAILABLE)
    _investigate(client, run["run_id"])

    evaluated = client.post(f"/api/runs/{run['run_id']}/recovery/evaluate", json={})
    assert evaluated.status_code == 200
    assert evaluated.json()["decision"]["decision"] == "ALLOW"
    assert evaluated.json()["decision"]["allowed_action"] == "RETRY_SAME_INPUT"
    assert evaluated.json()["decision"]["reason_codes"] == ["ELIGIBLE_TRANSIENT_RETRY"]
    assert evaluated.json()["recovery_state"] == "ALLOW"

    recovered = client.post(f"/api/runs/{run['run_id']}/recover", json={})
    assert recovered.status_code == 200
    assert recovered.json()["execution"]["erp_attempt_number"] == 2
    assert recovered.json()["execution"]["status"] == "SUCCEEDED"
    assert recovered.json()["recovery_state"] == "RECOVERED"
    assert recovered.json()["idempotent_replay"] is False

    duplicate = client.post(f"/api/runs/{run['run_id']}/recover", json={})
    aggregate = client.get(f"/api/runs/{run['run_id']}").json()
    assert duplicate.status_code == 200
    assert duplicate.json()["idempotent_replay"] is True
    assert duplicate.json()["execution"]["execution_id"] == recovered.json()["execution"]["execution_id"]
    assert aggregate["run"]["workflow_state"] == "FAILED"
    assert aggregate["run"]["recovery_state"] == "RECOVERED"
    assert aggregate["run"]["erp_attempt_count"] == 2
    assert len(aggregate["erp_attempts"]) == 2


@pytest.mark.parametrize(
    ("preset_id", "decision", "reason"),
    [
        (PresetId.MISSING_CUSTOMER, "REQUIRE_REVIEW", "HUMAN_INPUT_REQUIRED"),
        (PresetId.INVALID_QUANTITY, "BLOCK", "NON_RETRYABLE_BUSINESS_RULE"),
    ],
)
def test_non_executable_policy_paths_make_no_erp_call(preset_id, decision, reason, api):
    client, _ = api
    run = _run_fixture(client, preset_id)
    _investigate(client, run["run_id"])
    evaluated = client.post(f"/api/runs/{run['run_id']}/recovery/evaluate", json={})
    triggered = client.post(f"/api/runs/{run['run_id']}/recover", json={})
    aggregate = client.get(f"/api/runs/{run['run_id']}").json()

    assert evaluated.json()["decision"]["decision"] == decision
    assert evaluated.json()["decision"]["reason_codes"] == [reason]
    assert triggered.status_code == 200
    assert triggered.json()["execution"] is None
    assert aggregate["run"]["recovery_state"] == decision
    assert aggregate["run"]["erp_attempt_count"] == 0
    assert aggregate["erp_attempts"] == []


def test_server_owned_authority_fields_are_rejected(api):
    client, _ = api
    fixture = SCENARIO_FIXTURES[PresetId.SUCCESS]
    response = client.post(
        "/api/runs",
        json={
            "order_request_text": fixture.order_request_text,
            "preset_id": "SUCCESS",
            "mock_erp_behavior": "SUCCEED",
            "extraction_provider_mode": "SCRIPTED",
            "canonical_failure_code": "ERP_UNAVAILABLE",
            "workflow_state": "FAILED",
            "recovery_state": "ALLOW",
            "idempotency_key": "caller-key",
            "erp_attempt_count": 1,
            "policy_decision": "ALLOW",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "INVALID_REQUEST"
    assert "caller-key" not in response.text


def test_recovery_and_investigation_payloads_reject_caller_authority(api):
    client, _ = api
    run = _run_fixture(client, PresetId.ERP_UNAVAILABLE)
    investigate = client.post(
        f"/api/runs/{run['run_id']}/investigate",
        json={
            "investigation_provider_mode": "SCRIPTED",
            "diagnosed_error_code": "ERP_UNAVAILABLE",
            "recommended_action": "RETRY_SAME_INPUT",
        },
    )
    recover = client.post(
        f"/api/runs/{run['run_id']}/recover",
        json={"allowed_action": "RETRY_SAME_INPUT", "idempotency_key": "caller"},
    )
    assert investigate.status_code == 400
    assert recover.status_code == 400


def test_unknown_run_is_404_and_registry_remains_exactly_read_only(api):
    client, _ = api
    response = client.get("/api/runs/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404
    assert TOOL_NAMES == tuple(tool.value for tool in DiagnosticToolName)
    assert set(TOOL_NAMES) == {
        "get_run_overview", "get_run_events", "get_stage_artifact", "search_runbook"
    }
