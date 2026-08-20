"""Legal transitions for the three orthogonal state machines."""

from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from traceguard.domain.enums import InvestigationState, RecoveryState, WorkflowState
from traceguard.domain.errors import IllegalStateTransition


WORKFLOW_TRANSITIONS: Mapping[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.CREATED: frozenset({WorkflowState.EXTRACTING}),
    WorkflowState.EXTRACTING: frozenset(
        {WorkflowState.STRUCTURE_VALIDATING, WorkflowState.FAILED}
    ),
    WorkflowState.STRUCTURE_VALIDATING: frozenset(
        {WorkflowState.DOMAIN_VALIDATING, WorkflowState.FAILED}
    ),
    WorkflowState.DOMAIN_VALIDATING: frozenset(
        {WorkflowState.BUSINESS_VALIDATING, WorkflowState.FAILED}
    ),
    WorkflowState.BUSINESS_VALIDATING: frozenset(
        {WorkflowState.ERP_CALLING, WorkflowState.FAILED}
    ),
    WorkflowState.ERP_CALLING: frozenset(
        {WorkflowState.SUCCEEDED, WorkflowState.FAILED}
    ),
    WorkflowState.SUCCEEDED: frozenset(),
    WorkflowState.FAILED: frozenset(),
}

INVESTIGATION_TRANSITIONS: Mapping[InvestigationState, frozenset[InvestigationState]] = {
    InvestigationState.NOT_REQUIRED: frozenset({InvestigationState.PENDING}),
    InvestigationState.PENDING: frozenset({InvestigationState.RUNNING}),
    InvestigationState.RUNNING: frozenset(
        {InvestigationState.COMPLETED, InvestigationState.FAILED}
    ),
    InvestigationState.COMPLETED: frozenset(),
    InvestigationState.FAILED: frozenset(),
}

RECOVERY_TRANSITIONS: Mapping[RecoveryState, frozenset[RecoveryState]] = {
    RecoveryState.NONE: frozenset(
        {RecoveryState.ALLOW, RecoveryState.BLOCK, RecoveryState.REQUIRE_REVIEW}
    ),
    RecoveryState.ALLOW: frozenset({RecoveryState.RETRYING, RecoveryState.BLOCK}),
    RecoveryState.RETRYING: frozenset(
        {RecoveryState.RECOVERED, RecoveryState.RETRY_EXHAUSTED}
    ),
    RecoveryState.BLOCK: frozenset(),
    RecoveryState.REQUIRE_REVIEW: frozenset(),
    RecoveryState.RECOVERED: frozenset(),
    RecoveryState.RETRY_EXHAUSTED: frozenset(),
}

StateT = TypeVar("StateT", bound=StrEnum)


def ensure_workflow_transition(current: WorkflowState, target: WorkflowState) -> None:
    _ensure_transition("workflow", current, target, WORKFLOW_TRANSITIONS)


def ensure_investigation_transition(
    current: InvestigationState, target: InvestigationState
) -> None:
    _ensure_transition("investigation", current, target, INVESTIGATION_TRANSITIONS)


def ensure_recovery_transition(current: RecoveryState, target: RecoveryState) -> None:
    _ensure_transition("recovery", current, target, RECOVERY_TRANSITIONS)


def _ensure_transition(
    machine: str,
    current: StateT,
    target: StateT,
    transitions: Mapping[StateT, frozenset[StateT]],
) -> None:
    if target not in transitions[current]:
        raise IllegalStateTransition(machine, current.value, target.value)

