"""Component boundaries over syntax facts; Python-only semantics ride in `extra`, dynamic access stays unverified.

The graph names its syntax. The analyzer for that syntax comes from `kernel/facts.py` — Python is always
there (stdlib `ast`), any other language needs the profile's language pack plus tree-sitter. Without an
analyzer the whole check is unverified, never a pass.
"""
from pathlib import Path
from kernel import component_graph, facts, port_contracts

DYNAMIC_ACCESS = {"__import__", "importlib.import_module", "exec", "eval", "getattr"}
DOMAIN_SIDE_EFFECTS = {"open", "input", "print", "datetime.datetime.now", "datetime.datetime.utcnow",
                       "time.time", "time.sleep"}


def check(graph: dict, root: Path, sources: list[Path]) -> tuple[list[str], list[str], list[dict]]:
    """Return violations, unresolved analysis, and observed (never allowed) edges.

    `graph` is already validated by `component_graph.load`; this gate does not re-validate it.
    """
    syntax = graph["technology"]["syntax"]
    analyzer, reason = facts.select(syntax)
    if analyzer is None:
        return [], [f"{syntax}: {reason}"], []
    violations, unverified, observed = [], [], []
    components = {item["id"]: item for item in graph["components"]}
    modules, parsed = {}, {}
    for path in sources:
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            violations.append(f"{path}: source escapes repository")
            continue
        if component_graph.excluded(graph, relative):
            continue
        found = component_graph.owners(graph, relative)
        if len(found) != 1:
            unverified.append(f"{relative}: dependency owner unresolved")
            continue
        if path.suffix not in analyzer.suffixes:
            unverified.append(f"{relative}: {analyzer.label} analyzer cannot inspect this source")
            continue
        file_facts = facts.facts_for(path, relative, analyzer)
        modules[file_facts.module] = (found[0], relative)
        if file_facts.error:
            unverified.append(f"{relative}: cannot parse source: {file_facts.error}")
        else:
            parsed[file_facts.module] = file_facts
    contracts = {item["module"]: (component["id"], item) for component in components.values() for item in component["public"]}
    for module, (owner, contract) in contracts.items():
        if components[owner]["state"] != "implemented":
            continue
        if module not in parsed:
            unverified.append(f"{owner}: public module {module} has no parsed source evidence")
            continue
        if modules[module][0][0] != owner:
            violations.append(f"{owner}: public module {module} belongs to another component")
        for symbol in contract["symbols"]:
            if symbol not in parsed[module].top_symbols:
                violations.append(f"{owner}: public symbol {module}.{symbol} has no declaration")
    for module, file_facts in parsed.items():
        (owner, role), relative = modules[module]
        for item in file_facts.imports:
            target = item.module
            imported = target + "." + item.symbol if target and item.symbol and target + "." + item.symbol in modules else target
            name = None if imported != target else item.symbol
            _boundary(graph, components, modules, contracts, owner, role, imported, name, item.external,
                      f"{relative}:{item.line}", violations, unverified, observed)
        # Python 전용 절 — 속성 경유 참조와 호출 이름은 Python 분석기만 낸다. 없는 언어는 건너뛴다.
        for qualified, line in file_facts.extra.get("attributes", ()):
            matches = [key for key in modules if qualified.startswith(key + ".")]
            if matches:
                imported = max(matches, key=len)
                symbol = qualified[len(imported) + 1:].split(".")[0]
                _boundary(graph, components, modules, contracts, owner, role, imported, symbol, None,
                          f"{relative}:{line}", violations, unverified, observed)
        for call, line in file_facts.extra.get("calls", ()):
            if call in DYNAMIC_ACCESS:
                unverified.append(f"{relative}:{line}: dynamic access {call} needs contract evidence")
            if role == "domain" and call in DOMAIN_SIDE_EFFECTS:
                violations.append(f"{relative}:{line}: domain side effect {call}")
    trees = {module: item.extra["tree"] for module, item in parsed.items() if "tree" in item.extra}
    port_failures, port_unknown = port_contracts.check(root, graph, trees)
    violations.extend(port_failures)
    unverified.extend(port_unknown)
    return sorted(set(violations)), sorted(set(unverified)), sorted(observed, key=lambda item: tuple(item.values()))


def _boundary(graph, components, modules, contracts, owner, role, target, symbol, external, location,
              violations, unverified, observed):
    match = modules.get(target)
    if not match:
        local_roots = {module.split(".")[0] for module in modules}
        if target is not None and target.split(".")[0] in local_roots:
            unverified.append(f"{location}: unresolved local import {target}")
        elif (external or target.split(".")[0]) not in components[owner]["external"]:
            violations.append(f"{location}: external dependency {external or target} is not allowed for {owner}")
        return
    (target_owner, target_role), _ = match
    if target_role not in graph["role_dependencies"].get(role, []):
        violations.append(f"{location}: forbidden role dependency {role} -> {target_role}")
    if owner == target_owner:
        return
    declaration = contracts.get(target)
    if not declaration or declaration[0] != target_owner:
        violations.append(f"{location}: private module bypass {target}")
        return
    contract = declaration[1]
    if symbol == "*" or (symbol and symbol not in contract["symbols"]):
        violations.append(f"{location}: private symbol bypass {target}.{symbol}")
    edge = {"source": owner, "target": target_owner, "contract": contract["id"], "kind": "import"}
    if edge not in observed:
        observed.append(edge)
    if edge not in graph["edges"]:
        violations.append(f"{location}: undeclared dependency {owner} -> {target_owner} ({contract['id']}); needs_decision")
