---
doc_id: SOP-INV-007
title: Inventory Allocation and Replenishment SOP
owner: Supply Planning
effective_from: 2025-10-01
version: 2.4
jurisdiction: India, Malaysia
---

# Inventory Allocation and Replenishment SOP

## 1. Allocation priority

When available stock cannot satisfy all demand for a SKU, it is allocated in this order:

1. Replacements for service failures already promised to a customer.
2. Orders already paid and awaiting dispatch, oldest first.
3. Store replenishment against safety stock breaches.
4. New web channel demand.
5. Promotional and marketing allocations.

Promotional allocation is never taken ahead of a promised replacement. Where a promotion
would breach safety stock on a SKU, the promotion is capped, not the replacement.

## 2. Safety stock

Safety stock is held at 14 days of forward cover for A-class SKUs, 21 days for B-class,
and 30 days for C-class, measured against trailing 8-week average daily sales. Seasonal
SKUs are excluded from this rule and managed to the seasonal plan.

## 3. Reorder triggers

A reorder is raised when projected on-hand falls below safety stock within the supplier
lead time plus a 3-day buffer. Reorder quantity is the greater of the economic order
quantity and the quantity needed to restore 45 days of forward cover.

Where a SKU has fewer than 8 weeks of sales history, reorder is driven by the launch
plan rather than by velocity, and requires planner review before release.

## 4. Store-to-customer dispatch

Where distribution centre stock is exhausted but a store holds the item, the order may be
dispatched from the store. Store dispatch adds one working day and is available in metro
locations only. Store dispatch may not reduce a store below 3 units of display stock on a
SKU that is on planogram.

## 5. Substitution

Substitution requires explicit customer consent and is offered only where the substitute
is the same product in a different size, or the same formulation under a different pack.
A substitute is never dispatched without consent, and never at a price higher than the
original line.

## 6. Discontinued and seasonal lines

Seasonal lines are not replenished after the seasonal window closes. Where a service
failure affects a seasonal or discontinued line, the resolution is a refund, since no
replacement stock exists. Planners must mark such SKUs as no-replenishment in the
master so that service teams see the constraint at the point of decision.

## 7. Supplier lead times

Contracted lead times are 9 days for domestic personal care suppliers, 21 days for
imported fragrance components, and 35 days for ceramics and glassware. Lead time
breaches beyond 5 days trigger a supplier service review.
