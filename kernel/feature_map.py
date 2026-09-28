"""Generate a projection of the canonical component intent and current source ownership; it never implies approval."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from kernel import component_graph
from kernel.context import candidate_files
from kernel.gates import context_api

JSON_PATH = "docs/architecture/feature-map.json"
MARKDOWN_PATH = "docs/architecture/feature-map.md"


def source_paths(root: Path, graph: dict) -> list[Path]:
    """Include not-yet-added code selected by the project's explicit language binding."""
    root = root.resolve()
    paths = set()
    for path in candidate_files(root=root):
        relative = path.relative_to(root).as_posix()
        if not any(component_graph.matches(relative, pattern) for pattern in graph["technology"]["sources"]):
            continue
        if component_graph.excluded(graph, relative):
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"{relative}: source escapes repository")
        paths.add(path)
    return sorted(paths)


def project(root: Path) -> dict:
    """A generated map records declared intent, not an approval or dependency verdict."""
    root = root.resolve()
    graph = component_graph.load(root)
    nodes = {}
    for component in sorted(graph["components"], key=lambda item: item["id"]):
        node = {key: component[key] for key in ("id", "name", "category", "responsibility", "excludes", "state")}
        node.update(public=sorted(component["public"], key=lambda item: item["id"]),
                    external=sorted(component.get("external", [])), sources=[])
        nodes[component["id"]] = node
    unclassified, ambiguous = [], []
    sources = source_paths(root, graph)
    for path in sources:
        relative = path.relative_to(root).as_posix()
        owners = component_graph.owners(graph, relative)
        if not owners:
            unclassified.append(relative)
        elif len(owners) > 1:
            ambiguous.append({"path": relative, "owners": [list(owner) for owner in sorted(owners)]})
        else:
            owner, role = owners[0]
            nodes[owner]["sources"].append({"path": relative, "role": role,
                                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    violations, unverified, observed = context_api.check(graph, root, sources)
    return {"schema": 1, "graph_digest": component_graph.digest(graph),
            "evidence": "working-tree", "approval": "not-evaluated",
            "components": list(nodes.values()),
            "declared_edges": sorted(graph["edges"], key=lambda item: json.dumps(item, sort_keys=True)),
            "observed_edges": observed, "dependency_violations": violations,
            "unverified_dependencies": unverified,
            "dependency_observation": "unverified" if unverified else "static-analysis",
            "unclassified": unclassified, "ambiguous": ambiguous}


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def markdown(projection: dict) -> str:
    lines = ["# 기능 지도", "",
             "> 담는 것: 정본 그래프와 현재 소스의 자동 투영. 담지 않는 것: 사용자 승인 판정(→ components.json). 읽는 시점: 구조 변경 검토 시.",
             "", "이 문서는 생성 결과이며 직접 편집하지 않는다.",
             "컴포넌트 이름과 관계는 선언된 의도이며 이 지도 자체가 승인을 증명하지 않는다.",
             "소스 근거는 현재 작업 파일의 해시이며 의존 관계의 실제 관측은 별도 게이트에서 검증한다.",
             "", "| 컴포넌트 | 상태 | 책임 | 공개 계약 | 현재 소스 수 |", "|---|---|---|---|---|"]
    for node in projection["components"]:
        contracts = ", ".join(item["id"] for item in node["public"]) or "없음"
        cells = [f"{node['name']} ({node['id']})", node["state"], node["responsibility"], contracts, len(node["sources"])]
        lines.append("| " + " | ".join(_cell(value) for value in cells) + " |")
    lines.extend(["", "## 선언된 연결", "", "| 출발 | 도착 | 계약 | 종류 |", "|---|---|---|---|"])
    for edge in projection["declared_edges"]:
        lines.append("| " + " | ".join(_cell(edge[key]) for key in ("source", "target", "contract", "kind")) + " |")
    lines.extend(["", "## 분류 검토", "", f"미분류 소스: {len(projection['unclassified'])}개.",
                  f"중복 분류 소스: {len(projection['ambiguous'])}개.",
                  "세부 소스와 제외 책임 및 외부 연결은 [생성 데이터](feature-map.json)에 기록한다.", ""])
    return "\n".join(lines)


def artifacts(root: Path) -> dict[str, str]:
    projection = project(root)
    return {JSON_PATH: json.dumps(projection, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            MARKDOWN_PATH: markdown(projection)}


def check(root: Path) -> list[str]:
    """Compare artifacts without creating directories, maps, proposals or receipts."""
    errors = []
    for relative, expected in artifacts(root).items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            errors.append(f"{relative}: stale or missing; run python -m kernel.feature_map --root {root}")
    return errors


def generate(root: Path) -> None:
    for relative, contents in artifacts(root).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="read-only comparison")
    args = parser.parse_args(argv)
    try:
        if args.check:
            errors = check(args.root)
            for error in errors:
                print(error)
            return int(bool(errors))
        generate(args.root)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"[UNVERIFIED] feature map: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
