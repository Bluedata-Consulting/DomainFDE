"""The output contract.

This is the single most valuable thing in this example. A prompt that returns
prose is a demo; a prompt that returns a validated object is a component you can
put behind an API, log, evaluate, and diff across model versions.

ADK passes this schema to Gemini as a response schema, so the model is
constrained at decode time rather than merely asked nicely in the prompt.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    DELIVERY_DELAY = "delivery_delay"
    DAMAGED_ITEM = "damaged_item"
    WRONG_ITEM = "wrong_item"
    REFUND_STATUS = "refund_status"
    PRODUCT_QUESTION = "product_question"
    OFFER_OR_PRICING = "offer_or_pricing"
    ACCOUNT_ACCESS = "account_access"
    OTHER = "other"


class Priority(str, Enum):
    P1 = "P1"  # customer-visible failure, SLA breach, or churn risk
    P2 = "P2"  # genuine problem, no immediate escalation risk
    P3 = "P3"  # question or low-impact request


class Sentiment(str, Enum):
    ANGRY = "angry"
    FRUSTRATED = "frustrated"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


class TicketTriage(BaseModel):
    """Structured triage of a single inbound customer-care ticket."""

    category: Category = Field(description="Primary issue type.")
    priority: Priority = Field(description="Operational priority.")
    sentiment: Sentiment = Field(description="Customer's emotional state.")

    order_id: str = Field(
        description="Order ID referenced by the customer, or 'NOT_PROVIDED'."
    )
    summary: str = Field(
        description="One sentence, under 25 words, stating the customer's problem."
    )
    policy_dependent: bool = Field(
        description=(
            "True when resolving this requires checking a specific policy, balance, "
            "or system record that is not present in the ticket text."
        )
    )
    suggested_reply: str = Field(
        description=(
            "Draft reply to the customer in Aurora's tone of voice. 60-110 words. "
            "Never states a refund amount, date, or stock position as fact."
        )
    )
    internal_note: str = Field(
        description="One line for the human agent: what to verify before sending."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Model confidence in this triage, 0.0 to 1.0."
    )
