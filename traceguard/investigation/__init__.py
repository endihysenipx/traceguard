"""Bounded workflow-failure investigation components."""

from traceguard.investigation.runbook import LocalRunbook, RunbookEntry
from traceguard.investigation.investigator import (
    MAX_MODEL_TURNS,
    MAX_TOOL_CALLS,
    InvestigationFailedError,
    InvestigationNotAllowedError,
    Investigator,
)
from traceguard.investigation.openai_model import OpenAIInvestigatorModel
from traceguard.investigation.scripted import ScriptedInvestigatorModel
from traceguard.investigation.tools import DiagnosticToolRegistry, TOOL_NAMES
from traceguard.investigation.validation import (
    InvestigationReportValidationError,
    validate_investigation_report,
)

__all__ = [
    "DiagnosticToolRegistry",
    "InvestigationFailedError",
    "InvestigationNotAllowedError",
    "InvestigationReportValidationError",
    "LocalRunbook",
    "MAX_MODEL_TURNS",
    "MAX_TOOL_CALLS",
    "OpenAIInvestigatorModel",
    "RunbookEntry",
    "ScriptedInvestigatorModel",
    "TOOL_NAMES",
    "validate_investigation_report",
    "Investigator",
]
