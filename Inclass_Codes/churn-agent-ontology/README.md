# churn-agent-ontology

The churn agent with an ontology layer. A copy of `../churn-agent`, which is left
untouched as the baseline; all ontology work happens here.

Agent generated with `agents-cli` version `1.6.1`

## Project Structure

```
churn-agent-ontology/
├── app/         # Core agent code
│   ├── agent.py               # Workflow: parse → assess → policy → review → validate
│   ├── customerData.py        # Source customer records (unchanged from baseline)
│   ├── ontology/              # The ontology layer
│   │   ├── churn_ontology.yaml#   THE TBOX — concepts, properties, thresholds, cues
│   │   ├── schema.py          #   concepts, properties, individuals, rule engine
│   │   ├── loader.py          #   YAML → Ontology, strictly validated
│   │   ├── churn_ontology.py  #   the loaded ontology, as Python constants
│   │   ├── lexicon.py         #   free text → interaction taxonomy
│   │   ├── graph.py           #   customer records → knowledge graph (ABox)
│   │   ├── reasoner.py        #   the rules, and `reason()` as the entry point
│   │   └── renderer.py        #   every text surface: prompt, briefing, answer
│   ├── fast_api_app.py        # FastAPI Backend server
│   └── app_utils/             # App utilities and helpers
├── tests/                     # Unit, integration, and load tests
├── GEMINI.md                  # AI-assisted development guide
└── pyproject.toml             # Project dependencies
```

## The ontology layer

The baseline agent reasons over raw fields: a float, a string segment, and a list
of untyped sentences. This version reasons over a **shared vocabulary** instead.

**1. A TBox** (`churn_ontology.yaml`) — declarative, and the single source for
the vocabulary: a subsumption hierarchy and typed properties. `Customer` and its
inferred states (`EngagedCustomer`, `DisengagedCustomer`, `AttritionRiskCustomer`,
`RecentlyIncentivisedCustomer`), `ValueSegment`, `RiskBand`, an `Interaction`
taxonomy, and `RetentionAction` with its four subconcepts. Properties are typed
and checked: `hasRiskBand` is a functional object property, `hasChurnScore` a
data property. Thresholds live beside the concepts they define — and interpolate
into their comments — because a threshold is what ties a number to a concept.

`loader.py` builds the `Ontology` from it, strictly: an unknown key, a duplicate
individual, an unresolvable threshold placeholder or a name collision all fail at
import time. `churn_ontology.py` is then only the Python face of the file —
every concept, property and threshold becomes a module constant under its
screaming-snake name (`HighValueSegment` → `co.HIGH_VALUE_SEGMENT`,
`hasChurnScore` → `co.HAS_CHURN_SCORE`), so the code and the YAML cannot drift.

**2. Grounding** (`lexicon.py`) — turns `"Downgraded loyalty tier due to
inactivity"` into `AttritionSignalInteraction`, a concept the rules can reason
over. The cues are declared on the concepts themselves in the YAML and ordered by
their `priority`, so that example reads as attrition rather than loyalty.

**3. An ABox** (`graph.py`) — customer records become individuals in a knowledge
graph. Swapping the hardcoded dict for a warehouse query touches only this file.

**4. A reasoner** (`reasoner.py`) — a forward-chaining rule engine that runs in
four stages: classification → customer state → **eligibility** → recommendation.
Every conclusion is recorded as an `Inference` naming the rule, its premises, and
what it concluded, so a decision replays as an explanation chain.

**5. A renderer** (`renderer.py`) — every text surface in one place: the ontology
and rule set as prompt text, the per-customer briefing, the inference chain, and
the final user-facing answer. The schema, the reasoner and `agent.py` hold no
presentation, so wording changes touch one file.

The important shift is *eligibility*. `PremiumOffer` is not something a rule
hardcodes an outcome to; it is a concept with constraints — the high-value
segment, high risk (or moderate risk while disengaged), and no offer fatigue.
Rules recommend, but only from what is eligible.

