"""Read-only source classification against the approved graph."""
from pathlib import Path
from kernel import component_graph


def check(graph: dict, root: Path, sources: list[Path]) -> list[str]:
    """`graph` is already validated by `component_graph.load`."""
    errors: list[str] = []
    counts = {component["id"]: 0 for component in graph["components"]}
    states = {component["id"]: component["state"] for component in graph["components"]}
    for path in sources:
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            errors.append(f"{path}: source escapes repository")
            continue
        if component_graph.excluded(graph, relative):
            continue
        found = component_graph.owners(graph, relative)
        if not found:
            errors.append(f"{relative}: unclassified source; needs_decision")
        elif len(found) != 1:
            errors.append(f"{relative}: multiple component-role owners {found}; needs_decision")
        else:
            owner, _ = found[0]
            counts[owner] += 1
            if states[owner] == "retired":
                errors.append(f"{relative}: retired component {owner} still has source")
    for owner, count in counts.items():
        if states[owner] == "implemented" and not count:
            errors.append(f"{owner}: implemented component has no source evidence")
    return errors
