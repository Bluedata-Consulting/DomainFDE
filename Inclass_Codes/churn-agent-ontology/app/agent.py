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

"""Churn agent, ontology edition.

Same shape as the baseline workflow — parse, look up, decide, review, finalise —
but every step is expressed against the ontology in :mod:`app.ontology` rather
than against raw fields:

- the customer becomes an individual in a knowledge graph;
- their free-text interactions are classified into a taxonomy;
- risk bands, customer states and *offer eligibility* are inferred, not hardcoded;
- the LLM reviewer is briefed with the ontology view and may only choose among
  the actions the reasoner declared eligible;
- that choice is validated against eligibility before it reaches the user.
"""

import re
from enum import Enum

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel, Field

from .ontology import churn_ontology as co
from .ontology import renderer
from .ontology.reasoner import REASONER, known_customer, reason

MODEL = "gemini-3.5-flash"

CUSTOMER_ID_PATTERN = re.compile(r"\bC\d{3,}\b", re.IGNORECASE)


class DecisionOutcome(str, Enum):
    NO_ACTION = "NO_ACTION"
    STANDARD_OFFER = "STANDARD_OFFER"
    PREMIUM_OFFER = "PREMIUM_OFFER"
    REVIEW = "REVIEW"


class TypedInteractionView(BaseModel):
    concept: str
    polarity: str
    text: str


class OntologyAssessment(BaseModel):
    """What the reasoner concluded about a customer, as workflow data."""

    customer_id: str
    churn_score: float
    days_since_last_offer: int
    value_segment: str
    risk_band: str
    customer_states: list[str]
    interactions: list[TypedInteractionView]
    eligible_actions: list[str]
    recommended_action: str | None = None
    inference_chain: list[str] = Field(default_factory=list)
    briefing: str = ""


class ReviewerVerdict(BaseModel):
    """The reviewer's pick, constrained to the eligible actions."""

    customer_id: str
    outcome: DecisionOutcome
    rationale: str


class DecisionIntent(BaseModel):
    customer_id: str
    outcome: DecisionOutcome
    rationale: str
    eligible_actions: list[str] = Field(default_factory=list)
    inference_chain: list[str] = Field(default_factory=list)


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


def assess_customer(node_input: str) -> Event:
    """Runs the ontology reasoner over the customer, or routes to REVIEW if unknown."""
    customer_id = node_input
    if not known_customer(customer_id):
        return Event(
            output=DecisionIntent(
                customer_id=customer_id,
                outcome=DecisionOutcome.REVIEW,
                rationale=f"No customer record found for '{customer_id}'.",
            ),
            route="not_found",
        )

    result = reason(customer_id)
    return Event(
        output=OntologyAssessment(
            customer_id=result.customer_id,
            churn_score=result.churn_score,
            days_since_last_offer=result.days_since_last_offer,
            value_segment=result.value_segment,
            risk_band=result.risk_band,
            customer_states=result.customer_states,
            interactions=[
                TypedInteractionView(
                    concept=i.concept, polarity=i.polarity, text=i.text
                )
                for i in result.interactions
            ],
            eligible_actions=result.eligible_actions,
            recommended_action=result.recommended_action,
            inference_chain=result.chain(),
            briefing=result.render_briefing(),
        ),
        route="assessed",
    )


def apply_ontology_policy(node_input: OntologyAssessment) -> Event:
    """Emits the reasoner's decision, or hands an ambiguous case to the reviewer."""
    if node_input.recommended_action is None:
        return Event(output=node_input, route="needs_review")

    action = node_input.recommended_action
    outcome = DecisionOutcome(co.OUTCOME_BY_ACTION[action])
    return Event(
        output=DecisionIntent(
            customer_id=node_input.customer_id,
            outcome=outcome,
            rationale=renderer.render_policy_rationale(node_input, action),
            eligible_actions=node_input.eligible_actions,
            inference_chain=node_input.inference_chain,
        ),
        route="decided",
    )


