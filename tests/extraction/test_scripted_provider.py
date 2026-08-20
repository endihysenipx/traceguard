import pytest

from traceguard.extraction import (
    ExtractionProvider,
    ScriptedExtractionProvider,
    UnsupportedScriptedInputError,
)
from traceguard.workflow.fixtures import SCENARIO_FIXTURES
from traceguard.workflow.models import PresetId, ProviderMode


@pytest.mark.parametrize("preset_id", list(PresetId))
def test_all_exact_fixture_texts_return_expected_content(
    preset_id: PresetId,
) -> None:
    fixture = SCENARIO_FIXTURES[preset_id]
    provider = ScriptedExtractionProvider()

    result = provider.extract(fixture.order_request_text)

    assert provider.mode is ProviderMode.SCRIPTED
    assert isinstance(provider, ExtractionProvider)
    assert result == fixture.expected_extraction_result.model_dump(mode="json")


def test_edited_fixture_text_is_rejected() -> None:
    fixture = SCENARIO_FIXTURES[PresetId.SUCCESS]

    with pytest.raises(UnsupportedScriptedInputError):
        ScriptedExtractionProvider().extract(fixture.order_request_text + " Edited.")


def test_arbitrary_custom_text_is_rejected() -> None:
    with pytest.raises(UnsupportedScriptedInputError):
        ScriptedExtractionProvider().extract("Order one entirely custom item.")


def test_matching_uses_text_and_has_no_preset_input() -> None:
    success = SCENARIO_FIXTURES[PresetId.SUCCESS]
    result = ScriptedExtractionProvider().extract(success.order_request_text)

    assert result["customer_number"] == "CUST-1001"
    assert "preset_id" not in result


def test_returned_mapping_cannot_mutate_fixture_or_later_results() -> None:
    fixture = SCENARIO_FIXTURES[PresetId.SUCCESS]
    provider = ScriptedExtractionProvider()
    first = provider.extract(fixture.order_request_text)

    first["customer_number"] = "MUTATED"
    second = provider.extract(fixture.order_request_text)

    assert second["customer_number"] == "CUST-1001"
    assert fixture.expected_extraction_result.customer_number == "CUST-1001"
