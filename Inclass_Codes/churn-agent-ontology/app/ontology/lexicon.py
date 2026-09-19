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

"""Grounds free-text interaction descriptions into interaction concepts.

This is the layer that turns ``"Unsubscribed from promotional emails"`` — a
string the rules cannot reason over — into ``AttritionSignalInteraction``, a
concept they can. The cues themselves are declared on the concepts in
:file:`churn_ontology.yaml` and ordered by their ``priority``, so the first
concept with a matching cue wins and "Downgraded loyalty tier" is read as an
attrition signal rather than as loyalty.
"""

from __future__ import annotations

from . import churn_ontology as co

#: (concept, cues) in cue-matching priority order, straight from the YAML.
LEXICON: tuple[tuple[str, tuple[str, ...]], ...] = co.SPEC.lexicon


def classify(text: str) -> str:
    """Returns the interaction concept ``text`` describes.

    Falls back to ``NeutralInteraction`` when no cue matches, so an
    unrecognised behaviour is recorded rather than dropped.
    """
    haystack = text.lower()
    for concept, cues in LEXICON:
        if any(cue in haystack for cue in cues):
            return concept
    return co.NEUTRAL_INTERACTION
