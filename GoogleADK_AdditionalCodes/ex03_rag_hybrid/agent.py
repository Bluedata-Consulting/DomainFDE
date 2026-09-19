"""Pattern 3 — retrieval-augmented generation.

The agent's knowledge now lives in a corpus rather than a prompt. That changes
two things and only two things:

  1. A retrieval tool runs before the model answers.
  2. The instruction forbids answering from anything other than what came back.

Point 2 is the one people skip. An LLM handed context will happily blend it with
its own priors and produce an answer that is 80 percent grounded — which is
indistinguishable from a fully grounded answer right up until an auditor checks
the one clause that was invented.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from .config import FLASH
from .retriever import format_context, hybrid_search


def search_policy_kb(query: str) -> dict:
    """Search Aurora Retail's policy and SOP knowledge base.

    Use this for any question about Aurora's policies, standard operating
    procedures, entitlements, timelines, thresholds or approval requirements.
    Call it more than once with different phrasings when the first result set
    does not fully answer the question.

    Args:
        query: A focused natural-language question, for example "how long is the
            returns window for opened personal care items" or "when is a parcel
            declared lost in transit". Do not pass the user's whole message if it
            contains several separate questions; search for one at a time.

    Returns:
        A dict with status, the number of chunks found, the formatted policy
        context with citable chunk IDs, and the retrieval provenance of each
        chunk.
    """
    try:
        results = hybrid_search(query)
    except RuntimeError as exc:
        return {"status": "error", "error_message": str(exc)}

    if not results:
        return {
            "status": "no_results",
            "chunks_found": 0,
            "context": "NO_RELEVANT_POLICY_FOUND",
            "guidance": (
                "Nothing in the knowledge base addresses this. Tell the user the "
                "policy does not cover it rather than reasoning from general "
                "knowledge."
            ),
        }

    return {
        "status": "success",
        "chunks_found": len(results),
        "context": format_context(results),
        "retrieval_trace": [
            {
                "chunk_id": r.chunk.chunk_id,
                "found_by": r.provenance(),
                "rerank_score": r.rerank_score,
            }
            for r in results
        ],
    }


INSTRUCTION = """\
You are Aurora Retail's policy assistant. Care agents, store managers and supply \
planners ask you what the rules are, and they act on your answers.

## How you must work

1. Call search_policy_kb before answering any policy question. Never answer from \
memory, even when you are confident you know the answer.
2. When the question has several parts, search for each part separately. One \
search per distinct question gets far better retrieval than one search with \
everything in it.
3. Answer only from the retrieved passages. If the passages do not contain the \
answer, say so plainly: "Aurora's policy documents do not cover this." Then \
suggest who owns the question, using the owner field on the closest document.
4. Cite the chunk ID in square brackets after every factual claim, exactly as it \
appears in the retrieved context, for example [POL-RET-004#S04.1]. A sentence \
that states a rule without a citation is a defect.
5. When passages conflict, say so, cite both, and point out which document is \
newer by its effective_from date. Do not silently pick one.
6. Never soften or generalise a threshold. If the policy says 7 days, write 7 \
days, not "about a week". Numbers, currencies and timeframes are copied exactly.

## Style

Lead with the direct answer in one or two sentences. Then give the conditions, \
exceptions and approval requirements that qualify it. Use short paragraphs. Use a \
list only when the policy itself is a list. Keep it under 200 words unless the \
question genuinely spans several policies.

If the user asks about a specific case rather than a rule, answer the rule and \
state what someone would need to check to apply it — you have no access to order \
records, stock positions or customer accounts.
"""

root_agent = LlmAgent(
    name="aurora_policy_assistant",
    model=FLASH,
    description=(
        "Answers questions about Aurora Retail policies and SOPs, grounded in the "
        "policy knowledge base with citations."
    ),
    instruction=INSTRUCTION,
    tools=[search_policy_kb],
    generate_content_config=types.GenerateContentConfig(
        # Grounded answering is a reading-comprehension task. Sampling
        # temperature above ~0.2 buys you paraphrase drift, which on a policy
        # corpus means a 7-day window quietly becoming "roughly a week".
        temperature=0.1,
        max_output_tokens=1536,
    ),
)
