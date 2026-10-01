"""Read-only runner integration for component ownership, decisions and maps."""

from pathlib import Path

from kernel import component_graph, feature_map, graph_workflow, port_contracts
from kernel.gates import components, context_api


def sections(root: Path, verify: bool = False) -> list[tuple]:
    """Graph rules cannot be exempted by the file baseline (`harness_baseline.txt`)."""
    try:
        graph = component_graph.load(root)
        sources = feature_map.source_paths(root, graph)
    except FileNotFoundError:
        return [("graph_schema", "Component graph", ["first code requires classification; needs_decision"], None)]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [("graph_schema", "Component graph", [str(exc)], None)]
    failures, unresolved, _observed = context_api.check(graph, root, sources)
    classification = components.check(graph, root, sources)
    approval = graph_workflow.check_approval(root, graph)
    result = [
        ("graph_schema", "Component graph format", [], None),
        ("component_classification", "Component classification", classification, None),
        ("graph_approval", "Graph user decisions", approval, None),
        ("component_dependencies", "Public contracts and dependency direction", failures, None),
        ("component_syntax", "Component syntax analysis", [], ("TOOL", "; ".join(unresolved)) if unresolved else None),
        ("graph_projection", "Feature map match", feature_map.check(root) if not (classification or approval or failures) else [],
         ("SKIP", "resolve graph decisions first") if classification or approval or failures else None),
    ]
    if verify:
        failures, unresolved = port_contracts.run(root, graph)
        result += [("port_contracts", "Runtime contracts of declared ports", failures, None),
                   ("port_tools", "Port contract runtime tools", [], ("TOOL", "; ".join(unresolved)) if unresolved else None)]
    return result
