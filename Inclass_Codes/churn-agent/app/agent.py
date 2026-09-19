# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
from enum import Enum

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel

from .customerData import CUSTOMERS

MODEL = "gemini-3.5-flash"

# Churn score is a fraction in [0, 1]; days_since_last_offer is in [0, 200].
CHURN_LOW_THRESHOLD = 0.30
CHURN_HIGH_THRESHOLD = 0.70

CUSTOMER_ID_PATTERN = re.compile(r"\bC\d{3,}\b", re.IGNORECASE)


class DecisionOutcome(str, Enum):
    NO_ACTION = "NO_ACTION"
    STANDARD_OFFER = "STANDARD_OFFER"
    PREMIUM_OFFER = "PREMIUM_OFFER"
    REVIEW = "REVIEW"


class CustomerProfile(BaseModel):
    customer_id: str
    churn_score: float
    clv_segment: str
    days_since_last_offer: int
    recent_interactions: list[str]


class DecisionIntent(BaseModel):
    customer_id: str
    outcome: DecisionOutcome
    rationale: str


def parse_customer_query(node_input: types.Content) -> Event:
    """Extracts a customer id from free-form user text (e.g. "what offer for C1001?")."""
    text = "".join(part.text or "" for part in (node_input.parts or []))
    match = CUSTOMER_ID_PATTERN.search(text)
    if match is None:
        return Event(route="missing_customer_id")
    return Event(output=match.group(0).upper(), route="has_customer_id")


def request_customer_id() -> Event:
    """Terminal branch for requests that name no customer to decide on."""
    return Event(
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text=(
                        "Please include a customer id (for example C1001) and I'll"
                        " recommend the most relevant offer."
                    )
                )
            ],
        )
    )


def lookup_customer(node_input: str) -> Event:
    """Resolves a customer id to a full CustomerProfile, or routes to REVIEW if unknown."""
    record = CUSTOMERS.get(node_input)
    if record is None:
        return Event(
            output=DecisionIntent(
                customer_id=node_input,
                outcome=DecisionOutcome.REVIEW,
                rationale=f"No customer record found for '{node_input}'.",
            ),
            route="not_found",
        )
    return Event(output=CustomerProfile(**record), route="found")


def evaluate_rules(node_input: CustomerProfile) -> Event:
    """Applies the deterministic churn/CLV rules; falls through to REVIEW otherwise."""
    churn = node_input.churn_score
    clv = node_input.clv_segment.strip().lower()

    if churn < CHURN_LOW_THRESHOLD:
        return Event(
            output=DecisionIntent(
                customer_id=node_input.customer_id,
                outcome=DecisionOutcome.NO_ACTION,
                rationale=f"Churn score {churn:.0%} is below the {CHURN_LOW_THRESHOLD:.0%} threshold.",
            ),
            route="decided",
        )

    if churn > CHURN_HIGH_THRESHOLD and clv == "high":
        return Event(
            output=DecisionIntent(
                customer_id=node_input.customer_id,
                outcome=DecisionOutcome.PREMIUM_OFFER,
                rationale=f"Churn score {churn:.0%} exceeds {CHURN_HIGH_THRESHOLD:.0%} and CLV segment is High.",
            ),
            route="decided",
        )

    if churn > CHURN_HIGH_THRESHOLD and clv == "medium":
        return Event(
            output=DecisionIntent(
                customer_id=node_input.customer_id,
                outcome=DecisionOutcome.STANDARD_OFFER,
                rationale=f"Churn score {churn:.0%} exceeds {CHURN_HIGH_THRESHOLD:.0%} and CLV segment is Medium.",
            ),
            route="decided",
        )

    return Event(output=node_input, route="needs_review")


reviewer = LlmAgent(
    name="offer_reviewer",
    model=MODEL,
    instruction="""You are a retail churn-offer specialist reviewing a customer that
does not fall into a clear-cut rule bucket (e.g. mid-range churn score, or a high
churn score paired with a Low CLV segment).

Given the customer profile (customer_id, churn_score, clv_segment,
days_since_last_offer, recent_interactions), decide the single best outcome:
- NO_ACTION: no intervention is warranted right now.
- STANDARD_OFFER: a standard retention offer is warranted.
- PREMIUM_OFFER: a premium retention offer is warranted.
- REVIEW: the situation is ambiguous enough that a human should look at it.

Weigh the churn_score, clv_segment, days_since_last_offer (how recently they were
last incentivized), and recent_interactions (signals like complaints, abandoned
carts, or positive engagement). Return the customer_id, your chosen outcome, and a
concise one-to-two sentence rationale grounded in the specific evidence.""",
    output_schema=DecisionIntent,
    output_key="decision",
)


def finalize(node_input: DecisionIntent) -> Event:
    """Renders the final decision as user-facing content and the workflow output."""
    summary = f"Customer {node_input.customer_id}: {node_input.outcome.value} — {node_input.rationale}"
    return Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=summary)]),
        output=node_input,
    )


root_agent = Workflow(
    # Keep in sync with agents-cli-manifest.yaml: agents-cli derives this name
    # from the project `name:` recorded there, and telemetry reports it as
    # gen_ai.agent.name. Renaming the agent only here makes the two disagree,
    # and anything selecting traces by name stops finding this agent's.
    name="churn_agent",
    edges=[
        ("START", parse_customer_query),
        (
            parse_customer_query,
            {
                "has_customer_id": lookup_customer,
                "missing_customer_id": request_customer_id,
            },
        ),
        (lookup_customer, {"found": evaluate_rules, "not_found": finalize}),
        (evaluate_rules, {"decided": finalize, "needs_review": reviewer}),
        (reviewer, finalize),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
