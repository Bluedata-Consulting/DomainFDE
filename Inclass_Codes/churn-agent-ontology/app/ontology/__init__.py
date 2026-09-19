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

"""The ontology layer: a shared vocabulary the whole agent reasons over.

- :file:`churn_ontology.yaml` — the TBox itself, declarative: concepts,
  properties, thresholds, and the cues that ground text into the taxonomy.
- :mod:`.schema` — domain-agnostic concepts, properties, individuals, rules.
- :mod:`.loader` — turns the YAML into an :class:`.schema.Ontology`.
- :mod:`.churn_ontology` — the loaded ontology and its constants.
- :mod:`.lexicon` — classifies free-text interactions using the YAML's cues.
- :mod:`.graph` — builds the ABox from customer records.
- :mod:`.reasoner` — the rules, and :func:`.reasoner.reason` as the entry point.
- :mod:`.renderer` — every text surface: prompts, briefings, answers.
"""

from . import renderer
from .churn_ontology import ONTOLOGY, OUTCOME_BY_ACTION, SPEC
from .loader import OntologySpec, load_ontology
from .reasoner import REASONER, ReasoningResult, known_customer, reason
from .schema import Inference, KnowledgeGraph, Ontology

__all__ = [
    "ONTOLOGY",
    "OUTCOME_BY_ACTION",
    "REASONER",
    "SPEC",
    "Inference",
    "KnowledgeGraph",
    "Ontology",
    "OntologySpec",
    "ReasoningResult",
    "known_customer",
    "load_ontology",
    "reason",
    "renderer",
]
