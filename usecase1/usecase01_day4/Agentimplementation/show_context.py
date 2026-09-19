"""Show what an agent actually reads: its instruction and its tools, exactly as ADK
sends them to the model. No model is called.

Run from the kit folder, with the ADK environment active:
    python3 show_context.py complaints_v3_measured
    python3 show_context.py complaints_v4_context
    python3 show_context.py complaints_v4_context issue_refund     (one tool only)
"""
import importlib
import inspect
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT / "agents"))


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
    instruction = agent.instruction if isinstance(agent.instruction, str) else "(read from instruction.txt)"

    if not only:
        print(f"\n==== {agent_name}: INSTRUCTION ({len(instruction.split())} words) ====\n")
        print(instruction.strip())
    print(f"\n==== {agent_name}: TOOLS, as the model reads them ====")
    for tool in agent.tools:
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
