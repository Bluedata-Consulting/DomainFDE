# Meridian agent ladder -- eval report

Rungs with results: none

## 1. Failure class by rung

| failure class | V0 | V1 | V2 | V3 | V4 | V5 |
|---|---|---|---|---|---|---|
| *pass, deterministic* | — | — | — | — | — | — |
| *pass, judged* | — | — | — | — | — | — |
| vocab | — | — | — | — | — | — |
| entity | — | — | — | — | — | — |
| tool | — | — | — | — | — | — |
| params | — | — | — | — | — | — |
| metric | — | — | — | — | — | — |
| ungrounded | — | — | — | — | — | — |
| authority | — | — | — | — | — | — |
| citation | — | — | — | — | — | — |
| *attributed by evidence / watch list* | — | — | — | — | — | — |

Cell = deterministic+judged failing cases attributed to the class. A case can carry more than one class. *Watch list* = no direct evidence; the dataset's declared failure_watch for the case was used.

## 2. V0 → V1 semantic delta

_V0 → V1 semantic delta: needs both results_v0.json and results_v1.json._

## 3. First passing rung vs expected

as expected: 0  earlier: 0  later: 0  never passed: 0  not testable: 31  regression: 0

✓/✗ decided by rule; ✓ʲ/✗ʲ decided by the judge (model opinion); · not run; ? unscored.

_Every case first passed at its expected rung._

## 4. Expected-fail cases

| case | question | V0 | V1 | V2 | V3 | V4 | V5 |
|---|---|---|---|---|---|---|---|
| C18 | Should we drop Finca La Esperanza as a supplier? | · | · | · | · | · | · |
| C19 | Is Rosewood still worth keeping as a flagship account? | · | · | · | · | · | · |

_No agent runs yet._

## 5. RAG layers (V5)

|  | retrieval | generation | e2e |
|---|---|---|---|
| recall@5 | 0.623 | — | — |
| precision@5 / MRR | 0.2 / 0.662 | — | — |
| superseded leakage (hard fail) | none | — | — |
| citation accurate (rule) | — | — | — |
| citation present (rule) | — | — | — |
| value correct (rule) | — | — | — |
| value correct (judged) | — | — | — |
| conditions complete (judged) | — | — | — |
| faithfulness (judged) | — | — | — |
| routing correct (rule) | — | — | — |
| synthesis (judged) | — | — | — |
| adversarial failures | none | — | — |

Retrieval mode: **hybrid**. Layers are never blended. Adversarial cases are pass/fail and excluded from every fraction. Last runs -- retrieval: 2026-09-28T17:00:35+00:00.

## 6. Retrieval by case (V5, no LLM)

Mode **hybrid**, k=5, ran 2026-09-28T17:00:35+00:00. 

