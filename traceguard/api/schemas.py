"""Small closed HTTP request contracts for the Phase 6 API."""

from pydantic import BaseModel, ConfigDict, Field

from traceguard.domain.enums import ProviderMode
from traceguard.workflow.models import MockErpBehavior, PresetId


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRunRequest(ApiRequest):
    order_request_text: str = Field(min_length=1, max_length=10_000)
    preset_id: PresetId | None = None
    mock_erp_behavior: MockErpBehavior
    extraction_provider_mode: ProviderMode


class InvestigateRequest(ApiRequest):
    investigation_provider_mode: ProviderMode


class EmptyActionRequest(ApiRequest):
    pass
