"""Install global Codex autonomy preferences while preserving unrelated TOML and instructions."""

from __future__ import annotations

import os
import re
from pathlib import Path

START = "<!-- harness-autonomy:start -->"
END = "<!-- harness-autonomy:end -->"
INSTRUCTIONS = f"""{START}
## Approved working style

In feature work, ask the user only to resolve material requirements that remain ambiguous or to approve a concrete implementation plan. A skill's own question step and facts only the user knows (such as the repository URL) are the other questions.
Read the available context first, make routine implementation decisions yourself, and prepare a reviewable plan before requesting its approval.
A concrete approval already given in the conversation remains valid; do not request it again for the same scope.
Within the approved scope, continue autonomously through implementation, tests, fixes, and a concise completion report.
Do not ask whether to continue, run a routine tool, or perform an already authorized step.
New scope still needs an appropriate plan; do not infer authorization for unrelated actions.
Host-managed requirements and higher-priority instructions remain authoritative and cannot be changed by this preference.
{END}
"""


def codex_home() -> Path:
    """Use the active runtime home when provided, otherwise the standard user home."""
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def parse_toml(text: str) -> dict:
    """Parse without including potentially secret configuration contents in errors."""
    try:
        import tomllib as parser
    except ImportError:
        try:
            import toml as parser
        except ImportError as exc:
            raise ValueError("TOML parser unavailable; use Python 3.11+ or an existing toml installation") from exc
    try:
        # The Python 3.10 fallback can silently drop CRLF multiline values unless normalized.
        return parser.loads(text.replace("\r\n", "\n"))
    except Exception as exc:
        raise ValueError("Invalid or unsupported TOML; no configuration was changed") from exc


def update_config(text: str) -> str:
    """Edit top-level permission preferences, then verify every unrelated parsed value."""
    original = parse_toml(text)
    modern = "default_permissions" in original
    wanted = {"approval_policy": "never"}
    wanted["default_permissions" if modern else "sandbox_mode"] = ":danger-full-access" if modern else "danger-full-access"
    removed = {"sandbox_mode", "sandbox_workspace_write"} if modern else set()
    expected = {key: value for key, value in original.items() if key not in removed}
    expected.update(wanted)
    if original == expected:
        return text
    keys = set(wanted) | removed
    output = []
    in_table = False
    discard_table = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("["):
            in_table = True
            discard_table = bool(modern and re.match(r"\[\s*['\"]?sandbox_workspace_write(?:['\"]?\s*\]|\.)", stripped))
        if discard_table:
            continue
        assignment = re.match(r'''\s*(?:"([^"\n]+)"|'([^'\n]+)'|([A-Za-z0-9_-]+))\s*=''', line)
        if not in_table and assignment and next(value for value in assignment.groups() if value is not None) in keys:
            continue
        output.append(line)
    newline = "\r\n" if "\r\n" in text else "\n"
    updated = "".join(f'{key} = "{value}"{newline}' for key, value in wanted.items()) + "".join(output)
    if parse_toml(updated) != expected:
        raise ValueError("Cannot safely update this TOML layout while preserving unrelated settings")
    return updated


def update_instructions(text: str) -> str:
    """Replace only our marked block; reject incomplete or repeated markers."""
    if START not in text and END not in text:
        return text + ("\n\n" if text and not text.endswith("\n") else "\n" if text else "") + INSTRUCTIONS
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError("Incomplete or repeated harness-autonomy instruction markers; no files changed")
    start, end = text.index(START), text.index(END) + len(END)
    return text[:start] + INSTRUCTIONS.rstrip("\n") + text[end:]


def _read_optional(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig") if path.exists() else ""


def _write_backed_up(path: Path, text: str) -> None:
    if path.exists():
        backup = path.with_name(path.name + ".pre-harness-autonomy.bak")
        if not backup.exists():
            with backup.open("xb") as handle:
                handle.write(path.read_bytes())
    path.write_bytes(text.encode("utf-8"))


def configure_codex(home: Path, check: bool = False) -> int:
    """Install or read-only check preferences; never print config values or modify host policies."""
    config = home / "config.toml"
    instructions = home / ("AGENTS.override.md" if (home / "AGENTS.override.md").exists() else "AGENTS.md")
    try:
        config_text, instruction_text = _read_optional(config), _read_optional(instructions)
        updated_config, updated_instructions = update_config(config_text), update_instructions(instruction_text)
        changes = [(config, updated_config, config_text), (instructions, updated_instructions, instruction_text)]
        if check:
            ready = all(after == before for _, after, before in changes)
            print(f"[CODEX] {'OK' if ready else 'MISSING'} global autonomy preferences: {home}")
            print("[CODEX] Expected: approval_policy=never; full access; approved working-style instructions.")
            print("[CODEX] Runtime launch options and managed requirements may override these preferences.")
            return 0 if ready else 1
        home.mkdir(parents=True, exist_ok=True)
        for path, after, before in changes:
            if after != before:
                _write_backed_up(path, after)
        print(f"[CODEX] Global autonomy preferences installed: {home}")
        print("[CODEX] Existing files backed up once as *.pre-harness-autonomy.bak when changed.")
        print("[CODEX] Start a new session; launch options and managed requirements still take precedence.")
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else exc.__class__.__name__
        print(f"[CODEX] ERROR {message}")
        return 2
