from collections.abc import Callable, Mapping
from enum import StrEnum

import pytest

from traceguard.domain.enums import InvestigationState, RecoveryState, WorkflowState
from traceguard.domain.errors import IllegalStateTransition
from traceguard.domain.transitions import (
    INVESTIGATION_TRANSITIONS,
    RECOVERY_TRANSITIONS,
    WORKFLOW_TRANSITIONS,
    ensure_investigation_transition,
    ensure_recovery_transition,
    ensure_workflow_transition,
)


@pytest.mark.parametrize(
    ("states", "transitions", "ensure"),
    [
        (WorkflowState, WORKFLOW_TRANSITIONS, ensure_workflow_transition),
        (
            InvestigationState,
            INVESTIGATION_TRANSITIONS,
            ensure_investigation_transition,
        ),
        (RecoveryState, RECOVERY_TRANSITIONS, ensure_recovery_transition),
    ],
)
def test_every_state_pair_matches_declared_transition_table(
    states: type[StrEnum],
    transitions: Mapping[StrEnum, frozenset[StrEnum]],
    ensure: Callable[[StrEnum, StrEnum], None],
) -> None:
    assert set(transitions) == set(states)

    for current in states:
        for target in states:
            if target in transitions[current]:
                ensure(current, target)
            else:
                with pytest.raises(IllegalStateTransition):
                    ensure(current, target)


def test_illegal_transition_exposes_machine_and_states() -> None:
    with pytest.raises(IllegalStateTransition) as raised:
        ensure_workflow_transition(WorkflowState.CREATED, WorkflowState.SUCCEEDED)

    assert raised.value.machine == "workflow"
    assert raised.value.current == WorkflowState.CREATED
    assert raised.value.target == WorkflowState.SUCCEEDED

