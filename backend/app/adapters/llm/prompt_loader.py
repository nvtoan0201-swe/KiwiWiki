"""Versioned prompt templates.

Prompts live as markdown files in `adapters/llm/prompts/`, named
`<purpose>_v<N>.md`. Behavior changes bump the version rather than silently
editing a prompt. `render_prompt` substitutes `{placeholders}` and leaves
unknown braces untouched (markdown often contains literal braces).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@cache
def _load(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **variables: Any) -> str:
    """Load prompt `name` (e.g. 'scoping_v1') and fill its placeholders."""
    return _load(name).format_map(_SafeDict(variables))
