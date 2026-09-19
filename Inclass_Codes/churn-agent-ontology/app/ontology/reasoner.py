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

"""The churn reasoner: rules expressed against the ontology.

Rules run in four stages:

1. **Classification** — turn measurements into concepts (risk band, signal counts).
2. **State** — derive customer states (engaged, disengaged, attrition risk, fatigued).
3. **Eligibility** — assert which retention actions the customer may receive at all.
4. **Recommendation** — pick the single action the deterministic policy settles on,
   or none, in which case the decision is ambiguous and goes to the LLM reviewer.

Nothing here hardcodes an outcome: an outcome is a ``RetentionAction`` concept,
and every conclusion is recorded as an :class:`~app.ontology.schema.Inference`
so the final answer can cite the chain that produced it.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

from . import churn_ontology as co
from . import renderer
from .graph import build_graph
from .schema import Inference, KnowledgeGraph, Reasoner, Rule

# --- small helpers over the graph -------------------------------------------


def _concept_of(graph: KnowledgeGraph, iri: str, prop: str) -> str | None:
    """The concept of the single individual ``iri`` points at via ``prop``."""
    targets = graph.related(iri, prop)
    if not targets:
        return None
    return next(iter(targets[0].types))


def risk_band(graph: KnowledgeGraph, customer: str) -> str | None:
    return _concept_of(graph, customer, co.HAS_RISK_BAND)


def value_segment(graph: KnowledgeGraph, customer: str) -> str | None:
    return _concept_of(graph, customer, co.HAS_VALUE_SEGMENT)


def eligible_actions(graph: KnowledgeGraph, customer: str) -> list[str]:
    return sorted(
        next(iter(target.types))
        for target in graph.related(graph.get(customer).iri, co.ELIGIBLE_FOR)
    )


def recommended_action(graph: KnowledgeGraph, customer: str) -> str | None:
    return _concept_of(graph, customer, co.RECOMMENDED_ACTION)


def _relate_action(
    graph: KnowledgeGraph, customer: str, prop: str, action_concept: str
) -> bool:
    return graph.relate(customer, prop, co.ACTION_INDIVIDUALS[action_concept])


def _churn(graph: KnowledgeGraph, customer: str) -> float:
    return float(graph.get_data(customer, co.HAS_CHURN_SCORE, 0.0))


def _days(graph: KnowledgeGraph, customer: str) -> int:
    return int(graph.get_data(customer, co.DAYS_SINCE_LAST_OFFER, 0))


# --- stage 1: classification -------------------------------------------------


def _assign_risk_band(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    if risk_band(graph, customer) is not None:
        return []
    churn = _churn(graph, customer)
    if churn < co.CHURN_LOW_THRESHOLD:
        band, why = co.LOW_RISK_BAND, f"below {co.CHURN_LOW_THRESHOLD:.0%}"
    elif churn > co.CHURN_HIGH_THRESHOLD:
        band, why = co.HIGH_RISK_BAND, f"above {co.CHURN_HIGH_THRESHOLD:.0%}"
    else:
        band, why = (
            co.MODERATE_RISK_BAND,
            f"between {co.CHURN_LOW_THRESHOLD:.0%} and {co.CHURN_HIGH_THRESHOLD:.0%}",
        )
    graph.relate(customer, co.HAS_RISK_BAND, co.BAND_INDIVIDUALS[band])
    graph.assert_type(customer, co.CUSTOMER)
    return [
        Inference(
            rule="RiskBandFromChurnScore",
            subject=customer,
            premises=(f"hasChurnScore = {churn:.0%}, which is {why}",),
            conclusion=f"hasRiskBand {band}",
        )
    ]


def _count_signals(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    if graph.get_data(customer, co.POSITIVE_SIGNAL_COUNT) is not None:
        return []
    interactions = graph.related(customer, co.HAD_INTERACTION)
    positive = sum(
        1 for i in interactions if graph.is_a(i.iri, co.POSITIVE_INTERACTION)
    )
    negative = sum(
        1 for i in interactions if graph.is_a(i.iri, co.NEGATIVE_INTERACTION)
    )
    graph.set_data(customer, co.POSITIVE_SIGNAL_COUNT, positive)
    graph.set_data(customer, co.NEGATIVE_SIGNAL_COUNT, negative)
    kinds = ", ".join(sorted({next(iter(i.types)) for i in interactions})) or "none"
    return [
        Inference(
            rule="SignalCensus",
            subject=customer,
            premises=(f"{len(interactions)} interactions classified as: {kinds}",),
            conclusion=(
                f"positiveSignalCount = {positive}, negativeSignalCount = {negative}"
            ),
        )
    ]


# --- stage 2: customer states ------------------------------------------------


def _attrition_risk(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    signals = [
        i
        for i in graph.related(customer, co.HAD_INTERACTION)
        if graph.is_a(i.iri, co.ATTRITION_SIGNAL_INTERACTION)
    ]
    if not signals or not graph.assert_type(customer, co.ATTRITION_RISK_CUSTOMER):
        return []
    evidence = "; ".join(str(i.data.get(co.DESCRIBED_AS, i.iri)) for i in signals)
    return [
        Inference(
            rule="ExplicitAttritionSignal",
            subject=customer,
            premises=(f"hadInteraction some AttritionSignalInteraction: {evidence}",),
            conclusion=f"{customer} is an AttritionRiskCustomer",
        )
    ]


def _engagement_state(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    positive = graph.get_data(customer, co.POSITIVE_SIGNAL_COUNT)
    negative = graph.get_data(customer, co.NEGATIVE_SIGNAL_COUNT)
    if positive is None or negative is None:
        return []
    if negative - positive >= co.DISENGAGEMENT_MARGIN:
        state, rule = co.DISENGAGED_CUSTOMER, "NegativeSignalsDominate"
    elif positive - negative >= co.DISENGAGEMENT_MARGIN:
        state, rule = co.ENGAGED_CUSTOMER, "PositiveSignalsDominate"
    else:
        return []
    if not graph.assert_type(customer, state):
        return []
    return [
        Inference(
            rule=rule,
            subject=customer,
            premises=(
                f"positiveSignalCount = {positive}, negativeSignalCount = {negative},"
                f" margin >= {co.DISENGAGEMENT_MARGIN}",
            ),
            conclusion=f"{customer} is a {state}",
        )
    ]


def _offer_fatigue(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    days = _days(graph, customer)
    if days >= co.OFFER_FATIGUE_DAYS:
        return []
    if not graph.assert_type(customer, co.RECENTLY_INCENTIVISED_CUSTOMER):
        return []
    return [
        Inference(
            rule="OfferFatigue",
            subject=customer,
            premises=(
                f"daysSinceLastOffer = {days}, under the {co.OFFER_FATIGUE_DAYS}-day"
                " fatigue window",
            ),
            conclusion=f"{customer} is a RecentlyIncentivisedCustomer",
        )
    ]


# --- stage 3: eligibility ----------------------------------------------------


def _always_available(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    out = []
    for action in (co.NO_ACTION, co.HUMAN_REVIEW):
        if _relate_action(graph, customer, co.ELIGIBLE_FOR, action):
            out.append(
                Inference(
                    rule="UnconstrainedAction",
                    subject=customer,
                    premises=(f"{action} carries no eligibility constraint",),
                    conclusion=f"eligibleFor {action}",
                )
            )
    return out


def _standard_offer_eligibility(
    graph: KnowledgeGraph, customer: str
) -> list[Inference]:
    band = risk_band(graph, customer)
    if band not in (co.MODERATE_RISK_BAND, co.HIGH_RISK_BAND):
        return []
    if graph.is_a(customer, co.RECENTLY_INCENTIVISED_CUSTOMER):
        return []
    if not _relate_action(graph, customer, co.ELIGIBLE_FOR, co.STANDARD_OFFER):
        return []
    return [
        Inference(
            rule="StandardOfferEligibility",
            subject=customer,
            premises=(f"hasRiskBand {band}", "not a RecentlyIncentivisedCustomer"),
            conclusion=f"eligibleFor {co.STANDARD_OFFER}",
        )
    ]


def _premium_offer_eligibility(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    segment = value_segment(graph, customer)
    band = risk_band(graph, customer)
    if segment != co.HIGH_VALUE_SEGMENT:
        return []
    if graph.is_a(customer, co.RECENTLY_INCENTIVISED_CUSTOMER):
        return []
    disengaged = graph.is_a(customer, co.DISENGAGED_CUSTOMER)
    if band == co.HIGH_RISK_BAND:
        justification = f"hasRiskBand {band}"
    elif band == co.MODERATE_RISK_BAND and disengaged:
        justification = f"hasRiskBand {band} and is a DisengagedCustomer"
    else:
        return []
    if not _relate_action(graph, customer, co.ELIGIBLE_FOR, co.PREMIUM_OFFER):
        return []
    return [
        Inference(
            rule="PremiumOfferEligibility",
            subject=customer,
            premises=(
                f"hasValueSegment {segment}",
                justification,
                "not a RecentlyIncentivisedCustomer",
            ),
            conclusion=f"eligibleFor {co.PREMIUM_OFFER}",
        )
    ]


# --- stage 4: recommendation -------------------------------------------------


def _recommend(
    graph: KnowledgeGraph,
    customer: str,
    action: str,
    *,
    rule: str,
    premises: tuple[str, ...],
) -> list[Inference]:
    """Sets the single recommended action, unless one is already settled."""
    if recommended_action(graph, customer) is not None:
        return []
    _relate_action(graph, customer, co.RECOMMENDED_ACTION, action)
    return [
        Inference(
            rule=rule,
            subject=customer,
            premises=premises,
            conclusion=f"recommendedAction {action}",
        )
    ]


def _low_risk_no_action(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    if risk_band(graph, customer) != co.LOW_RISK_BAND:
        return []
    if graph.is_a(customer, co.ATTRITION_RISK_CUSTOMER):
        return []
    return _recommend(
        graph,
        customer,
        co.NO_ACTION,
        rule="LowRiskNeedsNoIntervention",
        premises=(
            f"hasRiskBand {co.LOW_RISK_BAND}",
            "no explicit attrition signal",
        ),
    )


def _high_risk_high_value_premium(
    graph: KnowledgeGraph, customer: str
) -> list[Inference]:
    if risk_band(graph, customer) != co.HIGH_RISK_BAND:
        return []
    if value_segment(graph, customer) != co.HIGH_VALUE_SEGMENT:
        return []
    if co.PREMIUM_OFFER not in eligible_actions(graph, customer):
        return []
    return _recommend(
        graph,
        customer,
        co.PREMIUM_OFFER,
        rule="HighRiskHighValueWarrantsPremium",
        premises=(
            f"hasRiskBand {co.HIGH_RISK_BAND}",
            f"hasValueSegment {co.HIGH_VALUE_SEGMENT}",
            f"eligibleFor {co.PREMIUM_OFFER}",
        ),
    )


def _high_risk_medium_value_standard(
    graph: KnowledgeGraph, customer: str
) -> list[Inference]:
    if risk_band(graph, customer) != co.HIGH_RISK_BAND:
        return []
    if value_segment(graph, customer) != co.MEDIUM_VALUE_SEGMENT:
        return []
    if co.STANDARD_OFFER not in eligible_actions(graph, customer):
        return []
    return _recommend(
        graph,
        customer,
        co.STANDARD_OFFER,
        rule="HighRiskMediumValueWarrantsStandard",
        premises=(
            f"hasRiskBand {co.HIGH_RISK_BAND}",
            f"hasValueSegment {co.MEDIUM_VALUE_SEGMENT}",
            f"eligibleFor {co.STANDARD_OFFER}",
        ),
    )


def _fatigue_suppresses_offers(graph: KnowledgeGraph, customer: str) -> list[Inference]:
    if not graph.is_a(customer, co.RECENTLY_INCENTIVISED_CUSTOMER):
        return []
    offers = {co.STANDARD_OFFER, co.PREMIUM_OFFER} & set(
        eligible_actions(graph, customer)
    )
    if offers:
        return []
    return _recommend(
        graph,
        customer,
        co.NO_ACTION,
        rule="FatigueSuppressesOffers",
        premises=(
            f"{customer} is a RecentlyIncentivisedCustomer",
            "no offer passes its eligibility constraints",
        ),
    )


RULES: list[Rule] = [
    Rule(
        "RiskBandFromChurnScore",
        10,
        "Maps hasChurnScore onto a RiskBand concept.",
        _assign_risk_band,
    ),
    Rule(
        "SignalCensus",
        11,
        "Counts positive and negative interactions from the taxonomy.",
        _count_signals,
    ),
    Rule(
        "ExplicitAttritionSignal",
        20,
        "Any AttritionSignalInteraction makes the customer an AttritionRiskCustomer.",
        _attrition_risk,
    ),
    Rule(
        "EngagementState",
        21,
        "Classifies the customer as Engaged or Disengaged from the signal census.",
        _engagement_state,
    ),
    Rule(
        "OfferFatigue",
        22,
        "A customer incentivised inside the fatigue window is RecentlyIncentivised.",
        _offer_fatigue,
    ),
    Rule(
        "UnconstrainedAction",
        30,
        "NoAction and HumanReview are always eligible.",
        _always_available,
    ),
    Rule(
        "StandardOfferEligibility",
        31,
        "Moderate or high risk, and not inside the offer-fatigue window.",
        _standard_offer_eligibility,
    ),
    Rule(
        "PremiumOfferEligibility",
        32,
        "High-value segment at high risk, or at moderate risk while disengaged.",
        _premium_offer_eligibility,
    ),
    Rule(
        "LowRiskNeedsNoIntervention",
        40,
        "Low risk with no attrition signal resolves to NoAction.",
        _low_risk_no_action,
    ),
    Rule(
        "HighRiskHighValueWarrantsPremium",
        41,
        "High risk plus high value resolves to PremiumOffer.",
        _high_risk_high_value_premium,
    ),
    Rule(
        "HighRiskMediumValueWarrantsStandard",
        42,
        "High risk plus medium value resolves to StandardOffer.",
        _high_risk_medium_value_standard,
    ),
    Rule(
        "FatigueSuppressesOffers",
        43,
        "When fatigue blocks every offer, the policy settles on NoAction.",
        _fatigue_suppresses_offers,
    ),
]

REASONER = Reasoner(RULES)


@dataclass(frozen=True)
class TypedInteraction:
    """One interaction, as the ontology sees it."""

    concept: str
    polarity: str
    text: str


@dataclass(frozen=True)
class ReasoningResult:
    """Everything the ontology concluded about one customer."""

    customer_id: str
    churn_score: float
    days_since_last_offer: int
    value_segment: str
    risk_band: str
    customer_states: list[str]
    interactions: list[TypedInteraction]
    eligible_actions: list[str]
    recommended_action: str | None
    inferences: list[Inference] = field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        """True when the deterministic policy did not settle on one action."""
        return self.recommended_action is None

    def chain(self) -> list[str]:
        return renderer.render_chain(self.inferences)

    def render_briefing(self) -> str:
        """The customer's ontology view, as text for the LLM reviewer node."""
        return renderer.render_briefing(self)


