from types import SimpleNamespace

import pytest

from traceguard.domain.enums import CanonicalErrorCode, WorkflowState
from traceguard.extraction import (
    DEFAULT_OPENAI_MODEL,
    ExtractionProviderRequestError,
    ExtractionProviderTimeoutError,
    ExtractionRefusalError,
    MalformedProviderResponseError,
    OpenAIExtractionProvider,
    OpenAIOrderExtraction,
    ProviderConfigurationError,
)
from traceguard.workflow.erp import MockErp
from traceguard.workflow.models import (
    MockErpBehavior,
    ProviderMode,
    StageArtifactType,
)
from traceguard.workflow.orchestrator import WorkflowOrchestrator
from traceguard.workflow.repository import InMemoryTraceRepository


class FakeResponses:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.responses = FakeResponses(response, error)


class InvalidStructureProvider:
    mode = ProviderMode.LIVE

    def extract(self, order_request_text: str) -> object:
        return {
            "customer_number": "C-1",
            "product_code": "SKU-1",
            "quantity": "three",
            "delivery_instructions": None,
        }


def parsed_response(**overrides: object) -> object:
    values: dict[str, object] = {
        "customer_number": "CUST-42",
        "product_code": "SKU-9",
        "quantity": 3,
        "delivery_instructions": None,
    }
    values.update(overrides)
    return SimpleNamespace(output_parsed=OpenAIOrderExtraction(**values), output=[])


def test_exact_text_model_schema_and_timeout_are_sent_to_responses_api() -> None:
    text = "  Keep this submitted text exactly, including spacing.  "
    client = FakeClient(parsed_response())
    provider = OpenAIExtractionProvider(
        client=client, model="configured-extraction-model", timeout_seconds=7.5
    )

    result = provider.extract(text)

    call = client.responses.calls[0]
    assert provider.mode is ProviderMode.LIVE
    assert call["input"] == text
    assert call["model"] == "configured-extraction-model"
    assert call["text_format"] is OpenAIOrderExtraction
    assert call["timeout"] == 7.5
    assert call["store"] is False
    assert "preset_id" not in call
    assert result == {
        "customer_number": "CUST-42",
        "product_code": "SKU-9",
        "quantity": 3,
        "delivery_instructions": None,
    }


def test_default_and_environment_configurable_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACEGUARD_OPENAI_MODEL", raising=False)
    default_provider = OpenAIExtractionProvider(client=FakeClient(parsed_response()))
    assert default_provider.model == DEFAULT_OPENAI_MODEL

    monkeypatch.setenv("TRACEGUARD_OPENAI_MODEL", "env-selected-model")
    client = FakeClient(parsed_response())
    configured = OpenAIExtractionProvider(client=client)
    configured.extract("Exact request")
    assert configured.model == "env-selected-model"
    assert client.responses.calls[0]["model"] == "env-selected-model"


def test_missing_customer_remains_null_and_negative_quantity_is_preserved() -> None:
    client = FakeClient(parsed_response(customer_number=None, quantity=-3))

    result = OpenAIExtractionProvider(client=client).extract("Custom negative order")

    assert result["customer_number"] is None
    assert result["quantity"] == -3


def test_missing_api_key_fails_configuration_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        OpenAIExtractionProvider()


def test_refusal_is_sanitized() -> None:
    refusal = SimpleNamespace(
        output_parsed=None,
        output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])],
    )
    with pytest.raises(ExtractionRefusalError, match="refused"):
        OpenAIExtractionProvider(client=FakeClient(refusal)).extract("request")


def test_timeout_and_request_errors_are_sanitized() -> None:
    with pytest.raises(ExtractionProviderTimeoutError) as timeout_error:
        OpenAIExtractionProvider(client=FakeClient(error=TimeoutError("secret"))).extract(
            "request"
        )
    assert "secret" not in str(timeout_error.value)

    with pytest.raises(ExtractionProviderRequestError) as request_error:
        OpenAIExtractionProvider(
            client=FakeClient(error=RuntimeError("api_key=super-secret"))
        ).extract("request")
    assert "super-secret" not in str(request_error.value)


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(output_parsed=None, output=[]),
        SimpleNamespace(output_parsed={"quantity": 1}, output=[]),
    ],
)
def test_malformed_or_unusable_output_fails_safely(response: object) -> None:
    with pytest.raises(MalformedProviderResponseError):
        OpenAIExtractionProvider(client=FakeClient(response)).extract("request")


def test_invalid_provider_shape_reaches_deterministic_structural_boundary() -> None:
    repository = InMemoryTraceRepository()
    run = WorkflowOrchestrator(repository, MockErp(repository)).execute(
        order_request_text="Quantity is represented with the wrong type.",
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        provider=InvalidStructureProvider(),
    )

    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.STRUCTURE_VALIDATING
    assert run.canonical_failure_code is CanonicalErrorCode.ORDER_STRUCTURE_INVALID


def test_secret_bearing_provider_error_never_reaches_workflow_trace_or_artifact() -> None:
    repository = InMemoryTraceRepository()
    provider = OpenAIExtractionProvider(
        client=FakeClient(error=RuntimeError("OPENAI_API_KEY=super-secret"))
    )
    run = WorkflowOrchestrator(repository, MockErp(repository)).execute(
        order_request_text="A custom request.",
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        provider=provider,
    )

    rendered_events = " ".join(
        event.details for event in repository.list_events(run.run_id)
    )
    artifact = repository.get_latest_stage_artifact(
        run.run_id, StageArtifactType.EXTRACTION
    )
    assert run.canonical_failure_code is CanonicalErrorCode.EXTRACTION_MODEL_ERROR
    assert "super-secret" not in rendered_events
    assert "super-secret" not in str(artifact.data)
