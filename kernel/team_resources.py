"""Resource names and conservative ownership checks for the team registry.

Paths are repository relative and case folded so mixed Windows/Linux workers cannot
claim aliases of the same file. Globs reserve their entire fixed parent subtree.
Named contracts reserve logical shared resources; they do not authorize file edits.
"""

from __future__ import annotations

import re
import unicodedata


class TeamError(Exception):
    """A request that cannot be fulfilled; status is suitable for the HTTP adapter."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def text_field(payload: dict, name: str, limit: int = 512) -> str:
    """Require a bounded, nonempty string rather than coercing untrusted JSON."""
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise TeamError(f"{name} must be a nonempty string of at most {limit} characters", 400)
    return value.strip()


def commit_sha(payload: dict, name: str) -> str:
    """Accept Git SHA-1 or SHA-256 object names, never abbreviated refs."""
    value = text_field(payload, name, 64)
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value):
        raise TeamError(f"{name} must be a full lowercase Git object id", 400)
    return value


def normalized_path(value: str, *, root_allowed: bool = False) -> str:
    """Normalize a relative path without permitting escapes or platform aliases."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise TeamError("resource paths must be nonempty strings", 400)
    value = unicodedata.normalize("NFC", value.replace("\\", "/"))
    if value.startswith("/") or ":" in value or any(part == ".." for part in value.split("/")):
        raise TeamError(f"resource path must stay inside the repository: {value}", 400)
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if any(part.endswith((" ", ".")) or any(ord(c) < 32 for c in part) for part in parts):
        raise TeamError("resource path has an ambiguous platform alias", 400)
    result = "/".join(parts).casefold()
    if not result and not root_allowed:
        raise TeamError("a file resource must name a file", 400)
    return result


def normalize_resource(value: str) -> str:
    """Canonical file/subtree/contract form; unknown resource kinds are rejected."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise TeamError("resources must contain bounded nonempty strings", 400)
    value = value.strip()
    kind, separator, name = value.partition(":")
    if not separator:
        kind, name = ("subtree" if value.endswith(("/", "\\")) else "file"), value
    if kind == "contract":
        name = name.strip()
        if not name or any(char in name for char in "*?[\x00") or any(ord(c) < 32 for c in name):
            raise TeamError("contract resources must name one literal contract", 400)
        return "contract:" + unicodedata.normalize("NFC", name.strip()).casefold()
    if kind not in ("file", "subtree"):
        raise TeamError(f"unknown resource kind: {kind}", 400)
    name = name.replace("\\", "/")
    if kind == "subtree" and name == "/":
        name = "."  # Canonical repository-root resource produced by a top-level glob.
    wildcard = re.search(r"[*?[]", name)
    if wildcard:
        name = name[:wildcard.start()].rsplit("/", 1)[0] if "/" in name[:wildcard.start()] else "."
        kind = "subtree"
    path = normalized_path(name, root_allowed=kind == "subtree")
    return f"{kind}:{path}" + ("/" if kind == "subtree" else "")


def resources_from(payload: dict, name: str = "resources") -> list[str]:
    """Deduplicate resource sets before taking their atomic reservation."""
    resources = payload.get(name)
    if not isinstance(resources, list) or not resources or len(resources) > 256:
        raise TeamError(f"{name} must contain between 1 and 256 resources", 400)
    return sorted({normalize_resource(value) for value in resources})


def overlaps(left: str, right: str) -> bool:
    """File/subtree containment overlaps; contracts conflict only with their name."""
    left_kind, left_path = left.split(":", 1)
    right_kind, right_path = right.split(":", 1)
    if "contract" in (left_kind, right_kind):
        return left == right
    left_path, right_path = left_path.rstrip("/"), right_path.rstrip("/")
    if left_path == right_path:
        return True
    if left_kind == "subtree" and (not left_path or right_path.startswith(left_path + "/")):
        return True
    return right_kind == "subtree" and (not right_path or left_path.startswith(right_path + "/"))


def authorized_paths(changed_paths: object, resources: list[str]) -> list[str]:
    """Validate the trusted Git diff; a logical contract alone cannot own a path."""
    if not isinstance(changed_paths, list) or any(not isinstance(path, str) for path in changed_paths):
        raise TeamError("changed_paths must be a list supplied by the trusted Git checker", 400)
    paths = sorted({normalized_path(path) for path in changed_paths})
    for path in paths:
        if not covers(resources, path):
            raise TeamError(f"changed path is outside task reservations: {path}")
    return paths


def covers(resources: list[str], path: str) -> bool:
    """Actual changed-path membership; contracts alone never authorize source edits."""
    candidate = "file:" + normalized_path(path)
    return any(overlaps(candidate, normalize_resource(resource)) for resource in resources
               if not resource.startswith("contract:"))
