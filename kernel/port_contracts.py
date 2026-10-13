"""Static port registration and explicit, isolated unittest contract execution."""
import ast
import json
import subprocess
import sys
from pathlib import Path
from kernel import component_graph


def _path(root, module):
    path = root.joinpath(*module.split(".")).with_suffix(".py")
    if not path.is_file():
        path = root.joinpath(*module.split("."), "__init__.py")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{module}: module escapes repository")
    return path


def _aliases(tree):
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = (node.module or "") + "." + alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def _name(node, aliases):
    if isinstance(node, ast.Subscript):
        return _name(node.value, aliases)
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _name(node.value, aliases) + "." + node.attr
    return ""


def _declarations(tree):
    aliases = _aliases(tree)
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
            and any(_name(base, aliases) in {"typing.Protocol", "typing_extensions.Protocol"} for base in node.bases)}


def _read(root, module, parsed):
    if module not in parsed:
        parsed[module] = ast.parse(_path(root, module).read_text(encoding="utf-8-sig"))
    return parsed[module]


def _signature(method):
    args = method.args
    return (type(method).__name__, tuple(arg.arg for arg in args.posonlyargs),
            tuple(arg.arg for arg in args.args), tuple(arg.arg for arg in args.kwonlyargs),
            bool(args.vararg), bool(args.kwarg), len(args.defaults),
            tuple(item is None for item in args.kw_defaults))


