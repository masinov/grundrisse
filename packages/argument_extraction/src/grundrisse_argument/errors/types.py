"""
Error taxonomy for autonomous retries.

Each failed extraction step returns a structured error object
that informs the recovery strategy.
"""

from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ErrorType(str, Enum):
    """Machine-interpretable error types for autonomous retry logic."""

    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    """No valid locution spans could be identified for a proposition or relation."""

    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    """Invalid JSON, missing required fields, or type mismatches."""

    CONTEXT_EXHAUSTION = "CONTEXT_EXHAUSTION"
    """Insufficient premises detected even after maximum retrieval attempts."""

    OVERGENERATION = "OVERGENERATION"
    """Too many propositions generated without clear relations (noise threshold exceeded)."""

    ENTITY_RESOLUTION_FAILURE = "ENTITY_RESOLUTION_FAILURE"
    """Cannot resolve attributed entity and context insufficient for disambiguation."""

    RETRIEVAL_POISONING_RISK = "RETRIEVAL_POISONING_RISK"
    """Retrieved context may be influencing extraction inappropriately."""

    VALIDATION_CYCLE = "VALIDATION_CYCLE"
    """Same validation failure occurs repeatedly without progress."""


class ExtractionError(BaseModel):
    """Structured error object for failed extraction steps."""

    error_type: ErrorType
    stage: str = Field(..., description="e.g., 'proposition_extraction', 'relation_classification'")
    doc_id: Optional[str] = None
    window_id: Optional[str] = None
    message: str = Field(..., description="Human-readable error message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional error context")
    retry_count: int = Field(default=0, description="Number of retries attempted")
    suggested_recovery: str = Field(..., description="Suggested recovery action")

    def to_log_message(self) -> str:
        """Format error for logging."""
        loc = f"doc:{self.doc_id}" if self.doc_id else f"window:{self.window_id}"
        return f"[{self.error_type.value}] {self.stage} @ {loc}: {self.message}"


class RetryPolicy(BaseModel):
    """Retry policy configuration for each error type."""

    max_retries: Dict[ErrorType, int] = Field(
        default={
            ErrorType.GROUNDING_FAILURE: 3,
            ErrorType.SCHEMA_VIOLATION: 3,
            ErrorType.CONTEXT_EXHAUSTION: 2,
            ErrorType.OVERGENERATION: 3,
            ErrorType.ENTITY_RESOLUTION_FAILURE: 1,
            ErrorType.RETRIEVAL_POISONING_RISK: 2,
            ErrorType.VALIDATION_CYCLE: 0,  # Fatal, requires manual review
        }
    )
    base_backoff_seconds: int = Field(default=1, description="Base for exponential backoff")
    max_backoff_seconds: int = Field(default=60, description="Maximum backoff time")

    def can_retry(self, error_type: ErrorType, retry_count: int) -> bool:
        """Check if an error type can be retried."""
        max_allowed = self.max_retries.get(error_type, 0)
        return retry_count < max_allowed

    def get_backoff_seconds(self, retry_count: int) -> int:
        """Calculate exponential backoff with a ceiling."""
        backoff = self.base_backoff_seconds * (2**retry_count)
        return min(backoff, self.max_backoff_seconds)
