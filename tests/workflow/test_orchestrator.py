from traceguard.domain.enums import (
    CanonicalErrorCode,
    EventOutcome,
    FailureCategory,
    InvestigationState,
    RecoveryState,
    WorkflowState,
)
from traceguard.domain.models import ValidatedOrder
from traceguard.extraction import ScriptedExtractionProvider
from traceguard.workflow.erp import MockErp
from traceguard.workflow.fixtures import SCENARIO_FIXTURES, ScenarioFixture
from traceguard.workflow.models import (
    EventSeverity,
    EventType,
    MockErpBehavior,
    PresetId,
    ProviderMode,
    StageArtifactType,
    WorkflowRun,
)
from traceguard.workflow.orchestrator import WorkflowOrchestrator
from traceguard.workflow.repository import InMemoryTraceRepository


class StubExtractionProvider:
    mode = ProviderMode.SCRIPTED

    def __init__(
        self,
        output: object = None,
        *,
        observed_text: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output
        self.observed_text = observed_text
        self.error = error

    def extract(self, text: str) -> object:
        if self.error is not None:
            raise self.error
        if self.observed_text is not None:
            self.observed_text.append(text)
        return self.output


def fixture_provider(
    fixture: ScenarioFixture,
    observed_text: list[str] | None = None,
) -> StubExtractionProvider:
    return StubExtractionProvider(
        fixture.expected_extraction_result.model_dump(mode="json"),
        observed_text=observed_text,
    )


def execute_fixture(
    fixture: ScenarioFixture,
) -> tuple[WorkflowRun, InMemoryTraceRepository, MockErp]:
    repository = InMemoryTraceRepository()
    erp = MockErp(repository)
    run = WorkflowOrchestrator(repository, erp).execute(
        order_request_text=fixture.order_request_text,
        preset_id=fixture.preset_id,
        mock_erp_behavior=fixture.mock_erp_behavior,
        provider=ScriptedExtractionProvider(),
    )
    return run, repository, erp


def test_exactly_four_editable_fixture_definitions_exist() -> None:
    assert set(SCENARIO_FIXTURES) == set(PresetId)
    assert len(SCENARIO_FIXTURES) == 4
    assert all(fixture.order_request_text for fixture in SCENARIO_FIXTURES.values())


def test_success_reaches_succeeded_without_failure_facts() -> None:
    run, repository, _ = execute_fixture(SCENARIO_FIXTURES[PresetId.SUCCESS])

    assert run.workflow_state is WorkflowState.SUCCEEDED
    assert run.extraction_provider_mode is ProviderMode.SCRIPTED
    assert run.investigation_state is InvestigationState.NOT_REQUIRED
    assert run.recovery_state is RecoveryState.NONE
    assert run.canonical_failure_code is None
    assert run.canonical_failure_category is None
    assert run.failure_stage is None
    assert run.erp_attempt_count == 1
    assert repository.list_erp_attempts(run.run_id)[0].status_code == 200
    assert [
        artifact.artifact_type
        for artifact in repository.list_stage_artifacts(run.run_id)
    ] == [
        StageArtifactType.EXTRACTION,
        StageArtifactType.STRUCTURAL_VALIDATION,
        StageArtifactType.DOMAIN_VALIDATION,
        StageArtifactType.BUSINESS_VALIDATION,
        StageArtifactType.ERP,
    ]


def test_missing_customer_fails_during_domain_validation() -> None:
    run, repository, _ = execute_fixture(
        SCENARIO_FIXTURES[PresetId.MISSING_CUSTOMER]
    )

    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.DOMAIN_VALIDATING
    assert run.canonical_failure_code is CanonicalErrorCode.CUSTOMER_NUMBER_MISSING
    assert (
        run.canonical_failure_category
        is FailureCategory.DOMAIN_VALIDATION_FAILURE
    )
    assert run.erp_attempt_count == 0
    assert [
        artifact.artifact_type
        for artifact in repository.list_stage_artifacts(run.run_id)
    ] == [
        StageArtifactType.EXTRACTION,
        StageArtifactType.STRUCTURAL_VALIDATION,
        StageArtifactType.DOMAIN_VALIDATION,
    ]


def test_invalid_quantity_fails_during_business_rule_validation() -> None:
    run, repository, _ = execute_fixture(
        SCENARIO_FIXTURES[PresetId.INVALID_QUANTITY]
    )

    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.BUSINESS_VALIDATING
    assert run.canonical_failure_code is CanonicalErrorCode.QUANTITY_NON_POSITIVE
    assert run.canonical_failure_category is FailureCategory.BUSINESS_RULE_VIOLATION
    assert run.erp_attempt_count == 0
    event_types = [event.event_type for event in repository.list_events(run.run_id)]
    assert EventType.DOMAIN_VALIDATION_COMPLETED in event_types
    assert EventType.BUSINESS_VALIDATION_FAILED in event_types


def test_erp_unavailable_records_noise_then_terminal_503() -> None:
    run, repository, _ = execute_fixture(
        SCENARIO_FIXTURES[PresetId.ERP_UNAVAILABLE]
    )

    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.ERP_CALLING
    assert run.erp_attempt_count == 1
    assert run.canonical_failure_code is CanonicalErrorCode.ERP_UNAVAILABLE
    assert (
        run.canonical_failure_category
        is FailureCategory.EXTERNAL_TRANSIENT_FAILURE
    )
    attempts = repository.list_erp_attempts(run.run_id)
    assert len(attempts) == 1
    assert attempts[0].status_code == 503
    assert not attempts[0].succeeded

    relevant_types = {
        EventType.OPTIONAL_FIELD_DEFAULTED,
        EventType.CACHE_LOOKUP_FAILED,
        EventType.CACHE_FALLBACK_SUCCEEDED,
        EventType.ERP_REQUEST_FAILED,
    }
    relevant_events = [
        event
        for event in repository.list_events(run.run_id)
        if event.event_type in relevant_types
    ]
    assert [event.event_type for event in relevant_events] == [
        EventType.OPTIONAL_FIELD_DEFAULTED,
        EventType.CACHE_LOOKUP_FAILED,
        EventType.CACHE_FALLBACK_SUCCEEDED,
        EventType.ERP_REQUEST_FAILED,
    ]
    assert relevant_events[0].severity is EventSeverity.WARNING
    assert relevant_events[0].outcome is EventOutcome.CONTINUED
    assert relevant_events[1].severity is EventSeverity.WARNING
    assert relevant_events[1].outcome is EventOutcome.RECOVERED
    assert relevant_events[2].outcome is EventOutcome.SUCCESS
    assert relevant_events[3].severity is EventSeverity.ERROR
    assert relevant_events[3].outcome is EventOutcome.TERMINAL
    assert run.canonical_failure_code is not CanonicalErrorCode.ERP_REJECTED


def test_erp_noise_uses_actual_order_facts_not_preset_identity() -> None:
    repository = InMemoryTraceRepository()
    erp = MockErp(repository)
    run = WorkflowOrchestrator(repository, erp).execute(
        order_request_text=(
            "Edited request for CUST-3003 with explicit delivery instructions."
        ),
        preset_id=PresetId.ERP_UNAVAILABLE,
        mock_erp_behavior=MockErpBehavior.FAIL_ONCE_503,
        provider=StubExtractionProvider({
            "customer_number": "CUST-3003",
            "product_code": "SKU-PUMP-9",
            "quantity": 6,
            "delivery_instructions": "Deliver to loading bay 4.",
        }),
    )

    event_types = [
        event.event_type for event in repository.list_events(run.run_id)
    ]
    assert EventType.OPTIONAL_FIELD_DEFAULTED not in event_types
    relevant_types = {
        EventType.CACHE_LOOKUP_FAILED,
        EventType.CACHE_FALLBACK_SUCCEEDED,
        EventType.ERP_REQUEST_FAILED,
    }
    assert [event_type for event_type in event_types if event_type in relevant_types] == [
        EventType.CACHE_LOOKUP_FAILED,
        EventType.CACHE_FALLBACK_SUCCEEDED,
        EventType.ERP_REQUEST_FAILED,
    ]
    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.ERP_CALLING
    assert run.canonical_failure_code is CanonicalErrorCode.ERP_UNAVAILABLE
    assert (
        run.canonical_failure_category
        is FailureCategory.EXTERNAL_TRANSIENT_FAILURE
    )


def test_fail_once_mock_erp_would_succeed_on_second_total_attempt() -> None:
    run, repository, erp = execute_fixture(
        SCENARIO_FIXTURES[PresetId.ERP_UNAVAILABLE]
    )

    second = erp.submit(
        run.run_id,
        ValidatedOrder(
            customer_number="CUST-3003",
            product_code="SKU-PUMP-9",
            quantity=6,
        ),
    )

    assert second.attempt.attempt_number == 2
    assert second.attempt.succeeded
    assert second.attempt.status_code == 200
    assert repository.get_run(run.run_id).erp_attempt_count == 2
    assert repository.get_run(run.run_id).workflow_state is WorkflowState.FAILED


def test_preset_id_is_metadata_and_editable_text_is_passed_unchanged() -> None:
    repository = InMemoryTraceRepository()
    erp = MockErp(repository)
    observed_text: list[str] = []
    custom_text = (
        "Edited request: customer CUST-9009 needs 1 unit of SKU-CUSTOM."
    )
    valid_fixture = SCENARIO_FIXTURES[PresetId.SUCCESS]

    run = WorkflowOrchestrator(repository, erp).execute(
        order_request_text=custom_text,
        preset_id=PresetId.MISSING_CUSTOMER,
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        provider=fixture_provider(valid_fixture, observed_text),
    )

    assert run.preset_id is PresetId.MISSING_CUSTOMER
    assert run.order_request_text == custom_text
    assert observed_text == [custom_text]
    assert run.workflow_state is WorkflowState.SUCCEEDED
    assert run.canonical_failure_code is None


def test_extraction_dependency_failure_is_sanitized_and_deterministic() -> None:
    repository = InMemoryTraceRepository()
    erp = MockErp(repository)

    run = WorkflowOrchestrator(repository, erp).execute(
        order_request_text="A request whose extraction dependency fails.",
        preset_id=None,
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        provider=StubExtractionProvider(
            error=RuntimeError("api_key=super-secret provider detail")
        ),
    )

    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.EXTRACTING
    assert run.canonical_failure_code is CanonicalErrorCode.EXTRACTION_MODEL_ERROR
    assert run.canonical_failure_category is FailureCategory.EXTRACTION_FAILURE
    assert run.erp_attempt_count == 0
    rendered_events = " ".join(
        event.details for event in repository.list_events(run.run_id)
    )
    extraction_artifact = repository.get_latest_stage_artifact(
        run.run_id, StageArtifactType.EXTRACTION
    )
    assert "super-secret" not in rendered_events
    assert "super-secret" not in str(extraction_artifact.data)
    assert extraction_artifact.data["status"] == "failed"


def test_structural_failure_uses_existing_phase_one_validation_boundary() -> None:
    repository = InMemoryTraceRepository()
    erp = MockErp(repository)
    run = WorkflowOrchestrator(repository, erp).execute(
        order_request_text="Quantity was extracted with an invalid type.",
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        provider=StubExtractionProvider({
            "customer_number": "C-1",
            "product_code": "SKU-1",
            "quantity": "three",
        }),
    )

    assert run.workflow_state is WorkflowState.FAILED
    assert run.failure_stage is WorkflowState.STRUCTURE_VALIDATING
    assert run.canonical_failure_code is CanonicalErrorCode.ORDER_STRUCTURE_INVALID
    assert (
        run.canonical_failure_category
        is FailureCategory.STRUCTURAL_VALIDATION_FAILURE
    )