def _verify_registration(root, port, parsed):
    failures, unverified = [], []
    try:
        declaration = _declarations(_read(root, port["module"], parsed)).get(port["symbol"])
        if declaration is None:
            return [f"{port['module']}.{port['symbol']}: registered port is not a declared Protocol"], []
        fake_tree = _read(root, port["fake_module"], parsed)
        fake = next((node for node in fake_tree.body if isinstance(node, ast.ClassDef) and node.name == port["fake_symbol"]), None)
        if fake is None:
            return [f"{port['fake_module']}: fake class {port['fake_symbol']} is missing"], []
        methods = {node.name: node for node in declaration.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        implementations = {node.name: node for node in fake.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if not methods:
            unverified.append(f"{port['symbol']}: data-only or inherited protocol needs a supported contract analyzer")
        for name, method in methods.items():
            implementation = implementations.get(name)
            if implementation is None or _signature(method) != _signature(implementation):
                failures.append(f"{port['fake_symbol']}.{name}: fake does not implement the declared method signature")
        test_tree = _read(root, port["test_module"], parsed)
        aliases = _aliases(test_tree)
        references = {_name(node, aliases) for node in ast.walk(test_tree) if isinstance(node, (ast.Name, ast.Attribute))}
        for module, symbol in ((port["module"], port["symbol"]), (port["fake_module"], port["fake_symbol"])):
            reference = symbol if module == port["test_module"] else module + "." + symbol
            if reference not in references:
                failures.append(f"{port['test_module']}: contract tests do not use {reference}")
    except (OSError, UnicodeError, SyntaxError, ValueError) as error:
        unverified.append(f"{port['symbol']}: contract source unavailable: {error}")
    return failures, unverified


def check(root: Path, graph: dict, parsed: dict | None = None) -> tuple[list[str], list[str]]:
    """Read-only static check; never execute user code on save. `graph` is already validated by `component_graph.load`."""
    failures, unverified = [], []
    if graph["technology"]["syntax"] != "python":
        # Ports are only inspected by the Python analyzer; a graph that declares none has nothing to inspect.
        declared = [port for component in graph["components"] for port in component.get("ports", [])]
        return [], (["port contracts: declared ports need the Python analyzer"] if declared else [])
    trees = dict(parsed or {})
    registrations = {}
    for component in graph["components"]:
        for port in component.get("ports", []):
            registrations[(port["module"], port["symbol"])] = port
            if component["state"] == "planned":
                continue
            try:
                relative = _path(root, port["module"]).relative_to(root).as_posix()
                owners = component_graph.owners(graph, relative)
                if len(owners) != 1 or owners[0][0] != component["id"]:
                    failures.append(f"{port['module']}: registered port must belong to {component['id']}")
            except ValueError as error:
                failures.append(str(error))
            bad, unknown = _verify_registration(root, port, trees)
            failures.extend(bad)
            unverified.extend(unknown)
    if parsed is None:
        for path in root.rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            if component_graph.excluded(graph, relative) or not component_graph.owners(graph, relative):
                continue
            module = relative[:-3].replace("/", ".").removesuffix(".__init__")
            try:
                _read(root, module, trees)
            except (OSError, UnicodeError, SyntaxError, ValueError) as error:
                unverified.append(f"{relative}: protocol scan unavailable: {error}")
    for module, tree in trees.items():
        for symbol in _declarations(tree):
            if (module, symbol) not in registrations:
                failures.append(f"{module}.{symbol}: declared Protocol has no registered fake and contract test")
    return sorted(set(failures)), sorted(set(unverified))


_EXECUTE = '''
import importlib, json, sys, unittest
specs = json.loads(sys.argv[1])
expected, seen = {}, set()
for spec in specs:
    protocol = getattr(importlib.import_module(spec['module']), spec['symbol'])
    fake = getattr(importlib.import_module(spec['fake_module']), spec['fake_symbol'])
    for name, method in protocol.__dict__.items():
        if callable(method) and hasattr(method, '__code__') and name not in {'__init__', '__subclasshook__'}:
            actual = getattr(fake, name, None)
            if hasattr(actual, '__code__'):
                expected[actual.__code__] = spec['fake_module'] + '.' + spec['fake_symbol'] + '.' + name
def trace(frame, event, arg):
    if event == 'call' and frame.f_code in expected:
        seen.add(expected[frame.f_code])
suite = unittest.TestSuite()
for module in sorted({spec['test_module'] for spec in specs}):
    selected = unittest.defaultTestLoader.loadTestsFromName(module)
    if selected.countTestCases() == 0:
        raise ValueError(module + ': zero contract tests')
    suite.addTests(selected)
sys.setprofile(trace)
try:
    result = unittest.TextTestRunner(verbosity=1).run(suite)
finally:
    sys.setprofile(None)
missing = sorted(set(expected.values()) - seen)
print('HARNESS_PORT_RESULT=' + json.dumps({'tests': result.testsRun, 'success': result.wasSuccessful(), 'missing': missing}))
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 and not missing else 1)
'''


def _graph_snapshot(root):
    directory = root / "docs/architecture"
    paths = [directory / "components.json", *directory.glob("proposals/*.json")]
    return {path.as_posix(): path.read_bytes() for path in paths if path.is_file()}


def run(root: Path, graph: dict) -> tuple[list[str], list[str]]:
    """Explicit completion check: real unittest execution and fake method coverage."""
    failures, unverified = check(root, graph)
    if failures or unverified:
        return failures, unverified
    specs = [port for component in graph["components"] if component["state"] == "implemented"
             for port in component.get("ports", [])]
    if not specs:
        return [], []
    before = _graph_snapshot(root)
    try:
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", _EXECUTE, json.dumps(specs)],
                                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
        records = [line for line in result.stdout.splitlines() if line.startswith("HARNESS_PORT_RESULT=")]
        record = json.loads(records[-1].split("=", 1)[1]) if records else {}
        if result.returncode != 0 or not record.get("success") or not record.get("tests") or record.get("missing"):
            failures.append(f"port contract tests failed or did not exercise all fake methods: {record}; {result.stderr[-3000:]}")
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError) as error:
        unverified.append(f"port contract tests could not complete: {error}")
    if before != _graph_snapshot(root):
        failures.append("port contract tests modified the canonical graph or proposal records")
    return failures, unverified
