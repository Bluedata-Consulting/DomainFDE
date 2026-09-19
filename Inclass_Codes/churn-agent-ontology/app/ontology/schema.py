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

"""Domain-agnostic ontology primitives.

This module is the *machinery*: concepts (a subsumption hierarchy), properties
(typed data and object properties), individuals, a knowledge graph holding
assertions about them, and a forward-chaining rule engine that records every
inference it makes so a decision can be replayed as an explanation chain.

The churn domain itself lives in :mod:`app.ontology.churn_ontology`; nothing
here knows about customers or offers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

THING = "Thing"


class PropertyKind(str, Enum):
    """Whether a property points at another individual or at a literal."""

    OBJECT = "object"
    DATA = "data"


@dataclass(frozen=True)
class Concept:
    """A class in the ontology, i.e. a node of the subsumption hierarchy."""

    name: str
    parent: str | None = THING
    label: str = ""
    comment: str = ""

    def display(self) -> str:
        return self.label or self.name


@dataclass(frozen=True)
class Property:
    """A typed relation between a concept and either a concept or a literal.

    ``range_`` names a concept for :attr:`PropertyKind.OBJECT` properties and a
    literal type (``"float"``, ``"int"``, ``"str"``, ``"bool"``) for data ones.
    ``functional`` marks properties that hold at most one value per individual.
    """

    name: str
    domain: str
    range_: str
    kind: PropertyKind = PropertyKind.DATA
    functional: bool = True
    comment: str = ""


class OntologyError(ValueError):
    """Raised when the ontology or an assertion against it is inconsistent."""


class Ontology:
    """A TBox: the concept hierarchy plus the properties defined over it."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._concepts: dict[str, Concept] = {
            THING: Concept(THING, parent=None, label="Thing", comment="Root concept.")
        }
        self._properties: dict[str, Property] = {}

    # -- authoring ---------------------------------------------------------

    def concept(
        self,
        name: str,
        parent: str = THING,
        *,
        label: str = "",
        comment: str = "",
    ) -> str:
        """Declares a concept and returns its name, so declarations can nest."""
        if name in self._concepts:
            raise OntologyError(f"Concept '{name}' is already defined.")
        if parent not in self._concepts:
            raise OntologyError(f"Parent concept '{parent}' of '{name}' is undefined.")
        self._concepts[name] = Concept(name, parent, label or name, comment)
        return name

    def property(
        self,
        name: str,
        *,
        domain: str,
        range_: str,
        kind: PropertyKind = PropertyKind.DATA,
        functional: bool = True,
        comment: str = "",
    ) -> str:
        """Declares a property and returns its name."""
        if name in self._properties:
            raise OntologyError(f"Property '{name}' is already defined.")
        if domain not in self._concepts:
            raise OntologyError(f"Domain concept '{domain}' of '{name}' is undefined.")
        if kind is PropertyKind.OBJECT and range_ not in self._concepts:
            raise OntologyError(f"Range concept '{range_}' of '{name}' is undefined.")
        self._properties[name] = Property(
            name, domain, range_, kind, functional, comment
        )
        return name

    # -- querying ----------------------------------------------------------

    def has_concept(self, name: str) -> bool:
        return name in self._concepts

    def get_concept(self, name: str) -> Concept:
        try:
            return self._concepts[name]
        except KeyError:
            raise OntologyError(f"Unknown concept '{name}'.") from None

    def get_property(self, name: str) -> Property:
        try:
            return self._properties[name]
        except KeyError:
            raise OntologyError(f"Unknown property '{name}'.") from None

    def ancestors(self, name: str, *, include_self: bool = False) -> list[str]:
        """Concepts from ``name`` up to (and including) ``Thing``."""
        chain: list[str] = [name] if include_self else []
        current = self.get_concept(name).parent
        while current is not None:
            chain.append(current)
            current = self.get_concept(current).parent
        return chain

    def is_a(self, name: str, ancestor: str) -> bool:
        """True when ``name`` is ``ancestor`` or is subsumed by it."""
        return name == ancestor or ancestor in self.ancestors(name)

    def children(self, name: str) -> list[str]:
        self.get_concept(name)
        return sorted(c.name for c in self._concepts.values() if c.parent == name)

    def descendants(self, name: str) -> list[str]:
        out: list[str] = []
        for child in self.children(name):
            out.append(child)
            out.extend(self.descendants(child))
        return out

    def most_specific(self, names: set[str]) -> list[str]:
        """Drops any concept that subsumes another concept in ``names``."""
        return sorted(
            n
            for n in names
            if not any(other != n and self.is_a(other, n) for other in names)
        )

    def properties_of(self, concept: str) -> list[Property]:
        """Properties declared on ``concept`` or on any of its ancestors."""
        lineage = set(self.ancestors(concept, include_self=True))
        return [p for p in self._properties.values() if p.domain in lineage]

    def all_properties(self) -> list[Property]:
        return list(self._properties.values())

    def __iter__(self) -> Iterator[Concept]:
        return iter(self._concepts.values())


