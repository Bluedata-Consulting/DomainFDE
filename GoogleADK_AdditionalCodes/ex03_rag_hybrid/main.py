"""Ask the Aurora policy assistant.

    python ex03_rag_hybrid/main.py                    # run the sample questions
    python ex03_rag_hybrid/main.py --chat             # interactive
    python ex03_rag_hybrid/main.py --ask "..."        # one question
    python ex03_rag_hybrid/main.py --retrieval-only "..."   # no LLM answer

Run ingest.py first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Run as a script, import as a package: the repo root goes on sys.path so
# that `python exNN_x/main.py` and `adk web .` resolve imports identically.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ex03_rag_hybrid.agent import root_agent  # noqa: E402
from ex03_rag_hybrid.config import APP_NAME, USER_ID, verify_credentials  # noqa: E402
from ex03_rag_hybrid.retriever import hybrid_search  # noqa: E402
from ex03_rag_hybrid.runner import run_agent  # noqa: E402

SAMPLE_QUESTIONS = [
    "A customer opened a face wash and says it smells off. Can they return it?",
    "When is a parcel officially declared lost, and what does the customer get?",
    "What does POL-GDW-001 say about goodwill ceilings?",
    "Can we use quarantined stock to fulfil a replacement we already promised?",
    "Three delivery attempts failed because nobody was home. Do we owe goodwill?",
    "What is our policy on cryptocurrency payments?",
]

RULE = "=" * 78


def show_retrieval(query: str) -> None:
    """Retrieval without generation — the first thing to check when an answer is wrong."""
    print(f"\nQUERY: {query}\n{'-' * 78}")
    results = hybrid_search(query)
    if not results:
        print("  no chunks survived retrieval")
        return
    for i, r in enumerate(results, start=1):
        score = f"{r.rerank_score:.0f}" if r.rerank_score is not None else "n/a"
        print(f"  {i}. {r.chunk.chunk_id:<22} rerank={score}  "
              f"rrf={r.rrf_score:.4f}  via {r.provenance()}")
        print(f"     {r.chunk.doc_title} > {r.chunk.section}")
        print(f"     {r.chunk.body[:110].strip()}...")


async def ask(question: str) -> str:
    answer, _ = await run_agent(
        agent=root_agent,
        prompt=question,
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    return answer


async def chat() -> None:
    print("Aurora policy assistant. Type 'exit' to quit, '/r <query>' to see retrieval.\n")
    while True:
        try:
            line = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            return
        if line.startswith("/r "):
            show_retrieval(line[3:])
            continue
        print(f"\n{await ask(line)}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Aurora policy RAG assistant")
    parser.add_argument("--chat", action="store_true", help="Interactive mode")
    parser.add_argument("--ask", help="Ask one question and exit")
    parser.add_argument("--retrieval-only", help="Show retrieved chunks, skip the LLM")
    args = parser.parse_args()

    verify_credentials()

    if args.retrieval_only:
        show_retrieval(args.retrieval_only)
        return
    if args.chat:
        await chat()
        return
    if args.ask:
        print(await ask(args.ask))
        return

    for question in SAMPLE_QUESTIONS:
        print(f"\n{RULE}\nQ: {question}\n{RULE}")
        print(await ask(question))

    print(f"\n{RULE}")
    print("The last question is the important one: nothing in the corpus covers")
    print("cryptocurrency payments, so the assistant should decline rather than")
    print("improvise. An assistant that answers it is not grounded, it is guessing.")
    print("\nNext: python ex03_rag_hybrid/evaluate.py")


if __name__ == "__main__":
    asyncio.run(main())
