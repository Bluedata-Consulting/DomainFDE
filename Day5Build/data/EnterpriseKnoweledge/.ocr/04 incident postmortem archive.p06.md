Root cause
A payment gateway timeout was treated as a failure rather than an unknown, and the job
retried a charge that had in fact succeeded.
Customer impact
118 customers. All duplicates refunded within 72 hours. 34 tickets. No cancellations
attributable.
Action items
| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Idempotency keys on all charge operations | Engineering | Closed Sep 2025 |
| 2 | Timeouts treated as indeterminate, requiring reconciliation before retry | Engineering | Closed Oct 2025 |

INC-2025-12 — Wholesale delivery window misses, Toronto
Severity: 2 Opened: 14 December 2025 Closed: 20 December 2025 Owner: Fulfilment
Operations
Summary
Four consecutive wholesale deliveries to Toronto accounts arrived outside the agreed
morning delivery window during the December peak, disrupting café opening preparation.
Root cause
Peak-season carrier capacity. Our wholesale deliveries were consolidated into a standard
service rather than the committed window service, to manage cost.
Contributing factors
The decision to consolidate was taken in fulfilment without reference to the wholesale
delivery commitments in the account agreements. Nobody checked what we had promised.
Customer impact
Three accounts, including Rosewood Coffee House, which raised it directly with its account
manager and asked whether the committed window was contractual. It is.