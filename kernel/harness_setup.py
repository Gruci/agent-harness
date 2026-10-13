"""Read-only checks for the shared Claude/Codex installation; no runtime trust claims."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ADAPTERS = ("feature-workflow", "full-feature", "code-audit", "code-debt",
            "code-trim", "md-audit", "review-loop", "test")
WORKFLOW_REF = re.compile(r"dev/workflows/[A-Za-z0-9_-]+\.md")
# (event, Claude wrapper stem, tools that must reach the shared entry point). Codex adds apply_patch
# to the tool-scoped events. PreToolUse carries the isolation guard and the exit gate for both.
REQUIRED_HOOKS = (("PostToolUse", "check_file_rules", ("Edit", "Write", "MultiEdit")),
                  ("Stop", "check_coding_rules", ("",)),
                  ("PreToolUse", "check_pretool", ("Edit", "Write", "Bash")))


def _read(root: Path, rel: str, problems: list[str]) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        problems.append(f"{rel}: missing or unreadable ({exc.__class__.__name__})")
        return ""


def _check_adapters(root: Path, problems: list[str]) -> None:
    for name in ADAPTERS:
        codex = f".agents/skills/{name}-cdx/SKILL.md"
        claude = f".claude/skills/{name}/SKILL.md"
        codex_text = _read(root, codex, problems)
        claude_text = _read(root, claude, problems)
        codex_refs = set(WORKFLOW_REF.findall(codex_text))
        claude_refs = set(WORKFLOW_REF.findall(claude_text))
        if not codex_refs or codex_refs != claude_refs:
            problems.append(f"{codex} / {claude}: shared workflow references missing or disagree")
        for rel in sorted(codex_refs | claude_refs):
            _read(root, rel, problems)


def _matches(matcher: object, tool: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    if not isinstance(matcher, str):
        return False
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return False


def _commands(config: dict, event: str, tool: str) -> list[dict]:
    hooks = config.get("hooks", {})
    groups = hooks.get(event, []) if isinstance(hooks, dict) else []
    if not isinstance(groups, list):
        return []
    found = []
    for group in groups:
        if not isinstance(group, dict) or not _matches(group.get("matcher"), tool):
            continue
        entries = group.get("hooks", [])
        if isinstance(entries, list):
            found.extend(entry for entry in entries if isinstance(entry, dict)
                         and entry.get("type") == "command" and not entry.get("async"))
    return found


def _shared_command(command: object, agent: str, event: str) -> bool:
    if not isinstance(command, str):
        return False
    return (re.search(r"\bpython(?:3(?:\.\d+)?)?\b", command) is not None
            and ("kernel/hook.py" in command or "kernel.hook" in command)
            and f"--agent {agent}" in command and f"--event {event}" in command
            and "git rev-parse --show-toplevel" in command)


def _check_hooks(root: Path, agent: str, problems: list[str]) -> None:
    rel = ".codex/hooks.json" if agent == "codex" else ".claude/settings.json"
    text = _read(root, rel, problems)
    try:
        config = json.loads(text)
    except (ValueError, TypeError):
        problems.append(f"{rel}: expected valid JSON hook configuration")
        return
    if not isinstance(config, dict):
        problems.append(f"{rel}: expected a JSON object")
        return
    if config.get("disableAllHooks"):
        problems.append(f"{rel}: disableAllHooks disables the required checks")
    for event, filename, tools in REQUIRED_HOOKS:
        if agent == "codex" and event != "Stop":
            tools += ("apply_patch",)
        wrapper = f".claude/hooks/{filename}.py"
        if agent == "claude":
            source = _read(root, wrapper, problems)
            if "from kernel.hook import main" not in source:
                problems.append(f"{wrapper}: must delegate to kernel.hook.main")
        for tool in tools:
            candidates = _commands(config, event, tool)
            if agent == "codex":
                wired = any(_shared_command(entry.get("command"), agent, event)
                            and _shared_command(entry.get("commandWindows", entry.get("command_windows")),
                                                agent, event) for entry in candidates)
            else:
                wired = any(wrapper in str(entry.get("command", "")) for entry in candidates)
            if not wired:
                problems.append(f"{rel}: {event} {tool} missing compatible synchronous command hook"
                                + (" (command and commandWindows)" if agent == "codex" else ""))


def hook_scripts(config: dict) -> set[tuple[str, str]]:
    """(event, hook script stem) wired in a Claude hook configuration. Only `.claude/hooks/*.py` commands count."""
    found: set[tuple[str, str]] = set()
    hooks = config.get("hooks", {}) if isinstance(config, dict) else {}
    for event, groups in (hooks.items() if isinstance(hooks, dict) else ()):
        for group in (groups if isinstance(groups, list) else ()):
            for entry in (group.get("hooks", []) if isinstance(group, dict) else ()):
                command = str(entry.get("command", "")) if isinstance(entry, dict) else ""
                found.update((str(event), stem) for stem in re.findall(r"\.claude/hooks/([A-Za-z0-9_]+)\.py", command))
    return found


def wiring_diff(root: Path, upstream: Path) -> list[str]:
    """Hook wiring that differs from upstream's `.claude/settings.json`. Reported, never applied: that file is the project's."""
    configs = []
    for base in (root, upstream):
        try:
            configs.append(hook_scripts(json.loads((base / ".claude/settings.json").read_text(encoding="utf-8-sig"))))
        except (OSError, ValueError, TypeError):
            return [f"[WIRING] {base / '.claude/settings.json'}: unreadable — compare the hook wiring by hand"]
    mine, theirs = configs
    lines = [f"[WIRING] upstream wires .claude/hooks/{stem}.py on {event}; this install does not — "
             f"add it to .claude/settings.json by hand (the upgrade never edits that file)"
             for event, stem in sorted(theirs - mine)]
    lines += [f"[WIRING] this install wires .claude/hooks/{stem}.py on {event}; upstream no longer does — "
              f"keep it only if the script still exists" for event, stem in sorted(mine - theirs)]
    return lines


def legacy_upgrade_notice(root: Path) -> str:
    """The upgrader before kernel.upgrade copied upstream over everything and never replaced itself. Its successor prints the way out."""
    installer = root / "harness_install.py"
    try:
        text = installer.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    if "kernel.upgrade" in text:
        return ""
    return ("[UPGRADE] The old upgrader (a harness_install.py without kernel.upgrade) ran: it overwrote kernel/ · .claude/hooks/ · profiles/*.py "
            "without checking for local changes. Review `git diff` and restore any local fix it reverted, commit, then run "
            "`python -X utf8 -m kernel.upgrade` once — it replaces harness_install.py and judges files by upstream history from now on.")


def check_agents(root: Path) -> int:
    """Report incomplete disk wiring and return nonzero without writing or running hooks."""
    problems: list[str] = []
    for rel in ("AGENTS.md", "CLAUDE.md", "kernel/hook.py", "kernel/runner.py",
                "dev/workflows/README.md", "kernel/component_graph.py", "kernel/graph_workflow.py",
                "kernel/graph_checks.py", "kernel/graph_notifications.py", "kernel/port_contracts.py",
                "docs/architecture/components.schema.json", "dev/COMPONENTS.md",
                "dev/workflows/harness-assembly.md"):
        _read(root, rel, problems)
    assembly = ".agents/skills/harness-assembly-cdx/SKILL.md"
    if "dev/workflows/harness-assembly.md" not in _read(root, assembly, problems):
        problems.append(f"{assembly}: missing reference to shared assembly workflow")
    _check_adapters(root, problems)
    for agent in ("claude", "codex"):
        _check_hooks(root, agent, problems)
    for problem in sorted(set(problems)):
        print(f"[AGENTS] FAIL {problem}")
    if problems:
        print("[AGENTS] Merge the missing shared workflow/adapter/hook entries from the harness template.")
        print("[AGENTS] Preserve project instructions and custom settings; rerun --check-agents after merging.")
    else:
        print("[AGENTS] OK shared files and required hook declarations are present.")
    print("[AGENTS] PENDING runtime: disk checks cannot establish client support, project trust, or hook activation.")
    print("[AGENTS] Confirm both clients load these hooks and block an intentional violation in a temporary checkout.")
    return 1 if problems else 0


if __name__ == "__main__":
    legacy = legacy_upgrade_notice(Path.cwd())
    if legacy:
        print(legacy)
    sys.exit(check_agents(Path.cwd()))