### What changed in the workflow

| Baseline | Ontology edition |
| --- | --- |
| `lookup_customer` → `CustomerProfile` | `assess_customer` → runs the reasoner, returns the full ontology view |
| `evaluate_rules` on raw fields | `apply_ontology_policy` on inferred concepts and eligibility |
| Reviewer sees the raw profile | Reviewer is briefed with the concept hierarchy, the rule set, the typed interactions, and **may only choose among eligible actions** |
| Reviewer output shipped as-is | `validate_verdict` re-checks the pick against eligibility and downgrades an ineligible one to `REVIEW` |
| Answer is one sentence | Answer carries the inference chain and the eligible action set |

Deterministic outcomes are unchanged from the baseline — the same customers
resolve to the same actions — but each now cites why, and the ambiguous cases
reach the LLM with a constrained, typed brief instead of a raw record.

> 💡 **Tip:** Use [Antigravity CLI](https://antigravity.google/) for AI-assisted development - project context is pre-configured in `GEMINI.md`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **agents-cli**: Agents CLI - Install with `uv tool install google-agents-cli`
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)


## Quick Start

Install `agents-cli` and its skills if not already installed:

```bash
uvx google-agents-cli setup
```

Install required packages:

```bash
agents-cli install
```

Test the agent with a local web server:

```bash
agents-cli playground
```

You can also use features from the [ADK](https://adk.dev/) CLI with `uv run adk`.

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `agents-cli install` | Install dependencies using uv                                                         |
| `agents-cli playground` | Launch local development environment                                                  |
| `agents-cli lint`    | Run code quality checks                                                               |
| `agents-cli eval`    | Evaluate agent behavior (generate, grade, analyze, and more — see `agents-cli eval --help`) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests                                                        || [A2A Inspector](https://github.com/a2aproject/a2a-inspector) | Launch A2A Protocol Inspector                                                        |

## 🛠️ Project Management

| Command | What It Does |
|---------|--------------|
| `agents-cli scaffold enhance` | Add CI/CD pipelines and Terraform infrastructure |
| `agents-cli infra cicd` | One-command setup of entire CI/CD pipeline + infrastructure |
| `agents-cli scaffold upgrade` | Auto-upgrade to latest version while preserving customizations |

---

## Development

Edit your agent logic in `app/agent.py` and test with `agents-cli playground` - it auto-reloads on save.

Most changes belong in the ontology rather than in `agent.py`, and most of those
are edits to `churn_ontology.yaml` rather than to any Python:

- **New behaviour to recognise?** Add `cues` (and a `priority`) to a concept in
  the YAML, adding a subconcept of `Interaction` if none fits.
- **New action?** Add a subconcept of `RetentionAction` in the YAML with its
  `individual` and `outcome`, then an eligibility rule for it.
- **Different thresholds?** Edit the `thresholds` block — the comments that cite
  them update with it.
- **New policy?** Add a `Rule` to `RULES` in `reasoner.py` at the right stage.
  Rules are idempotent: return `[]` when there is nothing new to conclude.
- **Different wording?** `renderer.py`, and nowhere else.

Run `uv run pytest tests/unit` after any of these — `tests/unit/test_ontology.py`
checks the TBox stays consistent, grounding stays correct, and no recommended
action can escape its eligibility constraints.

## Deployment

```bash
gcloud config set project <your-project-id>
agents-cli deploy
```

To add CI/CD and Terraform, run `agents-cli scaffold enhance`.
To set up your production infrastructure, run `agents-cli infra cicd`.

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.

## A2A Inspector

This agent supports the [A2A Protocol](https://a2a-protocol.org/). Use the [A2A Inspector](https://github.com/a2aproject/a2a-inspector) to test interoperability.
See the [A2A Inspector docs](https://github.com/a2aproject/a2a-inspector) for details.