| case | category | recall@5 | precision@5 | MRR | leakage | missed | retrieved (rank order, top 5) |
|---|---|---|---|---|---|---|---|
| R01 | rule_lookup | 0.00 | 0.00 | 0.00 | ok | MR-CC-POL-004 §6 | 1. MR-CC-POL-004 §5<br>2. MR-CC-POL-004 §4<br>3. MR-CC-POL-004 §1<br>4. MR-CC-POL-004 §2<br>5. MR-PROC-HB-003 §10 |
| R02 | rule_lookup | 1.00 | 0.20 | 1.00 | ok | — | 1. MR-QA-STD-002 §3.1<br>2. MR-QA-STD-002 §5.3<br>3. MR-QA-STD-002 §2.2<br>4. MR-OPS-PM-ARCHIVE §INC-2024-11<br>5. MR-PROC-HB-003 §3.3 |
| R03 | rule_lookup | 1.00 | 0.20 | 1.00 | ok | — | 1. MR-PROC-HB-003 §3.2<br>2. MR-PROC-HB-003 §3.3<br>3. MR-PROC-HB-003 §4.3<br>4. MR-PROC-HB-003 §3.4<br>5. MR-PROC-HB-003 §3.1 |
| R04 | rule_lookup | 1.00 | 0.20 | 1.00 | ok | — | 1. MR-QA-STD-002 §4<br>2. MR-QA-STD-002 §2.1<br>3. MR-OPS-PM-ARCHIVE §INC-2024-11<br>4. MR-QA-STD-002 §1<br>5. MR-QA-STD-002 §10 |
| R05 | rule_lookup | 1.00 | 0.20 | 0.50 | ok | — | 1. MR-CC-POL-004 §4<br>2. MR-CC-POL-004 §7.3<br>3. MR-CC-POL-004 §5<br>4. MR-CC-POL-004 §6<br>5. MR-CC-POL-004 §7.1 |
| R06 | cross_document | 0.33 | 0.20 | 1.00 | ok | MR-CC-POL-004 §7.1, MR-PROC-HB-003 §9.3 | 1. MR-PROC-HB-003 §9.2<br>2. MR-PROC-HB-003 §3.1<br>3. MR-OPS-PM-ARCHIVE §INC-2024-11<br>4. MR-PROC-HB-003 §3.4<br>5. MR-QA-STD-002 §5.4 |
| R07 | cross_document | 0.50 | 0.20 | 1.00 | ok | MR-PROC-HB-003 §5 | 1. MR-QA-STD-002 §5.3<br>2. MR-OPS-PM-ARCHIVE §INC-2024-11<br>3. MR-QA-STD-002 §3.1<br>4. MR-QA-STD-002 §5.2<br>5. MR-QA-STD-002 §4 |
| R08 | cross_document | 0.50 | 0.40 | 1.00 | ok | MR-PROC-HB-003 §11.1, MR-QA-STD-002 §5.4 | 1. MR-OPS-PM-ARCHIVE §INC-2024-11<br>2. MR-PROC-HB-003 §9.2<br>3. MR-PROC-HB-003 §3.4<br>4. MR-CC-POL-004 §7.1<br>5. MR-PROC-HB-003 §2 |
| R09 | cross_document | 0.33 | 0.20 | 0.25 | ok | MR-CC-POL-004 §7.1, MR-CC-POL-004 §7.3 | 1. MR-CC-POL-004 §7.2<br>2. MR-OPS-PM-ARCHIVE §INC-2024-11<br>3. MR-QA-STD-002 §5.5<br>4. MR-QA-STD-002 §9<br>5. MR-QA-STD-002 §4 |
| R10 | rule_plus_db | 0.67 | 0.40 | 1.00 | ok | MR-PROC-HB-003 §11.1 | 1. MR-PROC-HB-003 §3.1<br>2. MR-PROC-HB-003 §10<br>3. MR-PROC-HB-003 §9.2<br>4. MR-PROC-HB-003 §11.3<br>5. MR-PROC-HB-003 §4.2 |
| R11 | rule_plus_db | 0.50 | 0.20 | 0.33 | ok | MR-QA-STD-002 §5.3 | 1. MR-OPS-PM-ARCHIVE §INC-2024-11<br>2. MR-QA-STD-002 §3.1<br>3. MR-QA-STD-002 §5.4<br>4. MR-QA-STD-002 §10<br>5. MR-QA-STD-002 §5.1 |
| R12 | rule_plus_db | 0.00 | 0.00 | 0.00 | ok | MR-QA-STD-002 §5.4 | 1. MR-OPS-PM-ARCHIVE §INC-2024-11<br>2. MR-QA-STD-002 §3.1<br>3. MR-OPS-PM-ARCHIVE §INC-2024-03<br>4. MR-QA-STD-002 §10<br>5. MR-QA-STD-002 §5.1 |
| R13 | rule_plus_db | 0.00 | 0.00 | 0.00 | ok | MR-CC-POL-004 §6, MR-CC-POL-004 §7.3 | 1. MR-OPS-PM-ARCHIVE §INC-2024-11<br>2. MR-PROC-HB-003 §5<br>3. MR-OPS-PM-ARCHIVE §INC-2024-03<br>4. MR-QA-STD-002 §10<br>5. MR-PROC-HB-003 §7 |
| R14 | institutional_memory | 1.00 | 0.20 | 1.00 | ok | — | 1. MR-OPS-PM-ARCHIVE §INC-2024-11<br>2. MR-QA-STD-002 §5.1<br>3. MR-QA-STD-002 §10<br>4. MR-QA-STD-002 §3.1<br>5. MR-QA-STD-002 §5 |
| R15 | institutional_memory | 1.00 | 0.40 | 0.50 | ok | — | 1. MR-OPS-PM-ARCHIVE §INC-2024-03<br>2. MR-OPS-PM-ARCHIVE §INC-2025-12<br>3. MR-OPS-PM-ARCHIVE §INC-2024-11<br>4. MR-OPS-PM-ARCHIVE §INC-2025-09<br>5. MR-OPS-PM-ARCHIVE §INC-2025-04 |
| R16 | institutional_memory | 1.00 | 0.20 | 1.00 | ok | — | 1. MR-OPS-PM-ARCHIVE §INC-2025-12<br>2. MR-OPS-PM-ARCHIVE §INC-2024-11<br>3. MR-OPS-PM-ARCHIVE §INC-2024-03<br>4. MR-OPS-PM-ARCHIVE §INC-2025-09<br>5. MR-PROC-HB-003 §11.1 |
| R17 | adversarial_superseded | 0.00 | 0.00 | 0.00 | ok | MR-CC-POL-004 §5.2 | 1. MR-OPS-PM-ARCHIVE §INC-2024-11<br>2. MR-OPS-PM-ARCHIVE §INC-2024-03<br>3. MR-CC-POL-004 §4<br>4. MR-OPS-PM-ARCHIVE §INC-2025-12<br>5. MR-CC-POL-004 §10 |
| R18 | adversarial_not_in_corpus | — | — | — | ok | — | 1. MR-CC-POL-004 §1<br>2. MR-CC-POL-004 §5.3<br>3. MR-OPS-PM-ARCHIVE §INC-2024-11<br>4. MR-CC-POL-004 §9<br>5. MR-CC-POL-004 §4 |
| R19 | adversarial_near_miss | 1.00 | 0.40 | 1.00 | ok | — | 1. MR-PROC-HB-003 §9.2<br>2. MR-OPS-PM-ARCHIVE §INC-2024-11<br>3. MR-PROC-HB-003 §3.2<br>4. MR-PROC-HB-003 §4.2<br>5. MR-OPS-PM-ARCHIVE §INC-2024-03 |
| R20 | adversarial_partial_conditions | 1.00 | 0.20 | 1.00 | ok | — | 1. MR-CC-POL-004 §7.4<br>2. MR-CC-POL-004 §1<br>3. MR-OPS-PM-ARCHIVE §INC-2025-12<br>4. MR-CC-POL-004 §7<br>5. MR-CC-POL-004 §4 |