reviewer = LlmAgent(
    name="offer_reviewer",
    model=MODEL,
    instruction=f"""You are a retail churn-offer specialist. A deterministic
ontology reasoner has already classified the customer but could not settle on a
single action, so the decision is yours.

You reason over this ontology:

{renderer.render_ontology(co.ONTOLOGY)}

The reasoner applies these rules:

{renderer.render_rules(REASONER)}

You are given the customer's ontology view: their churn score, inferred
hasRiskBand, hasValueSegment, customer states, every interaction classified into
the interaction taxonomy, the actions they are ELIGIBLE for, and the inference
chain drawn so far.

Hard constraints:
- Choose exactly one outcome, and only from the ELIGIBLE ACTIONS listed. The
  mapping is NoAction -> NO_ACTION, StandardOffer -> STANDARD_OFFER,
  PremiumOffer -> PREMIUM_OFFER, HumanReview -> REVIEW.
- Never propose an offer the eligibility rules excluded; if the eligible set is
  too thin to act on meaningfully, choose REVIEW.

Weigh the risk band against the value segment, the customer states (an
AttritionRiskCustomer or DisengagedCustomer argues for intervention; an
EngagedCustomer against it), how recently they were last incentivised, and the
balance of positive against negative interaction concepts.

Return the customer_id, your chosen outcome, and a concise one-to-two sentence
rationale that cites the ontology concepts you relied on (for example
"ModerateRiskBand", "DisengagementInteraction") rather than restating raw text.""",
    output_schema=ReviewerVerdict,
    output_key="decision",
)


def validate_verdict(node_input: ReviewerVerdict) -> Event:
    """Checks the reviewer's pick against ontology eligibility before it ships.

    The reviewer is instructed to stay inside the eligible set; this node makes
    that a guarantee rather than a hope. An ineligible pick is downgraded to
    REVIEW instead of being served to the user.
    """
    result = reason(node_input.customer_id)
    chosen_action = co.ACTION_BY_OUTCOME[node_input.outcome.value]

    if chosen_action not in result.eligible_actions:
        return Event(
            output=DecisionIntent(
                customer_id=node_input.customer_id,
                outcome=DecisionOutcome.REVIEW,
                rationale=renderer.render_ineligible_verdict(
                    chosen_action, result.eligible_actions
                ),
                eligible_actions=result.eligible_actions,
                inference_chain=result.chain(),
            ),
            route="validated",
        )

    return Event(
        output=DecisionIntent(
            customer_id=node_input.customer_id,
            outcome=node_input.outcome,
            rationale=node_input.rationale,
            eligible_actions=result.eligible_actions,
            inference_chain=[
                *result.chain(),
                f"[ReviewerVerdict] recommendedAction {chosen_action}"
                f" (because {node_input.rationale})",
            ],
        ),
        route="validated",
    )


def finalize(node_input: DecisionIntent) -> Event:
    """Renders the decision plus the inference chain that justifies it."""
    summary = renderer.render_decision(node_input, node_input.outcome.value)
    return Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=summary)]),
        output=node_input,
    )


root_agent = Workflow(
    # Keep in sync with agents-cli-manifest.yaml: agents-cli derives this name
    # from the project `name:` recorded there, and telemetry reports it as
    # gen_ai.agent.name. Renaming the agent only here makes the two disagree,
    # and anything selecting traces by name stops finding this agent's.
    name="churn_agent_ontology",
    edges=[
        ("START", parse_customer_query),
        (
            parse_customer_query,
            {
                "has_customer_id": assess_customer,
                "missing_customer_id": request_customer_id,
            },
        ),
        (assess_customer, {"assessed": apply_ontology_policy, "not_found": finalize}),
        (apply_ontology_policy, {"decided": finalize, "needs_review": reviewer}),
        (reviewer, validate_verdict),
        (validate_verdict, finalize),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
