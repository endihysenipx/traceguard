"""Deterministic domain exceptions with machine-readable facts."""

from traceguard.domain.enums import CanonicalErrorCode, FailureCategory


class WorkflowValidationError(ValueError):
    """A canonical validation failure produced by deterministic workflow logic."""

    def __init__(
        self,
        *,
        category: FailureCategory,
        code: CanonicalErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code


class IllegalStateTransition(ValueError):
    """Raised when a deterministic state machine transition is not legal."""

    def __init__(self, machine: str, current: str, target: str) -> None:
        super().__init__(f"Illegal {machine} transition: {current} -> {target}")
        self.machine = machine
        self.current = current
        self.target = target