## 7. Dataset health (dry run)

Dry run 2026-09-28T16:58:42+00:00 (as_of 2026-03-16, no model calls): 33 cases; truth drift: none; scorer oracle failures: none; naive answers missed: none.

*oracle* = an answer built from the truth must pass every deterministic check; *naive* = an answer built from the stored naive values must fail.

| case | tier | category | expected | rule checks | judge calls | oracle | naive | drift |
|---|---|---|---|---|---|---|---|---|
| A01 | A | single_hop | V0 | 1 | 0 | ok | — | none |
| A02 | A | single_hop | V0 | 1 | 0 | ok | — | none |
| A03 | A | single_hop | V0 | 1 | 2 | ok | — | none |
| A04 | A | single_hop | V0 | 2 | 0 | ok | caught | none |
| A05 | A | multi_hop | V1 | 1 | 0 | ok | — | none |
| A06 | A | multi_hop | V1 | 1 | 0 | ok | — | none |
| A07 | A | multi_hop | V1 | 1 | 0 | ok | — | none |
| C01 | C | entity_ambiguity | V2 | 0 | 4 | — | — | none |
| C02 | C | entity_ambiguity | V2 | 0 | 3 | — | — | none |
| C03 | C | entity_ambiguity | V2 | 0 | 3 | — | — | none |
| C04 | C | entity_ambiguity | V2 | 0 | 3 | — | — | none |
| C05 | C | entity_ambiguity | V2 | 0 | 2 | — | — | none |
| C06 | C | entity_ambiguity | V2 | 0 | 3 | — | — | none |
| C07 | C | entity_ambiguity | V2 | 0 | 3 | — | — | none |
| A08 | A | vocabulary | V2 | 2 | 0 | ok | — | none |
| A09 | A | vocabulary | V2 | 1 | 0 | ok | — | none |
| C08 | C | vocabulary | V2 | 0 | 4 | — | — | none |
| C09 | C | vocabulary | V2 | 0 | 3 | — | — | none |
| A10 | A | governed_metric | V2 | 2 | 0 | ok | caught | none |
| A11 | A | governed_metric | V2 | 2 | 0 | ok | caught | none |
| A12 | A | governed_metric | V2 | 2 | 0 | ok | caught | none |
| A13 | A | governed_metric | V2 | 2 | 0 | ok | caught | none |
| C10 | C | root_cause | V4 | 0 | 6 | — | — | none |
| C11 | C | root_cause | V4 | 0 | 4 | — | — | none |
| C12 | C | root_cause | V4 | 0 | 4 | — | — | none |
| C13 | C | external_api | V3 | 0 | 3 | — | — | none |
| C14 | C | external_api | V3 | 0 | 3 | — | — | none |
| C15 | C | authority | V4 | 0 | 4 | — | — | none |
| C16 | C | authority | V4 | 0 | 3 | — | — | none |
| C17 | C | authority | V4 | 0 | 4 | — | — | none |
| B01 | B | authority | V5 | 2 | 0 | ok | — | none |
| C18 | C | residual | never | 0 | 3 | — | — | none |
| C19 | C | residual | never | 0 | 2 | — | — | none |
