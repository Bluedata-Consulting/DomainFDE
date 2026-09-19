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

"""Unit tests for the ontology layer: the YAML TBox, grounding, and inference."""

import pytest
import yaml

from app.customerData import CUSTOMERS
from app.ontology import churn_ontology as co
from app.ontology import renderer
from app.ontology.graph import build_graph
from app.ontology.lexicon import LEXICON, classify
from app.ontology.loader import constant_name, load_ontology
from app.ontology.reasoner import REASONER, known_customer, reason
from app.ontology.schema import OntologyError, PropertyKind


def _write(tmp_path, document: dict) -> str:
    path = tmp_path / "ontology.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return str(path)


# --- loading the YAML --------------------------------------------------------


def test_the_yaml_is_the_source_of_the_python_constants() -> None:
    document = yaml.safe_load(co.ONTOLOGY_PATH.read_text(encoding="utf-8"))
    for name in document["properties"]:
        assert getattr(co, constant_name(name)) == name
    for name in document["thresholds"]:
        assert getattr(co, name) == document["thresholds"][name]
    assert co.HIGH_VALUE_SEGMENT == "HighValueSegment"
    assert co.HAS_CHURN_SCORE == "hasChurnScore"


def test_a_missing_constant_explains_itself() -> None:
    with pytest.raises(AttributeError, match=r"churn_ontology\.yaml"):
        co.PLATINUM_SEGMENT  # noqa: B018


def test_thresholds_interpolate_into_concept_comments() -> None:
    comment = co.ONTOLOGY.get_concept(co.LOW_RISK_BAND).comment
    assert f"{co.CHURN_LOW_THRESHOLD:.0%}" in comment


def test_loader_rejects_an_unknown_concept_key(tmp_path) -> None:
    path = _write(tmp_path, {"concepts": {"Customer": {"commnet": "typo"}}})
    with pytest.raises(OntologyError, match="unknown keys"):
        load_ontology(path)


def test_loader_rejects_cues_without_a_priority(tmp_path) -> None:
    path = _write(tmp_path, {"concepts": {"Signal": {"cues": ["oops"]}}})
    with pytest.raises(OntologyError, match="priority"):
        load_ontology(path)


def test_loader_rejects_a_duplicated_individual(tmp_path) -> None:
    path = _write(
        tmp_path,
        {
            "concepts": {
                "A": {"individual": "x:1"},
                "B": {"individual": "x:1"},
            }
        },
    )
    with pytest.raises(OntologyError, match="claimed twice"):
        load_ontology(path)


def test_loader_rejects_an_unresolvable_comment_placeholder(tmp_path) -> None:
    path = _write(tmp_path, {"concepts": {"A": {"comment": "{NOT_A_THRESHOLD}"}}})
    with pytest.raises(OntologyError, match="interpolate"):
        load_ontology(path)


def test_lexicon_is_ordered_by_declared_priority() -> None:
    concepts = [concept for concept, _ in LEXICON]
    assert concepts.index(co.ATTRITION_SIGNAL_INTERACTION) < concepts.index(
        co.LOYALTY_INTERACTION
    )
    assert all(co.ONTOLOGY.is_a(concept, co.INTERACTION) for concept, _ in LEXICON)


# --- TBox -------------------------------------------------------------------


def test_subsumption_is_transitive() -> None:
    assert co.ONTOLOGY.is_a(co.ADVOCACY_INTERACTION, co.POSITIVE_INTERACTION)
    assert co.ONTOLOGY.is_a(co.ADVOCACY_INTERACTION, co.INTERACTION)
    assert not co.ONTOLOGY.is_a(co.ADVOCACY_INTERACTION, co.NEGATIVE_INTERACTION)


def test_every_action_maps_to_an_outcome() -> None:
    assert set(co.ONTOLOGY.descendants(co.RETENTION_ACTION)) == set(
        co.OUTCOME_BY_ACTION
    )
    assert set(co.ACTION_INDIVIDUALS) == set(co.OUTCOME_BY_ACTION)


def test_redefining_a_concept_is_rejected() -> None:
    with pytest.raises(OntologyError):
        co.ONTOLOGY.concept(co.CUSTOMER)


def test_most_specific_drops_ancestors() -> None:
    assert co.ONTOLOGY.most_specific(
        {co.INTERACTION, co.POSITIVE_INTERACTION, co.ADVOCACY_INTERACTION}
    ) == [co.ADVOCACY_INTERACTION]


# --- grounding --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Unsubscribed from promotional emails", co.ATTRITION_SIGNAL_INTERACTION),
        ("Downgraded loyalty tier due to inactivity", co.ATTRITION_SIGNAL_INTERACTION),
        ("Filed a complaint about pricing discrepancy", co.COMPLAINT_INTERACTION),
        (
            "Compared prices with competitor via chatbot",
            co.COMPETITOR_INTEREST_INTERACTION,
        ),
        ("No app logins in the last 60 days", co.DISENGAGEMENT_INTERACTION),
        ("Abandoned cart with 3 items over $150", co.PURCHASE_HESITATION_INTERACTION),
        ("Exchanged a defective product in-store", co.RETURN_INTERACTION),
        ("Attended VIP early-access sale event", co.LOYALTY_INTERACTION),
        ("Referred a friend using referral code", co.ADVOCACY_INTERACTION),
        ("Redeemed a 15% off coupon in-store", co.PROMOTION_REDEMPTION_INTERACTION),
        ("Something entirely unforeseen happened", co.NEUTRAL_INTERACTION),
    ],
)
def test_lexicon_grounds_text_into_the_taxonomy(text: str, expected: str) -> None:
    assert classify(text) == expected


