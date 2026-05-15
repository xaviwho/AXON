"""Regenerate shared/knowledge_base/action_library_reference.md from library.json.

Run with: `python -m shared.action_library.generate_docs`
"""

from __future__ import annotations

from pathlib import Path

from .wrappers import ActionLibrary

KB_PATH = Path(__file__).parent.parent / "knowledge_base" / "action_library_reference.md"


def render() -> str:
    lib = ActionLibrary.load()
    out: list[str] = [
        "# Action Library Reference",
        "",
        "Auto-generated from `shared/action_library/library.json` by "
        "`python -m shared.action_library.generate_docs`. Do not edit by hand.",
        "",
        "Layer D selects and parameterizes from this bounded set. It cannot "
        "synthesize new actions — adding an entry requires design review.",
        "",
    ]
    for name in sorted(lib.names()):
        action = lib[name]
        out.append(f"## `{action.action_id}`")
        out.append("")
        out.append(action.description)
        out.append("")
        out.append(f"- **Latency class:** {action.latency_class.value}")
        out.append(f"- **Permission level:** {action.permission_level.value}")
        audit = ", ".join(action.audit_requirements) or "none"
        out.append(f"- **Audit requirements:** {audit}")
        props = action.parameters_schema.get("properties", {})
        required = set(action.parameters_schema.get("required", []))
        if props:
            out.append("- **Parameters:**")
            for pname, pdef in props.items():
                ptype = pdef.get("type", "any")
                req = "required" if pname in required else "optional"
                out.append(f"  - `{pname}` _{ptype}, {req}_")
        else:
            out.append("- **Parameters:** none")
        out.append("")
    return "\n".join(out)


def main() -> None:
    KB_PATH.write_text(render(), encoding="utf-8")
    print(f"Wrote {KB_PATH}")


if __name__ == "__main__":
    main()
