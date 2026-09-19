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

"""Unit tests for the workflow nodes that need no LLM call."""

from google.genai import types

from app.agent import (
    DecisionOutcome,
    ReviewerVerdict,
    apply_ontology_policy,
    assess_customer,
    parse_customer_query,
    validate_verdict,
)
from app.ontology import churn_ontology as co


def _content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


def test_parse_routes_on_whether_a_customer_is_named() -> None:
    assert (
        parse_customer_query(_content("what about c1001?")).actions.route
        == "has_customer_id"
    )
    assert parse_customer_query(_content("what about c1001?")).output == "C1001"
    assert (
        parse_customer_query(_content("hello")).actions.route == "missing_customer_id"
    )


def test_unknown_customer_routes_to_review() -> None:
    event = assess_customer("C9999")
    assert event.actions.route == "not_found"
    assert event.output.outcome is DecisionOutcome.REVIEW


def test_assessment_carries_the_ontology_view() -> None:
    assessment = assess_customer("C1001").output
    assert assessment.risk_band == co.HIGH_RISK_BAND
    assert assessment.value_segment == co.HIGH_VALUE_SEGMENT
    assert {i.concept for i in assessment.interactions} == {
        co.ATTRITION_SIGNAL_INTERACTION,
        co.COMPLAINT_INTERACTION,
        co.PURCHASE_HESITATION_INTERACTION,
    }
    assert co.HIGH_RISK_BAND in assessment.briefing


def test_policy_decides_when_the_reasoner_settled_on_an_action() -> None:
    event = apply_ontology_policy(assess_customer("C1001").output)
    assert event.actions.route == "decided"
    assert event.output.outcome is DecisionOutcome.PREMIUM_OFFER
    assert event.output.inference_chain


def test_policy_defers_ambiguous_cases_to_the_reviewer() -> None:
    event = apply_ontology_policy(assess_customer("C1003").output)
    assert event.actions.route == "needs_review"
    assert event.output.eligible_actions


def test_validation_accepts_an_eligible_verdict() -> None:
    verdict = ReviewerVerdict(
        customer_id="C1010",
        outcome=DecisionOutcome.PREMIUM_OFFER,
        rationale="DisengagedCustomer in the HighValueSegment.",
    )
    decision = validate_verdict(verdict).output
    assert decision.outcome is DecisionOutcome.PREMIUM_OFFER
    assert any("ReviewerVerdict" in step for step in decision.inference_chain)


def test_validation_downgrades_an_ineligible_verdict() -> None:
    # C1003 is in the low-value segment, so PremiumOffer is never eligible.
    verdict = ReviewerVerdict(
        customer_id="C1003",
        outcome=DecisionOutcome.PREMIUM_OFFER,
        rationale="Feels right.",
    )
    decision = validate_verdict(verdict).output
    assert decision.outcome is DecisionOutcome.REVIEW
    assert "eligibility" in decision.rationale
