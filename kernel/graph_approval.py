"""Validate recorded user decisions against the exact proposal shown in conversation.

This is consistency checking, not authentication of a host or a human identity.
The agent must ask the user and record their actual response before calling decide.
"""

from __future__ import annotations


def validate(record: dict, proposal: dict) -> list[str]:
    """A free-standing approved flag is not a decision record."""
    errors = []
    for key in ("proposal_id", "base_graph_hash", "proposed_graph_hash"):
        expected = proposal["id"] if key == "proposal_id" else proposal[key]
        if record.get(key) != expected:
            errors.append(f"decision {key} does not match the proposal")
    if record.get("actor") != "user":
        errors.append("decision requires a user response")
    for key in ("response", "conversation_ref"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            errors.append(f"decision requires {key}")
    if record.get("choice") not in ("approve", "reject", "defer"):
        errors.append("decision choice must be approve, reject or defer")
    return errors
