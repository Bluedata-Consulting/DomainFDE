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

"""Builds the ABox: customer records as individuals in a knowledge graph.

The source records stay exactly as the baseline agent has them — a plain dict.
Everything the agent reasons over is derived here, so swapping the dict for a
warehouse query later changes only this module.
"""

from __future__ import annotations

from typing import Any

from . import churn_ontology as co
from .lexicon import classify
from .schema import KnowledgeGraph, OntologyError


def _add_singletons(graph: KnowledgeGraph) -> None:
    """Creates the one canonical individual per segment, band and action."""
    for mapping in (
        co.SEGMENT_INDIVIDUALS,
        co.BAND_INDIVIDUALS,
        co.ACTION_INDIVIDUALS,
    ):
        for concept, iri in mapping.items():
            graph.add(iri, concept)


def add_customer(graph: KnowledgeGraph, record: dict[str, Any]) -> str:
    """Asserts one customer record into ``graph`` and returns its IRI."""
    iri = record["customer_id"]
    graph.add(iri, co.CUSTOMER)
    graph.set_data(iri, co.HAS_CHURN_SCORE, float(record["churn_score"]))
    graph.set_data(iri, co.DAYS_SINCE_LAST_OFFER, int(record["days_since_last_offer"]))

    segment_label = str(record["clv_segment"]).strip().lower()
    segment_concept = co.SEGMENT_BY_LABEL.get(segment_label)
    if segment_concept is None:
        raise OntologyError(
            f"Customer '{iri}' has CLV segment '{record['clv_segment']}', which maps"
            " to no ValueSegment concept."
        )
    graph.relate(iri, co.HAS_VALUE_SEGMENT, co.SEGMENT_INDIVIDUALS[segment_concept])

    for index, text in enumerate(record.get("recent_interactions", [])):
        interaction_iri = f"{iri}/interaction/{index}"
        graph.add(interaction_iri, classify(text))
        graph.set_data(interaction_iri, co.DESCRIBED_AS, text)
        graph.relate(iri, co.HAD_INTERACTION, interaction_iri)

    return iri


def build_graph(customers: dict[str, dict[str, Any]]) -> KnowledgeGraph:
    """Builds a knowledge graph holding every customer in ``customers``."""
    graph = KnowledgeGraph(co.ONTOLOGY)
    _add_singletons(graph)
    for record in customers.values():
        add_customer(graph, record)
    return graph
