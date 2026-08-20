"""Editable convenience fixtures; preset IDs never drive workflow decisions."""

from types import MappingProxyType
from typing import Mapping

from traceguard.domain.models import DomainModel, ExtractedOrderCandidate
from traceguard.workflow.models import MockErpBehavior, PresetId


class ScenarioFixture(DomainModel):
    preset_id: PresetId
    order_request_text: str
    mock_erp_behavior: MockErpBehavior
    expected_extraction_result: ExtractedOrderCandidate


_FIXTURES = {
    PresetId.SUCCESS: ScenarioFixture(
        preset_id=PresetId.SUCCESS,
        order_request_text=(
            "Please create an order for customer CUST-1001 for 2 units of "
            "SKU-WIDGET-A. Deliver to the receiving desk."
        ),
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        expected_extraction_result=ExtractedOrderCandidate(
            customer_number="CUST-1001",
            product_code="SKU-WIDGET-A",
            quantity=2,
            delivery_instructions="Deliver to the receiving desk.",
        ),
    ),
    PresetId.MISSING_CUSTOMER: ScenarioFixture(
        preset_id=PresetId.MISSING_CUSTOMER,
        order_request_text=(
            "Please order 4 units of SKU-FILTER-20. The requester did not "
            "include a customer account number."
        ),
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        expected_extraction_result=ExtractedOrderCandidate(
            customer_number=None,
            product_code="SKU-FILTER-20",
            quantity=4,
        ),
    ),
    PresetId.INVALID_QUANTITY: ScenarioFixture(
        preset_id=PresetId.INVALID_QUANTITY,
        order_request_text=(
            "Create an order for customer CUST-2002 for -3 units of "
            "SKU-BEARING-7."
        ),
        mock_erp_behavior=MockErpBehavior.SUCCEED,
        expected_extraction_result=ExtractedOrderCandidate(
            customer_number="CUST-2002",
            product_code="SKU-BEARING-7",
            quantity=-3,
        ),
    ),
    PresetId.ERP_UNAVAILABLE: ScenarioFixture(
        preset_id=PresetId.ERP_UNAVAILABLE,
        order_request_text=(
            "Customer CUST-3003 needs 6 units of SKU-PUMP-9. No delivery "
            "instructions were supplied."
        ),
        mock_erp_behavior=MockErpBehavior.FAIL_ONCE_503,
        expected_extraction_result=ExtractedOrderCandidate(
            customer_number="CUST-3003",
            product_code="SKU-PUMP-9",
            quantity=6,
            delivery_instructions=None,
        ),
    ),
}

SCENARIO_FIXTURES: Mapping[PresetId, ScenarioFixture] = MappingProxyType(_FIXTURES)

