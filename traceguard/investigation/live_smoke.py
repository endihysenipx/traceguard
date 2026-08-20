"""Opt-in real investigator smoke: python -m traceguard.investigation.live_smoke."""

import os

from traceguard.extraction import ScriptedExtractionProvider
from traceguard.investigation.investigator import Investigator
from traceguard.investigation.openai_model import OpenAIInvestigatorModel
from traceguard.investigation.runbook import LocalRunbook
from traceguard.workflow import InMemoryTraceRepository, MockErp, WorkflowOrchestrator
from traceguard.workflow.fixtures import SCENARIO_FIXTURES
from traceguard.workflow.models import PresetId


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("SKIPPED: OPENAI_API_KEY is not configured; no external call was made.")
        return 0
    fixture = SCENARIO_FIXTURES[PresetId.ERP_UNAVAILABLE]
    repository = InMemoryTraceRepository()
    run = WorkflowOrchestrator(repository, MockErp(repository)).execute(
        order_request_text=fixture.order_request_text,
        preset_id=fixture.preset_id,
        mock_erp_behavior=fixture.mock_erp_behavior,
        provider=ScriptedExtractionProvider(),
    )
    report = Investigator(repository, LocalRunbook()).investigate(
        run.run_id, OpenAIInvestigatorModel()
    )
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