@dataclass
class Individual:
    """An ABox entity: an id, the concepts it belongs to, and its assertions."""

    iri: str
    types: set[str] = field(default_factory=set)
    data: dict[str, Any] = field(default_factory=dict)
    relations: dict[str, list[str]] = field(default_factory=dict)

    def related(self, prop: str) -> list[str]:
        return self.relations.get(prop, [])


class KnowledgeGraph:
    """An ABox: individuals asserted against an :class:`Ontology`."""

    def __init__(self, ontology: Ontology) -> None:
        self.ontology = ontology
        self._individuals: dict[str, Individual] = {}

    def add(self, iri: str, concept: str) -> Individual:
        if iri in self._individuals:
            raise OntologyError(f"Individual '{iri}' already exists.")
        self.ontology.get_concept(concept)
        individual = Individual(iri=iri, types={concept})
        self._individuals[iri] = individual
        return individual

    def get(self, iri: str) -> Individual:
        try:
            return self._individuals[iri]
        except KeyError:
            raise OntologyError(f"Unknown individual '{iri}'.") from None

    def has(self, iri: str) -> bool:
        return iri in self._individuals

    def assert_type(self, iri: str, concept: str) -> bool:
        """Adds a type. Returns True only when this is new information."""
        self.ontology.get_concept(concept)
        individual = self.get(iri)
        if concept in individual.types:
            return False
        individual.types.add(concept)
        return True

    def is_a(self, iri: str, concept: str) -> bool:
        """True when any asserted type of ``iri`` is subsumed by ``concept``."""
        return any(self.ontology.is_a(t, concept) for t in self.get(iri).types)

    def set_data(self, iri: str, prop: str, value: Any) -> bool:
        definition = self.ontology.get_property(prop)
        if definition.kind is not PropertyKind.DATA:
            raise OntologyError(f"'{prop}' is an object property, not a data property.")
        individual = self.get(iri)
        if individual.data.get(prop) == value and prop in individual.data:
            return False
        individual.data[prop] = value
        return True

    def get_data(self, iri: str, prop: str, default: Any = None) -> Any:
        return self.get(iri).data.get(prop, default)

    def relate(self, subject: str, prop: str, obj: str) -> bool:
        definition = self.ontology.get_property(prop)
        if definition.kind is not PropertyKind.OBJECT:
            raise OntologyError(f"'{prop}' is a data property, not an object property.")
        self.get(obj)
        targets = self.get(subject).relations.setdefault(prop, [])
        if obj in targets:
            return False
        if definition.functional and targets:
            raise OntologyError(
                f"'{prop}' is functional but '{subject}' already relates to"
                f" '{targets[0]}'."
            )
        targets.append(obj)
        return True

    def related(self, subject: str, prop: str) -> list[Individual]:
        return [self.get(iri) for iri in self.get(subject).related(prop)]

    def individuals_of(self, concept: str) -> list[Individual]:
        """Every individual whose type is ``concept`` or a subconcept of it."""
        return [i for i in self._individuals.values() if self.is_a(i.iri, concept)]

    def most_specific_types(self, iri: str) -> list[str]:
        return self.ontology.most_specific(self.get(iri).types)


@dataclass(frozen=True)
class Inference:
    """One step of reasoning: which rule fired, on what grounds, concluding what."""

    rule: str
    subject: str
    premises: tuple[str, ...]
    conclusion: str


# A rule inspects the graph for one subject and returns the inferences it drew,
# having already asserted them. Returning an empty list means "did not fire".
RuleFn = Callable[[KnowledgeGraph, str], list[Inference]]


@dataclass(frozen=True)
class Rule:
    """A named, documented inference rule with a stage for ordering."""

    name: str
    stage: int
    description: str
    apply: RuleFn


class Reasoner:
    """Forward-chains a rule set over one subject until it reaches a fixpoint.

    Rules run in ``stage`` order, and the whole set repeats while any rule still
    produces new assertions, so a later stage can feed an earlier one. Every
    inference is collected in firing order, which is exactly the explanation
    chain shown to the user.
    """

    MAX_PASSES = 8

    def __init__(self, rules: list[Rule]) -> None:
        self.rules = sorted(rules, key=lambda r: (r.stage, r.name))

    def run(self, graph: KnowledgeGraph, subject: str) -> list[Inference]:
        chain: list[Inference] = []
        for _ in range(self.MAX_PASSES):
            produced = False
            for rule in self.rules:
                new = rule.apply(graph, subject)
                if new:
                    produced = True
                    chain.extend(new)
            if not produced:
                break
        return chain