@functools.cache
def _graph() -> KnowledgeGraph:
    """The process-wide knowledge graph, built once from the customer records."""
    from ..customerData import CUSTOMERS

    return build_graph(CUSTOMERS)


def known_customer(customer_id: str) -> bool:
    graph = _graph()
    return graph.has(customer_id) and graph.is_a(customer_id, co.CUSTOMER)


@functools.cache
def reason(customer_id: str) -> ReasoningResult:
    """Runs the reasoner over ``customer_id`` and returns everything it inferred.

    Cached because the reasoner asserts its conclusions into the shared graph:
    a second run would find nothing new to conclude and so would report an empty
    inference chain.
    """
    graph = _graph()
    chain = REASONER.run(graph, customer_id)

    interactions = []
    for individual in graph.related(customer_id, co.HAD_INTERACTION):
        concept = next(iter(individual.types))
        if graph.ontology.is_a(concept, co.POSITIVE_INTERACTION):
            polarity = "positive"
        elif graph.ontology.is_a(concept, co.NEGATIVE_INTERACTION):
            polarity = "negative"
        else:
            polarity = "neutral"
        interactions.append(
            TypedInteraction(
                concept=concept,
                polarity=polarity,
                text=str(individual.data.get(co.DESCRIBED_AS, "")),
            )
        )

    states = [
        state
        for state in graph.most_specific_types(customer_id)
        if state != co.CUSTOMER
    ] or [co.CUSTOMER]

    return ReasoningResult(
        customer_id=customer_id,
        churn_score=_churn(graph, customer_id),
        days_since_last_offer=_days(graph, customer_id),
        value_segment=value_segment(graph, customer_id) or "unknown",
        risk_band=risk_band(graph, customer_id) or "unknown",
        customer_states=states,
        interactions=interactions,
        eligible_actions=eligible_actions(graph, customer_id),
        recommended_action=recommended_action(graph, customer_id),
        inferences=chain,
    )
