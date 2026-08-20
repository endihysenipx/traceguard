"""Explicit deterministic order-validation boundaries."""

from typing import Any

from pydantic import ValidationError

from traceguard.domain.enums import CanonicalErrorCode, FailureCategory
from traceguard.domain.errors import WorkflowValidationError
from traceguard.domain.models import DomainOrder, ExtractedOrderCandidate, ValidatedOrder


def validate_extracted_structure(value: Any) -> ExtractedOrderCandidate:
    """Validate only extraction shape and types, not business completeness."""

    try:
        return ExtractedOrderCandidate.model_validate(value)
    except ValidationError as exc:
        raise WorkflowValidationError(
            category=FailureCategory.STRUCTURAL_VALIDATION_FAILURE,
            code=CanonicalErrorCode.ORDER_STRUCTURE_INVALID,
            message="Extracted order has an invalid structure or field type.",
        ) from exc


def validate_domain_requirements(candidate: ExtractedOrderCandidate) -> DomainOrder:
    """Require and normalize business fields using deterministic precedence."""

    customer_number = _required_text(
        candidate.customer_number,
        code=CanonicalErrorCode.CUSTOMER_NUMBER_MISSING,
        label="Customer number",
    )
    product_code = _required_text(
        candidate.product_code,
        code=CanonicalErrorCode.PRODUCT_CODE_MISSING,
        label="Product code",
    )
    if candidate.quantity is None:
        raise WorkflowValidationError(
            category=FailureCategory.DOMAIN_VALIDATION_FAILURE,
            code=CanonicalErrorCode.QUANTITY_MISSING,
            message="Quantity is required.",
        )

    delivery_instructions = candidate.delivery_instructions
    if delivery_instructions is not None:
        delivery_instructions = delivery_instructions.strip() or None

    return DomainOrder(
        customer_number=customer_number,
        product_code=product_code,
        quantity=candidate.quantity,
        delivery_instructions=delivery_instructions,
    )


def validate_business_rules(order: DomainOrder) -> ValidatedOrder:
    """Validate deterministic business rules over complete, typed data."""

    if order.quantity <= 0:
        raise WorkflowValidationError(
            category=FailureCategory.BUSINESS_RULE_VIOLATION,
            code=CanonicalErrorCode.QUANTITY_NON_POSITIVE,
            message="Quantity must be greater than zero.",
        )

    return ValidatedOrder(**order.model_dump())


def _required_text(
    value: str | None,
    *,
    code: CanonicalErrorCode,
    label: str,
) -> str:
    if value is None or not value.strip():
        raise WorkflowValidationError(
            category=FailureCategory.DOMAIN_VALIDATION_FAILURE,
            code=code,
            message=f"{label} is required.",
        )
    return value.strip()