def test_unknown_segment_is_rejected_rather_than_guessed() -> None:
    with pytest.raises(OntologyError):
        build_graph(
            {
                "C0001": {
                    "customer_id": "C0001",
                    "churn_score": 0.5,
                    "clv_segment": "Platinum",
                    "days_since_last_offer": 10,
                    "recent_interactions": [],
                }
            }
        )


def test_graph_holds_every_customer_and_their_interactions() -> None:
    graph = build_graph(CUSTOMERS)
    assert len(graph.individuals_of(co.CUSTOMER)) == len(CUSTOMERS)
    assert graph.related("C1001", co.HAD_INTERACTION)


def test_functional_property_rejects_a_second_value() -> None:
    graph = build_graph(CUSTOMERS)
    with pytest.raises(OntologyError):
        graph.relate(
            "C1001",
            co.HAS_VALUE_SEGMENT,
            co.SEGMENT_INDIVIDUALS[co.LOW_VALUE_SEGMENT],
        )


def test_object_and_data_properties_are_not_interchangeable() -> None:
    graph = build_graph(CUSTOMERS)
    with pytest.raises(OntologyError):
        graph.set_data("C1001", co.HAS_RISK_BAND, "whatever")
    assert co.ONTOLOGY.get_property(co.HAS_CHURN_SCORE).kind is PropertyKind.DATA


# --- inference --------------------------------------------------------------


@pytest.mark.parametrize(
    ("customer_id", "band", "action"),
    [
        ("C1001", co.HIGH_RISK_BAND, co.PREMIUM_OFFER),
        ("C1005", co.HIGH_RISK_BAND, co.STANDARD_OFFER),
        ("C1002", co.LOW_RISK_BAND, co.NO_ACTION),
        ("C1007", co.LOW_RISK_BAND, co.NO_ACTION),
    ],
)
def test_deterministic_cases_resolve_without_the_reviewer(
    customer_id: str, band: str, action: str
) -> None:
    result = reason(customer_id)
    assert result.risk_band == band
    assert result.recommended_action == action
    assert not result.is_ambiguous


@pytest.mark.parametrize("customer_id", ["C1003", "C1006", "C1008", "C1010"])
def test_ambiguous_cases_are_left_to_the_reviewer(customer_id: str) -> None:
    result = reason(customer_id)
    assert result.is_ambiguous
    assert result.recommended_action is None


def test_premium_offer_requires_the_high_value_segment() -> None:
    # C1005 is at high risk but only medium value, so the premium constraint fails.
    assert co.PREMIUM_OFFER not in reason("C1005").eligible_actions
    assert co.STANDARD_OFFER in reason("C1005").eligible_actions


def test_premium_offer_is_inferred_for_a_disengaged_high_value_customer() -> None:
    # C1010 sits in the moderate band, so premium eligibility comes only from
    # being a DisengagedCustomer in the high-value segment.
    result = reason("C1010")
    assert result.risk_band == co.MODERATE_RISK_BAND
    assert co.DISENGAGED_CUSTOMER in result.customer_states
    assert co.PREMIUM_OFFER in result.eligible_actions


def test_offer_fatigue_blocks_offers() -> None:
    # C1002 was incentivised 12 days ago, inside the fatigue window.
    result = reason("C1002")
    assert co.RECENTLY_INCENTIVISED_CUSTOMER in result.customer_states
    assert co.STANDARD_OFFER not in result.eligible_actions
    assert co.PREMIUM_OFFER not in result.eligible_actions


def test_explicit_attrition_signal_is_detected() -> None:
    # "Requested account deletion information"
    assert co.ATTRITION_RISK_CUSTOMER in reason("C1005").customer_states


def test_every_decision_carries_an_explanation_chain() -> None:
    for customer_id in CUSTOMERS:
        result = reason(customer_id)
        assert result.chain(), f"{customer_id} produced no inferences"
        assert any("hasRiskBand" in step for step in result.chain())


def test_recommended_action_is_always_eligible() -> None:
    for customer_id in CUSTOMERS:
        result = reason(customer_id)
        if result.recommended_action is not None:
            assert result.recommended_action in result.eligible_actions


def test_no_action_and_review_are_always_available() -> None:
    for customer_id in CUSTOMERS:
        eligible = reason(customer_id).eligible_actions
        assert co.NO_ACTION in eligible
        assert co.HUMAN_REVIEW in eligible


def test_unknown_customer_is_not_in_the_graph() -> None:
    assert known_customer("C1001")
    assert not known_customer("C9999")


# --- rendering ---------------------------------------------------------------


def test_rendered_ontology_covers_every_concept_and_property() -> None:
    rendered = renderer.render_ontology(co.ONTOLOGY)
    for concept in co.ONTOLOGY:
        assert concept.name in rendered
    for prop in co.ONTOLOGY.all_properties():
        assert prop.name in rendered


def test_briefing_names_the_eligible_actions_and_the_chain() -> None:
    result = reason("C1010")
    briefing = renderer.render_briefing(result)
    assert "ELIGIBLE ACTIONS" in briefing
    for action in result.eligible_actions:
        assert action in briefing
    assert co.MODERATE_RISK_BAND in briefing


def test_rule_set_is_documented() -> None:
    described = renderer.render_rules(REASONER)
    for rule in REASONER.rules:
        assert rule.name in described
        assert rule.description
