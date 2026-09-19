"""Contracts between pipeline stages.

In a static workflow the schemas matter more than in a chat agent, because each
stage's output is the next stage's input. Typed boundaries are what stop a
quality problem in stage 1 from surfacing as a baffling error in stage 4.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ExceptionType(str, Enum):
    LOST_IN_TRANSIT = "lost_in_transit"
    DELAYED = "delayed"
    DAMAGED = "damaged"
    SHORT_SHIPPED = "short_shipped"
    WRONG_ITEM = "wrong_item"
    FAILED_DELIVERY = "failed_delivery"


class ResolutionAction(str, Enum):
    REPLACE_FULL = "replace_full"
    REPLACE_PARTIAL = "replace_partial"
    REFUND_FULL = "refund_full"
    REFUND_PARTIAL = "refund_partial"
    REDELIVER = "redeliver"
    GOODWILL_CREDIT_ONLY = "goodwill_credit_only"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class ExceptionCase(BaseModel):
    """Stage 1 output — the normalised case, extracted from a raw ops payload."""

    order_id: str
    customer_name: str
    exception_type: ExceptionType
    affected_skus: list[str] = Field(description="SKU codes affected by the exception.")
    order_value_inr: float = Field(description="Total order value in INR.")
    days_since_promised: int = Field(
        description="Days past the promised delivery date. Negative if not yet due."
    )
    evidence_available: bool = Field(
        description="True when photographs or a carrier scan support the claim."
    )
    customer_statement: str = Field(description="What the customer said, condensed.")


class Resolution(BaseModel):
    """Stage 3 output — the decision, with its reasoning made auditable."""

    action: ResolutionAction
    goodwill_credit_inr: float = Field(
        ge=0, description="Goodwill credit in INR. 0 when none is warranted."
    )
    rationale: str = Field(
        description="Two sentences citing the policy, supply and customer inputs."
    )
    policy_exception_required: bool = Field(
        description="True when the action breaches standard policy and needs sign-off."
    )
    expected_cost_inr: float = Field(
        ge=0, description="Total expected cost to Aurora of this resolution."
    )
    confidence: float = Field(ge=0.0, le=1.0)
