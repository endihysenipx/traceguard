"""Exact-fixture extraction for reproducible offline demonstrations."""

from traceguard.domain.enums import ProviderMode
from traceguard.extraction.base import UnsupportedScriptedInputError
from traceguard.workflow.fixtures import SCENARIO_FIXTURES


class ScriptedExtractionProvider:
    mode = ProviderMode.SCRIPTED

    def supports(self, order_request_text: str) -> bool:
        """Return whether text is one of the four exact approved fixtures."""

        return any(
            fixture.order_request_text == order_request_text
            for fixture in SCENARIO_FIXTURES.values()
        )

    def extract(self, order_request_text: str) -> object:
        for fixture in SCENARIO_FIXTURES.values():
            if fixture.order_request_text == order_request_text:
                return fixture.expected_extraction_result.model_dump(mode="json")
        raise UnsupportedScriptedInputError(
            "Scripted extraction supports only exact, unedited fixture text."
        )
