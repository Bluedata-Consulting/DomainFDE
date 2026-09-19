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

"""Every text surface the ontology produces, in one place.

Three audiences read the ontology's output — the LLM reviewer (the prompt and
the briefing), the end user (the decision and its inference chain), and whoever
is reading the docs (the hierarchy). Keeping their renderings here means the
schema, the reasoner and the agent stay free of presentation, and the wording
can change without touching any of them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol

from .schema import THING, Inference, Ontology, Reasoner

if TYPE_CHECKING:
    from .reasoner import ReasoningResult


class Decision(Protocol):
    """The shape :func:`render_decision` needs; ``agent.DecisionIntent`` fits it."""

    customer_id: str
    rationale: str
    eligible_actions: list[str]
    inference_chain: list[str]


class CustomerView(Protocol):
    """The shape :func:`render_policy_rationale` needs; both a
    ``ReasoningResult`` and the workflow's ``OntologyAssessment`` fit it."""

    customer_id: str
    churn_score: float
    risk_band: str
    value_segment: str


# --- the ontology itself -----------------------------------------------------


def render_hierarchy(ontology: Ontology, root: str = THING, indent: int = 0) -> str:
    """An indented rendering of the concept hierarchy, for prompts and docs."""
    concept = ontology.get_concept(root)
    line = f"{'  ' * indent}- {concept.display()}"
    if concept.comment:
        line += f": {concept.comment}"
    return "\n".join(
        [line]
        + [
            render_hierarchy(ontology, child, indent + 1)
            for child in ontology.children(root)
        ]
    )


def render_properties(ontology: Ontology) -> str:
    return "\n".join(
        f"- {p.name}({p.domain}) -> {p.range_}"
        + (f": {p.comment}" if p.comment else "")
        for p in ontology.all_properties()
    )


def render_ontology(ontology: Ontology) -> str:
    """The concept hierarchy and properties, as text to ground an LLM node."""
    return (
        "CONCEPT HIERARCHY\n"
        f"{render_hierarchy(ontology)}\n\n"
        "PROPERTIES\n"
        f"{render_properties(ontology)}"
    )


def render_rules(reasoner: Reasoner) -> str:
    return "\n".join(
        f"- {rule.name} (stage {rule.stage}): {rule.description}"
        for rule in reasoner.rules
    )


# --- what the reasoner concluded ---------------------------------------------


def render_inference(inference: Inference) -> str:
    because = "; ".join(inference.premises)
    return f"[{inference.rule}] {inference.conclusion} (because {because})"


def render_chain(inferences: Iterable[Inference]) -> list[str]:
    return [render_inference(inference) for inference in inferences]


def render_briefing(result: ReasoningResult) -> str:
    """The customer's ontology view, as text for the LLM reviewer node."""
    interactions = "\n".join(
        f"  - {i.concept} ({i.polarity}): {i.text}" for i in result.interactions
    )
    chain = "\n".join(f"  - {line}" for line in result.chain())
    return (
        f"CUSTOMER {result.customer_id}\n"
        f"  hasChurnScore: {result.churn_score:.0%}\n"
        f"  hasValueSegment: {result.value_segment}\n"
        f"  hasRiskBand: {result.risk_band}\n"
        f"  daysSinceLastOffer: {result.days_since_last_offer}\n"
        f"  states: {', '.join(result.customer_states)}\n"
        "INTERACTIONS\n"
        f"{interactions or '  - none recorded'}\n"
        "ELIGIBLE ACTIONS (you may choose only from these)\n"
        f"  - {', '.join(result.eligible_actions)}\n"
        "INFERENCE CHAIN SO FAR\n"
        f"{chain or '  - none'}"
    )


# --- what the user sees ------------------------------------------------------


def render_policy_rationale(customer: CustomerView, action: str) -> str:
    """The rationale for a decision the deterministic rules settled on."""
    return (
        f"Churn score {customer.churn_score:.0%} places {customer.customer_id} in"
        f" {customer.risk_band} with {customer.value_segment}; {action} satisfies"
        " its eligibility constraints."
    )


def render_ineligible_verdict(action: str, eligible: Sequence[str]) -> str:
    """The rationale for downgrading a reviewer pick that fails eligibility."""
    return (
        f"The reviewer proposed {action}, which fails its eligibility constraints"
        f" for this customer (eligible: {', '.join(eligible)}). Escalating for a"
        " human decision."
    )


def render_decision(decision: Decision, outcome: str) -> str:
    """The final user-facing answer: the call, why, and what backs it."""
    summary = f"Customer {decision.customer_id}: {outcome} — {decision.rationale}"
    if decision.inference_chain:
        steps = "\n".join(f"  {step}" for step in decision.inference_chain)
        summary += f"\n\nOntology inference chain:\n{steps}"
    if decision.eligible_actions:
        summary += f"\n\nEligible actions: {', '.join(decision.eligible_actions)}"
    return summary
