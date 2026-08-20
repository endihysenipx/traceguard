from uuid import UUID, uuid4

from traceguard.domain.enums import (
    CANONICAL_FAILURE_CATEGORY,
    CanonicalErrorCode,
    Confidence,
    EvidenceRole,
    ProviderMode,
    RecoveryAction,
)
from traceguard.domain.models import EvidenceItem, InvestigationReport
from traceguard.extraction import ScriptedExtractionProvider
from traceguard.investigation.models import (
    InvestigationStartContext,
    InvestigatorTurn,
    ToolCallResult,
)
from traceguard.workflow.erp import MockErp
from traceguard.workflow.fixtures import SCENARIO_FIXTURES
from traceguard.workflow.models import PresetId, TraceEvent, WorkflowRun
from traceguard.workflow.orchestrator import WorkflowOrchestrator
from traceguard.workflow.repository import InMemoryTraceRepository


def execute_fixture(
    preset_id: PresetId,
) -> tuple[WorkflowRun, InMemoryTraceRepository]:
    fixture = SCENARIO_FIXTURES[preset_id]
    repository = InMemoryTraceRepository()
    run = WorkflowOrchestrator(repository, MockErp(repository)).execute(
        order_request_text=fixture.order_request_text,
        preset_id=fixture.preset_id,
        mock_erp_behavior=fixture.mock_erp_behavior,
        provider=ScriptedExtractionProvider(),
    )
    return run, repository


def report_for_event(
    run_id: UUID,
    event: TraceEvent,
    *,
    code: CanonicalErrorCode,
    role: EvidenceRole = EvidenceRole.TERMINAL_CAUSE,
    runbook_references: list[str] | None = None,
) -> InvestigationReport:
    return InvestigationReport(
        report_id=uuid4(),
        run_id=run_id,
        failure_category=CANONICAL_FAILURE_CATEGORY[code],
        diagnosed_error_code=code,
        root_cause="Evidence-grounded test diagnosis.",
        evidence=[
            EvidenceItem(
                event_id=event.event_id,
                role=role,
                observation="The cited event supports this test diagnosis.",
            )
        ],
        recommended_action=RecoveryAction.NO_ACTION,
        rationale="This is a recommendation only.",
        confidence=Confidence.HIGH,
        runbook_references=runbook_references or [],
    )


class SequenceInvestigatorModel:
    mode = ProviderMode.LIVE

    def __init__(self, turns: list[InvestigatorTurn | Exception]) -> None:
        self.turns = list(turns)
        self.context: InvestigationStartContext | None = None
        self.tool_definitions: tuple[dict[str, object], ...] = ()
        self.submitted_results: list[tuple[ToolCallResult, ...]] = []
        self.turn_count = 0

    def start(
        self,
        context: InvestigationStartContext,
        tool_definitions: tuple[dict[str, object], ...],
    ) -> None:
        self.context = context
        self.tool_definitions = tool_definitions

    def next_turn(self) -> InvestigatorTurn:
        self.turn_count += 1
        value = self.turns.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def submit_tool_results(self, results: tuple[ToolCallResult, ...]) -> None:
        self.submitted_results.append(results)
