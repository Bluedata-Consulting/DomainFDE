# Google ADK Reference Implementations — Retail / CPG / Supply Chain

Five progressively more autonomous patterns, all built on **Google ADK 2.x + Gemini**,
all running against one fictional company so the domain never gets in the way of the
architecture.

| # | Folder | Pattern | Autonomy | Control flow decided by |
|---|--------|---------|----------|--------------------------|
| 1 | `ex01_prompt_assistant` | Prompt-based GenAI assistant | None | You (single call) |
| 2 | `ex02_workflow_pipeline` | Static workflow (Sequential + Parallel + Loop) | None | Your code |
| 3 | `ex03_rag_hybrid` | Hybrid RAG (dense + BM25 + RRF + rerank) | Low | Your code, grounded by retrieval |
| 4 | `ex04_single_agent_tools` | Single agent with tools | Medium | The model (which tool, when) |
| 5 | `ex05_multi_agent_supervisor` | Supervisor + 3 specialist sub-agents | High | The model (which specialist, when) |

**Read them in order.** Each one is the previous one plus exactly one new capability,
and each README states *when you should stop at that level* — which matters more than
the code, because the most common failure in enterprise GenAI is reaching for pattern 5
when pattern 2 was the correct answer.

---

## The running domain: Aurora Retail

Aurora Retail is an omnichannel home & personal-care retailer — 240 stores across India
and Malaysia, a DTC web channel, and ~4,000 SKUs sourced from CPG suppliers. Every
example uses the same SKUs, stores, orders and policies, held in each example's `data/`
folder as JSON or Markdown standing in for OMS / WMS / ERP systems.

---

## Setup (once, for all five)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then put your key in .env
```

Get an API key from [Google AI Studio](https://aistudio.google.com/apikey) and set
`GOOGLE_API_KEY` in `.env`.

To run against **Vertex AI** instead (the usual enterprise path — VPC-SC, IAM, data
residency, no consumer API key), set these in `.env` and leave `GOOGLE_API_KEY` empty:

```
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=asia-south1
```

then `gcloud auth application-default login`. No application code changes — that switch
is the whole point of going through the `google-genai` client.

## Running

Every example has a `main.py` that runs end to end with no arguments:

```bash
python ex01_prompt_assistant/main.py
python ex02_workflow_pipeline/main.py
python ex03_rag_hybrid/ingest.py      # build the vector + BM25 index first
python ex03_rag_hybrid/main.py
python ex04_single_agent_tools/main.py
python ex05_multi_agent_supervisor/main.py
```

You can also open any of them in ADK's dev UI, which gives you a chat window plus an
event/trace inspector — the fastest way to see *why* an agent did what it did:

```bash
adk web .            # from this directory, then pick an example from the dropdown
```

This is why every folder is named `exNN_...` and not `01_...`: ADK imports each agent
folder as a Python module, and `01_prompt_assistant` is not a legal module name.

## Repository conventions

- **Each folder is self-contained.** `config.py` and `runner.py` are duplicated across
  the five examples on purpose, so you can copy a single folder into a client project
  without dragging a shared package behind it. In a real product you would factor these
  into one internal library.
- **`agent.py` exposes `root_agent`.** ADK's dev UI and `adk run` both look for that
  exact name, so the convention is worth keeping even in scripts.
- **Sample data is local JSON/Markdown.** Swap the functions in `mock_backend.py` /
  `tools.py` for real API calls and nothing else in the agent has to change.
- **Models are pinned in `config.py`**, never inline, so a model upgrade is a one-line
  diff per example.

## Model choices

| Job | Model | Why |
|-----|-------|-----|
| Routing, extraction, tool calling, drafting | `gemini-2.5-flash` | Cheap and fast; the right default for almost every node |
| Final synthesis, judgement calls, reranking | `gemini-2.5-pro` | Used only where reasoning quality actually moves the outcome |
| Embeddings | `gemini-embedding-001` | 768-dim output, task-type aware (query vs document) |

Mixing models per node is deliberate. A five-node pipeline that runs Pro everywhere
costs roughly an order of magnitude more than one that runs Flash everywhere except the
one node that needs Pro.

## What to look at in each folder

- `ex01` — prompt structure, structured output with Pydantic, generation config
- `ex02` — `SequentialAgent` / `ParallelAgent` / `LoopAgent`, state passing via `output_key`
- `ex03` — chunking, dual indexing, Reciprocal Rank Fusion, LLM reranking, grounded answering, retrieval eval
- `ex04` — tool design, docstrings as schemas, `ToolContext` state, `before_tool_callback` guardrails
- `ex05` — supervisor pattern, `AgentTool` vs `sub_agents` transfer, specialist scoping

## Known gotchas this code already works around

1. **Braces in instructions.** ADK substitutes `{variable}` in instructions from session
   state and raises `KeyError` if the key is missing. Literal JSON in a prompt is safe
   only because `{"key": "value"}` isn't a valid state name — but a bare `{status}` in
   your prompt text will blow up at runtime. Use `{var?}` for optional injection.
2. **Tool functions must not have default argument values.** The automatic function
   declaration builder does not express them; make every parameter required and handle
   "not supplied" inside the function.
3. **`create_session` is a coroutine** in ADK 2.x. Await it.
4. **`Runner.run_async` is keyword-only** (`user_id=`, `session_id=`, `new_message=`).
5. **Sibling modules collide in `sys.modules`.** `adk web` imports every agent
   folder as a package. Five folders each containing a top-level `config.py` and
   `tools.py` means whichever loads first wins and the rest silently get the wrong
   module. Every folder here is a proper package using relative imports
   (`from .config import FLASH`), and the entry scripts put the *repo root* on
   `sys.path` and import through the package namespace — so
   `python ex04_single_agent_tools/main.py` and `adk web .` resolve identically.
   This is also why example 2's stage definitions live in `stages.py` rather than
   `sub_agents.py`, which would have clashed with example 5's `sub_agents/` package.
6. **Sub-agent instructions need explicit scope limits**, or the model transfers control
   on topics the specialist has no tools for. See `ex05/sub_agents/`.

Built against `google-adk==2.9.2`, `google-genai==2.24.x`, `chromadb==1.5.x`.
