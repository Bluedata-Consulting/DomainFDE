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

"""The retail-churn ontology, loaded from :file:`churn_ontology.yaml`.

The TBox itself is declarative and lives in the YAML; this module is only the
Python face of it. Every concept, property and threshold declared there becomes
a module constant under its screaming-snake name, so the rest of the codebase
keeps writing ``co.HIGH_RISK_BAND`` and ``co.OFFER_FATIGUE_DAYS`` and cannot
drift from the file:

    HighValueSegment -> HIGH_VALUE_SEGMENT
    hasChurnScore    -> HAS_CHURN_SCORE

To change the vocabulary, edit the YAML — not this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .loader import constant_name, load_ontology

ONTOLOGY_PATH = Path(__file__).with_name("churn_ontology.yaml")

SPEC = load_ontology(ONTOLOGY_PATH)
ONTOLOGY = SPEC.ontology

# Concepts, properties and thresholds, as module constants. Names are generated,
# so a static checker cannot see them; `__getattr__` below turns a typo into a
# clear error instead of a bare AttributeError.
_CONSTANTS: dict[str, Any] = SPEC.constants()
globals().update(_CONSTANTS)

# --- lookup tables derived from the YAML ------------------------------------

#: Segment, band and action concepts mapped to their canonical individual.
SEGMENT_INDIVIDUALS = SPEC.individuals_under(_CONSTANTS["VALUE_SEGMENT"])
BAND_INDIVIDUALS = SPEC.individuals_under(_CONSTANTS["RISK_BAND"])
ACTION_INDIVIDUALS = SPEC.individuals_under(_CONSTANTS["RETENTION_ACTION"])

#: Raw ``clv_segment`` label -> segment concept.
SEGMENT_BY_LABEL = SPEC.segment_by_label

#: Retention-action concept <-> the outcome name the agent emits.
OUTCOME_BY_ACTION = SPEC.outcome_by_action
ACTION_BY_OUTCOME = {outcome: action for action, outcome in OUTCOME_BY_ACTION.items()}


def __getattr__(name: str) -> Any:
    known = ", ".join(sorted(_CONSTANTS)[:8])
    raise AttributeError(
        f"'{name}' is not defined by {ONTOLOGY_PATH.name}. Concepts and properties"
        f" are exposed under their constant name (e.g. {known}, ...); add the"
        f" concept to the YAML, or check the spelling of"
        f" '{constant_name(name)}'."
    )


def __dir__() -> list[str]:
    return sorted({*globals(), *_CONSTANTS})
