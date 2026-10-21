"""Read-only runner integration for component ownership, decisions and maps."""

import fnmatch
from pathlib import Path, PurePosixPath

from kernel import component_graph, feature_map, graph_workflow, lang, port_contracts, profile
from kernel.context import candidate_files, is_harness_own
from kernel.gates import components, context_api

UNBOUND_SHOWN = 5

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


def _known_source_patterns() -> set[str]:
    """Every shipped or project language pack's source patterns plus the profile's UI patterns."""
    patterns = set(profile.UI_EXT)
    for name in lang.available():
        try:
            patterns |= set(lang.load(name)["EXT"])
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            continue
    return patterns


def unbound_report(root: Path) -> list[str]:
    """Files that look like source to some language pack but no technology.sources pattern binds.

    A report, never a block: that such a file is product code is an inference, and inferences do not block
    (dev/HARNESS.md 「단계」). Excluded graph paths, harness files and SCOPE exclusions are left out.
    """
    try:
        graph = component_graph.load(root)
    except (OSError, ValueError, KeyError, TypeError):
        return []
    patterns = _known_source_patterns()
    skipped = tuple(profile.SCOPE.get("exclude_all") or ())
    root = root.resolve()
    unbound = []
    for path in candidate_files(root=root):
        rel = path.relative_to(root).as_posix()
        name = PurePosixPath(rel).name
        if (not any(fnmatch.fnmatch(name, pattern) for pattern in patterns) or is_harness_own(rel)
                or rel.startswith(skipped) or component_graph.excluded(graph, rel)
                or any(component_graph.matches(rel, source) for source in graph["technology"]["sources"])):
            continue
        unbound.append(rel)
    if not unbound:
        return []
    shown = ", ".join(unbound[:UNBOUND_SHOWN]) + (f" and {len(unbound) - UNBOUND_SHOWN} more"
                                                  if len(unbound) > UNBOUND_SHOWN else "")
    return [f"{len(unbound)} files look like source but no technology.sources pattern binds them ({shown}) — "
            f"no gate checks them. Bind the language ({BIND}) or exclude the path in the graph."]


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
