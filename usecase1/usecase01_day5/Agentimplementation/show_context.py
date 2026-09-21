"""Show how an agent is built, and what it reads. No model is called.

Run from the kit folder, with the ADK environment active:
    python3 show_context.py v5a_loop_agent            an agent: instruction and tools
    python3 show_context.py v5b_loop_graph            a graph: nodes and routes
    python3 show_context.py v5c_router_graph
    python3 show_context.py v5d_orchestrator          an orchestrator: its specialists
    python3 show_context.py v5a_loop_agent get_complaint     (one tool only)
"""
import importlib
import inspect
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT / "agents"))
sys.path.insert(0, str(KIT))


def declaration(tool):
    """The tool as the model sees it: name, description and parameters."""
    try:
        from google.adk.tools.function_tool import FunctionTool
        decl = FunctionTool(tool)._get_declaration()
        schema = getattr(decl, "parameters_json_schema", None)
        if schema is None and decl.parameters is not None:
            schema = decl.parameters.model_dump(exclude_none=True)
        params = {}
        for name, spec in (schema or {}).get("properties", {}).items():
            spec = {k.lower(): v for k, v in spec.items()}
            kind = str(spec.get("type", "")).lower().replace("type.", "")
            enum = spec.get("enum")
            params[name] = f"{kind} (one of: {', '.join(enum)})" if enum else kind
        return decl.name, decl.description or "", params
    except Exception:
        sig = inspect.signature(tool)
        return tool.__name__, inspect.getdoc(tool) or "", {
            n: str(p.annotation).replace("typing.", "") for n, p in sig.parameters.items()}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    agent_name, only = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    agent = importlib.import_module(f"{agent_name}.agent").root_agent

    graph = getattr(agent, "graph", None)
    if graph is not None:
        print(f"\n==== {agent_name}: a GRAPH. The code below decides the order, not the model ====\n")
        for n in graph.nodes:
            inner = getattr(n, "agent", None) or n
            kind = "model" if hasattr(inner, "instruction") else "code"
            print(f"  node  {n.name:<20} {kind}")
        print()
        for e in graph.edges:
            route = f" --{e.route}-->" if e.route is not None else " ------->"
            print(f"  {e.from_node.name:<20}{route:<18} {e.to_node.name}")
        print()
        return

    instruction = agent.instruction if isinstance(agent.instruction, str) else "(read from instruction.txt)"

    if not only:
        print(f"\n==== {agent_name}: INSTRUCTION ({len(instruction.split())} words) ====\n")
        print(instruction.strip())
    print(f"\n==== {agent_name}: TOOLS, as the model reads them ====")
    for tool in agent.tools:
        if hasattr(tool, "agent"):
            sub = tool.agent
            if only and sub.name != only:
                continue
            names = ", ".join(getattr(t, "__name__", str(t)) for t in sub.tools)
            print(f"\n--- {sub.name}  (a specialist agent, used as a tool) ---")
            print(sub.description)
            print(f"    its own tools: {names}")
            continue
        name, description, params = declaration(tool)
        if only and name != only:
            continue
        print(f"\n--- {name} ---")
        print(description.strip())
        for p, kind in params.items():
            print(f"    {p}: {kind}")
    print()


if __name__ == "__main__":
    main()
