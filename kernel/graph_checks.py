"""Read-only runner integration for component ownership, decisions and maps."""

from pathlib import Path

from kernel import component_graph, feature_map, graph_workflow, port_contracts, profile
from kernel.gates import components, context_api

# Before any product source or implemented component exists there is nothing to classify or trace.
NO_SOURCE = ("SKIP", "no product source matches technology.sources yet")
BIND = "run `python -X utf8 -m kernel.graph_workflow bind`"


def binding_errors(graph: dict) -> list[str]:
    """The graph must read the profile's language. Before LANG is chosen there is nothing to compare."""
    if profile.LANG is None:
        return []
    technology = graph["technology"]
    errors = []
    if technology["syntax"] != profile.SYNTAX:
        errors.append(f"technology.syntax is {technology['syntax']!r} but the profile language is "
                      f"{profile.SYNTAX!r} — {BIND}; needs_decision")
    for pattern in profile.SOURCE_EXT:
        probes = (pattern.replace("*", "probe"), "pkg/" + pattern.replace("*", "probe"))
        if not all(any(component_graph.matches(probe, source) for source in technology["sources"])
                   for probe in probes):
            errors.append(f"technology.sources do not cover {pattern} — {BIND}; needs_decision")
    return errors


def sections(root: Path, verify: bool = False) -> list[tuple]:
    """Graph rules cannot be exempted by the file baseline (`harness_baseline.txt`)."""
    try:
        graph = component_graph.load(root)
        sources = feature_map.source_paths(root, graph)
    except FileNotFoundError:
        return [("graph_schema", "Component graph", ["first code requires classification; needs_decision"], None)]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [("graph_schema", "Component graph", [str(exc)], None)]
    idle = not sources and not any(item["state"] == "implemented" for item in graph["components"])
    failures, unresolved, _observed = context_api.check(graph, root, sources) if not idle else ([], [], [])
    classification = components.check(graph, root, sources) if not idle else []
    approval = graph_workflow.check_approval(root, graph)
    result = [
        ("graph_schema", "Component graph format", binding_errors(graph), None),
        ("component_classification", "Component classification", classification, NO_SOURCE if idle else None),
        ("graph_approval", "Graph user decisions", approval, None),
        ("component_dependencies", "Public contracts and dependency direction", failures, NO_SOURCE if idle else None),
        ("component_syntax", "Component syntax analysis", [],
         NO_SOURCE if idle else ("TOOL", "; ".join(unresolved)) if unresolved else None),
        ("graph_projection", "Feature map match", feature_map.check(root) if not (classification or approval or failures) else [],
         ("SKIP", "resolve graph decisions first") if classification or approval or failures else None),
    ]
    if verify:
        failures, unresolved = port_contracts.run(root, graph)
        result += [("port_contracts", "Runtime contracts of declared ports", failures, None),
                   ("port_tools", "Port contract runtime tools", [], ("TOOL", "; ".join(unresolved)) if unresolved else None)]
    return result
