"""Read-only canonical component graph, structural validation and ownership."""
import fnmatch
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

GRAPH_PATH = "docs/architecture/components.json"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/architecture/components.schema.json"


def load(root: Path, path: str = GRAPH_PATH) -> dict:
    """Read the graph; missing or malformed documents are never defaulted."""
    graph = json.loads((root / path).read_text(encoding="utf-8"))
    errors = validate(graph)
    if errors:
        raise ValueError("; ".join(errors))
    return graph


def has_components(root: Path) -> bool:
    """Has the first classification been approved? That ends greenfield. Unreadable or malformed reads as False."""
    try:
        graph = json.loads((root / GRAPH_PATH).read_text(encoding="utf-8"))
        return bool(graph["components"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _schema_errors(value, spec, path):
    errors = []
    kind = spec.get("type")
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": type(value) is int}
    if kind and not valid[kind]:
        return [f"{path}: expected {kind}"]
    if "const" in spec and (value != spec["const"] or type(value) is not int):
        errors.append(f"{path}: unsupported schema")
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: expected one of {spec['enum']}")
    if kind == "string" and len(value.strip()) < spec.get("minLength", 0):
        errors.append(f"{path}: nonempty text required")
    if kind == "integer" and value < spec.get("minimum", value):
        errors.append(f"{path}: invalid minimum")
    if kind == "array":
        if len(value) < spec.get("minItems", 0):
            errors.append(f"{path}: empty list is not allowed")
        if spec.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append(f"{path}: duplicate values")
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, spec["items"], f"{path}[{index}]"))
    if kind == "object":
        if len(value) < spec.get("minProperties", 0):
            errors.append(f"{path}: empty mapping is not allowed")
        for key in spec.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, item in value.items():
            child = spec.get("properties", {}).get(key, spec.get("additionalProperties", True))
            if child is False:
                errors.append(f"{path}.{key}: unknown field")
            elif isinstance(child, dict):
                errors.extend(_schema_errors(item, child, f"{path}.{key}"))
    return errors


def safe_relative(path: str, allow_root: bool = False) -> bool:
    """Only portable repository-contained paths and glob selectors are accepted."""
    return (isinstance(path, str) and bool(path) and "\\" not in path and ":" not in path
            and not path.startswith("/") and ".." not in path.split("/")
            and (allow_root or path != "."))


def validate(graph) -> list[str]:
    """Validate shape, references, portable paths and declared dependency cycles."""
    errors = _schema_errors(graph, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), "graph")
    if errors:
        return errors
    categories = {item["id"]: item for item in graph["categories"]}
    components = {item["id"]: item for item in graph["components"]}
    for label, items in (("categories", graph["categories"]), ("components", graph["components"])):
        ids = [item["id"] for item in items]
        if len(ids) != len(set(ids)):
            errors.append(f"{label}: duplicate id")
        if any(not re.fullmatch(r"[a-z][a-z0-9_-]*", item) for item in ids):
            errors.append(f"{label}: id must be a stable lowercase identifier")
    contracts = {}
    port_ids = set()
    roles = {role for category in categories.values() for role in category["roles"]}
    for component in components.values():
        label = component["id"]
        category = categories.get(component["category"])
        if not category:
            errors.append(f"{label}: unknown category")
        if not safe_relative(component["root"], allow_root=True) or any(c in component["root"] for c in "*?["):
            errors.append(f"{label}: invalid root")
        for role, patterns in component["roles"].items():
            if not category or role not in category["roles"]:
                errors.append(f"{label}: unknown role {role}")
            if any(not safe_relative(pattern) for pattern in patterns):
                errors.append(f"{label}: invalid role selector")
        for contract in component["public"]:
            if contract["id"] in contracts:
                errors.append(f"{label}: duplicate contract {contract['id']}")
            contracts[contract["id"]] = label
            if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", contract["module"]):
                errors.append(f"{label}: invalid public module")
        for port in component.get("ports", []):
            identity = (port["module"], port["symbol"])
            if identity in port_ids:
                errors.append(f"{label}: duplicate declared port {identity}")
            port_ids.add(identity)
            for field, value in port.items():
                pattern = r"[A-Za-z_]\w*" if field.endswith("symbol") else r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*"
                if not re.fullmatch(pattern, value):
                    errors.append(f"{label}: invalid port {field}")
    for role, targets in graph["role_dependencies"].items():
        if role not in roles or any(target not in roles for target in targets):
            errors.append(f"role_dependencies: unknown role {role}")
    if roles - set(graph["role_dependencies"]):
        errors.append("role_dependencies: every role requires an explicit dependency rule")
    for pattern in graph["technology"]["sources"]:
        if not safe_relative(pattern):
            errors.append("technology.sources: invalid selector")
    for excluded in graph["technology"].get("exclude", []):
        if not safe_relative(excluded["path"]) or any(c in excluded["path"] for c in "*?["):
            errors.append("technology.exclude: requires a specific path prefix")
    for edge in graph["edges"]:
        if edge["source"] not in components or edge["target"] not in components:
            errors.append("edges: unknown component")
        elif components[edge["source"]]["state"] == "retired" or components[edge["target"]]["state"] == "retired":
            errors.append("edges: retired component reference")
        if contracts.get(edge["contract"]) != edge["target"]:
            errors.append(f"edges: unknown target contract {edge['contract']}")
    adjacency = {key: set() for key in components}
    for edge in graph["edges"]:
        if edge["source"] in adjacency and edge["target"] in adjacency:
            adjacency[edge["source"]].add(edge["target"])
    allowed = {frozenset(cycle) for cycle in graph.get("allowed_cycles", [])}
    for cycle in graph.get("allowed_cycles", []):
        if any(item not in components for item in cycle):
            errors.append("allowed_cycles: unknown component")
    def visit(node, trail):
        if node in trail:
            cycle = trail[trail.index(node):]
            if frozenset(cycle) not in allowed:
                errors.append("edges: dependency cycle " + " -> ".join(cycle + [node]))
            return
        for target in adjacency[node]:
            visit(target, trail + [node])
    for node in adjacency:
        visit(node, [])
    return sorted(set(errors))


def digest(graph: dict) -> str:
    """Canonicalize graph sets so display ordering cannot invalidate approval."""
    def canonical(value):
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
        return value
    encoded = json.dumps(canonical(graph), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def matches(path: str, pattern: str) -> bool:
    """Segment globs: only ** crosses directories and it may match zero segments."""
    def match(parts, selectors):
        if not selectors:
            return not parts
        if selectors[0] == "**":
            return match(parts, selectors[1:]) or bool(parts and match(parts[1:], selectors))
        return bool(parts and fnmatch.fnmatchcase(parts[0], selectors[0]) and match(parts[1:], selectors[1:]))
    return match(path.split("/"), pattern.split("/"))


def excluded(graph: dict, relative: str) -> bool:
    return any(relative == item["path"].rstrip("/") or relative.startswith(item["path"].rstrip("/") + "/")
               for item in graph["technology"].get("exclude", []))


def owners(graph: dict, relative: str) -> list[tuple[str, str]]:
    """Return unique component-role matches without changing the graph."""
    result = []
    if not safe_relative(relative) or excluded(graph, relative):
        return result
    for component in graph["components"]:
        try:
            local = PurePosixPath(relative).relative_to(component["root"]).as_posix()
        except ValueError:
            continue
        for role, patterns in component["roles"].items():
            if any(matches(local, pattern) for pattern in patterns):
                result.append((component["id"], role))
    return result
