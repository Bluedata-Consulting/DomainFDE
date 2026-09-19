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

"""Loads a declarative YAML TBox into an :class:`~app.ontology.schema.Ontology`.

The loader is strict on purpose: an unknown key, a duplicate individual, a
threshold placeholder that does not resolve, or two names that would collide as
module constants all fail at import time rather than misbehaving at decision
time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .schema import THING, Ontology, OntologyError, PropertyKind

#: Keys a concept node may carry. Anything else is a typo.
_CONCEPT_KEYS = frozenset(
    {"comment", "children", "individual", "matches", "outcome", "cues", "priority"}
)
_PROPERTY_KEYS = frozenset({"domain", "range", "kind", "functional", "comment"})
_DOCUMENT_KEYS = frozenset(
    {"name", "description", "thresholds", "concepts", "properties"}
)

_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def constant_name(name: str) -> str:
    """``HighValueSegment`` -> ``HIGH_VALUE_SEGMENT``; ``hasRiskBand`` -> ``HAS_RISK_BAND``."""
    return _BOUNDARY.sub("_", name).upper()


@dataclass(frozen=True)
class OntologySpec:
    """An ontology plus the domain tables the YAML declared alongside it."""

    ontology: Ontology
    description: str
    thresholds: dict[str, Any]
    #: concept -> IRI of its one canonical individual
    individuals: dict[str, str]
    #: retention-action concept -> DecisionOutcome name
    outcome_by_action: dict[str, str]
    #: raw ``clv_segment`` label -> segment concept
    segment_by_label: dict[str, str]
    #: (concept, cues) in cue-matching priority order
    lexicon: tuple[tuple[str, tuple[str, ...]], ...]

    def individuals_under(self, root: str) -> dict[str, str]:
        """The individuals of ``root``'s subconcepts, keyed by concept."""
        under = set(self.ontology.descendants(root))
        return {c: iri for c, iri in self.individuals.items() if c in under}

    def constants(self) -> dict[str, Any]:
        """Every concept, property and threshold, keyed by its constant name.

        :mod:`app.ontology.churn_ontology` injects these into its namespace, so
        ``co.HIGH_RISK_BAND`` and the YAML stay in step by construction.
        """
        out: dict[str, Any] = dict(self.thresholds)
        for name in [c.name for c in self.ontology] + [
            p.name for p in self.ontology.all_properties()
        ]:
            key = constant_name(name)
            if key in out:
                raise OntologyError(
                    f"'{name}' collides with '{key}', which is already defined."
                )
            out[key] = name
        return out


def _require_mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise OntologyError(f"{where} must be a mapping, got {type(value).__name__}.")
    return value


def _interpolate(text: str, thresholds: dict[str, Any], where: str) -> str:
    try:
        return text.format(**thresholds)
    except (KeyError, IndexError, ValueError) as exc:
        raise OntologyError(
            f"Cannot interpolate the comment on {where}: {exc}"
        ) from exc


class _Builder:
    """Walks the YAML document, asserting it into a fresh :class:`Ontology`."""

    def __init__(self, document: dict[str, Any]) -> None:
        if unknown := set(document) - _DOCUMENT_KEYS:
            raise OntologyError(f"Unknown top-level keys: {sorted(unknown)}.")
        self.document = document
        self.thresholds = _require_mapping(document.get("thresholds"), "thresholds")
        self.ontology = Ontology(document.get("name", "ontology"))
        self.individuals: dict[str, str] = {}
        self.outcome_by_action: dict[str, str] = {}
        self.segment_by_label: dict[str, str] = {}
        self.cues: list[tuple[int, str, tuple[str, ...]]] = []

    def build(self) -> OntologySpec:
        self._add_concepts(
            _require_mapping(self.document.get("concepts"), "concepts"), THING
        )
        self._add_properties(
            _require_mapping(self.document.get("properties"), "properties")
        )
        return OntologySpec(
            ontology=self.ontology,
            description=self.document.get("description", ""),
            thresholds=dict(self.thresholds),
            individuals=self.individuals,
            outcome_by_action=self.outcome_by_action,
            segment_by_label=self.segment_by_label,
            lexicon=tuple((concept, cues) for _, concept, cues in sorted(self.cues)),
        )

    def _add_concepts(self, nodes: dict[str, Any], parent: str) -> None:
        for name, raw in nodes.items():
            node = _require_mapping(raw, f"concept '{name}'")
            if unknown := set(node) - _CONCEPT_KEYS:
                raise OntologyError(
                    f"Concept '{name}' has unknown keys: {sorted(unknown)}."
                )

            comment = str(node.get("comment", ""))
            self.ontology.concept(
                name,
                parent,
                comment=_interpolate(comment, self.thresholds, f"concept '{name}'"),
            )

            if iri := node.get("individual"):
                if iri in self.individuals.values():
                    raise OntologyError(f"Individual '{iri}' is claimed twice.")
                self.individuals[name] = str(iri)
            if outcome := node.get("outcome"):
                self.outcome_by_action[name] = str(outcome)
            if (label := node.get("matches")) is not None:
                self.segment_by_label[str(label).strip().lower()] = name
            if cues := node.get("cues"):
                priority = node.get("priority")
                if priority is None:
                    raise OntologyError(f"Concept '{name}' has cues but no priority.")
                self.cues.append((int(priority), name, tuple(str(c) for c in cues)))

            self._add_concepts(
                _require_mapping(node.get("children"), f"children of '{name}'"), name
            )

    def _add_properties(self, nodes: dict[str, Any]) -> None:
        for name, raw in nodes.items():
            node = _require_mapping(raw, f"property '{name}'")
            if unknown := set(node) - _PROPERTY_KEYS:
                raise OntologyError(
                    f"Property '{name}' has unknown keys: {sorted(unknown)}."
                )
            try:
                kind = PropertyKind(str(node.get("kind", "data")))
            except ValueError as exc:
                raise OntologyError(f"Property '{name}': {exc}") from exc
            self.ontology.property(
                name,
                domain=str(node["domain"]),
                range_=str(node["range"]),
                kind=kind,
                functional=bool(node.get("functional", True)),
                comment=str(node.get("comment", "")),
            )


def load_ontology(path: str | Path) -> OntologySpec:
    """Reads a YAML TBox from ``path`` and builds its :class:`OntologySpec`."""
    text = Path(path).read_text(encoding="utf-8")
    document = _require_mapping(yaml.safe_load(text), f"the document at {path}")
    if not document:
        raise OntologyError(f"The ontology at {path} is empty.")
    return _Builder(document).build()
