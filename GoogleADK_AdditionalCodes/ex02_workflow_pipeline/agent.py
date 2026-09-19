"""Pattern 2 — the static workflow.

The control flow is written in Python, not decided by a model. Stage 2 always
runs after stage 1, the three assessments always run, and the draft is always
reviewed. No prompt can talk the pipeline out of a step.

That is the entire value proposition. An LLM asked to "handle this exception"
will sometimes skip the supply check, and you will not know which runs skipped
it. Here, the trace is the same shape every time, so you can measure each stage
independently and fix the one that is weak.

    SequentialAgent
      1. intake_agent .................... raw payload  -> ExceptionCase
      2. ParallelAgent
           policy_assessor  ┐
           supply_assessor  ├─ concurrent, independent, distinct state keys
           customer_assessor┘
      3. resolution_agent ................ 3 assessments -> Resolution
      4. LoopAgent (max 3)
           comms_drafter                  writes draft_reply
           comms_reviewer                 approves (exit_loop) or returns notes
"""

from __future__ import annotations

from google.adk.agents import LoopAgent, ParallelAgent, SequentialAgent

from .stages import (
    comms_drafter,
    comms_reviewer,
    customer_assessor,
    intake_agent,
    policy_assessor,
    resolution_agent,
    supply_assessor,
)

# --- Stage 2 --------------------------------------------------------------
# ParallelAgent runs its children concurrently in separate branches. They share
# the same session state, so each child must write to a distinct output_key or
# they will overwrite one another. They also cannot read each other's output —
# if B needs A's result, B does not belong in this block.
assessment_fan_out = ParallelAgent(
    name="assessment_fan_out",
    description="Runs the policy, supply and customer assessments concurrently.",
    sub_agents=[policy_assessor, supply_assessor, customer_assessor],
)

# --- Stage 4 --------------------------------------------------------------
# LoopAgent re-runs its children until a child calls exit_loop or max_iterations
# is hit. max_iterations is not optional in production: without it, a reviewer
# that is never satisfied will burn tokens until something else kills the job.
#
# Three is deliberate. If a draft is still failing review on the third pass, the
# problem is upstream — usually an incoherent resolution — and looping harder
# will not fix it.
drafting_loop = LoopAgent(
    name="drafting_loop",
    description="Drafts the customer message and revises it until it passes review.",
    sub_agents=[comms_drafter, comms_reviewer],
    max_iterations=3,
)

# --- The pipeline ---------------------------------------------------------
root_agent = SequentialAgent(
    name="exception_resolution_pipeline",
    description=(
        "Deterministic four-stage pipeline that turns a raw Aurora Retail delivery "
        "exception into an audited resolution and an approved customer message."
    ),
    sub_agents=[
        intake_agent,
        assessment_fan_out,
        resolution_agent,
        drafting_loop,
    ],
)
