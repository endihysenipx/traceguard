import pytest

from traceguard.domain.enums import CanonicalErrorCode, FailureCategory
from traceguard.domain.errors import WorkflowValidationError
from traceguard.domain.models import ExtractedOrderCandidate
from traceguard.domain.validation import (
    validate_business_rules,
    validate_domain_requirements,
    validate_extracted_structure,
)


def test_structural_validation_allows_missing_business_fields() -> None:
    assert validate_extracted_structure({}) == ExtractedOrderCandidate()


@pytest.mark.parametrize(
    "payload",
    [
        {"quantity": "-3"},
        {"quantity": True},
        {"customer_number": 123},
        {"unknown_field": "value"},
        ["not", "an", "object"],
    ],
)
def test_structural_validation_rejects_wrong_shape_or_types(payload: object) -> None:
    with pytest.raises(WorkflowValidationError) as raised:
        validate_extracted_structure(payload)

    assert raised.value.category is FailureCategory.STRUCTURAL_VALIDATION_FAILURE
    assert raised.value.code is CanonicalErrorCode.ORDER_STRUCTURE_INVALID


@pytest.mark.parametrize("customer_number", [None, "", "   "])
def test_domain_validation_requires_customer_number(
    customer_number: str | None,
) -> None:
    candidate = ExtractedOrderCandidate(
        customer_number=customer_number,
        product_code="SKU-1",
        quantity=1,
    )

    with pytest.raises(WorkflowValidationError) as raised:
        validate_domain_requirements(candidate)

    assert raised.value.category is FailureCategory.DOMAIN_VALIDATION_FAILURE
    assert raised.value.code is CanonicalErrorCode.CUSTOMER_NUMBER_MISSING


@pytest.mark.parametrize("product_code", [None, "", "   "])
def test_domain_validation_requires_product_code(product_code: str | None) -> None:
    candidate = ExtractedOrderCandidate(
        customer_number="C-1",
        product_code=product_code,
        quantity=1,
    )

    with pytest.raises(WorkflowValidationError) as raised:
        validate_domain_requirements(candidate)

    assert raised.value.code is CanonicalErrorCode.PRODUCT_CODE_MISSING


def test_domain_validation_requires_quantity() -> None:
    candidate = ExtractedOrderCandidate(
        customer_number="C-1",
        product_code="SKU-1",
        quantity=None,
    )

    with pytest.raises(WorkflowValidationError) as raised:
        validate_domain_requirements(candidate)

    assert raised.value.code is CanonicalErrorCode.QUANTITY_MISSING


def test_domain_validation_has_deterministic_missing_field_precedence() -> None:
    with pytest.raises(WorkflowValidationError) as raised:
        validate_domain_requirements(ExtractedOrderCandidate())

    assert raised.value.code is CanonicalErrorCode.CUSTOMER_NUMBER_MISSING


def test_domain_validation_normalizes_text_but_does_not_apply_quantity_rule() -> None:
    candidate = ExtractedOrderCandidate(
        customer_number=" C-1 ",
        product_code=" SKU-1 ",
        quantity=-3,
        delivery_instructions="   ",
    )

    order = validate_domain_requirements(candidate)

    assert order.customer_number == "C-1"
    assert order.product_code == "SKU-1"
    assert order.quantity == -3
    assert order.delivery_instructions is None


@pytest.mark.parametrize("quantity", [0, -3])
def test_non_positive_quantity_is_a_business_rule_violation(quantity: int) -> None:
    domain_order = validate_domain_requirements(
        ExtractedOrderCandidate(
            customer_number="C-1",
            product_code="SKU-1",
            quantity=quantity,
        )
    )

    with pytest.raises(WorkflowValidationError) as raised:
        validate_business_rules(domain_order)

    assert raised.value.category is FailureCategory.BUSINESS_RULE_VIOLATION
    assert raised.value.code is CanonicalErrorCode.QUANTITY_NON_POSITIVE


def test_valid_order_crosses_all_validation_boundaries() -> None:
    candidate = validate_extracted_structure(
        {
            "customer_number": "C-1",
            "product_code": "SKU-1",
            "quantity": 2,
            "delivery_instructions": "Leave at desk",
        }
    )
    domain_order = validate_domain_requirements(candidate)

    validated_order = validate_business_rules(domain_order)

    assert validated_order.quantity == 2
    assert validated_order.customer_number == "C-1"

