"""Shared extraction-provider boundary and sanitized provider failures."""

from typing import Protocol, runtime_checkable

from traceguard.domain.enums import ProviderMode


@runtime_checkable
class ExtractionProvider(Protocol):
    """Returns JSON-compatible candidate data for deterministic validation."""

    @property
    def mode(self) -> ProviderMode: ...

    def extract(self, order_request_text: str) -> object: ...


class ExtractionProviderError(RuntimeError):
    """Base class for failures safe to collapse at the workflow boundary."""


class ProviderConfigurationError(ExtractionProviderError):
    """The selected provider is not configured for use."""


class ExtractionProviderTimeoutError(ExtractionProviderError):
    """The provider request exceeded its bounded timeout."""


class ExtractionProviderRequestError(ExtractionProviderError):
    """The provider request failed without exposing provider details."""


class ExtractionRefusalError(ExtractionProviderError):
    """The provider refused to produce the requested extraction."""


class MalformedProviderResponseError(ExtractionProviderError):
    """The provider response could not be used as extraction output."""


class UnsupportedScriptedInputError(ExtractionProviderError):
    """Scripted mode received text that is not an exact fixture request."""
