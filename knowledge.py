"""
The training research library the coach reads before it plans.

Each topic is one markdown file in knowledge/ with a small front matter block
(topic, title, keywords, last_reviewed) followed by a summary, graded findings,
rules for the coach and references. principles.md is the short distilled list
that rides along in every system prompt; README.md is for people, not the coach.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
NOT_TOPICS = {"README", "principles"}
REQUIRED_FIELDS = ("topic", "title", "keywords", "last_reviewed")
REQUIRED_SECTIONS = ("## Summary", "## Key findings", "## Rules for the coach",
                     "## Where evidence is thin or disputed", "## References")
MAX_TOPICS_PER_CALL = 3


def _split_front_matter(text: str) -> tuple[dict, str]:
    """Read the simple key: value lines between the opening and closing --- lines."""
    if not text.startswith("---"):
        return {}, text
    head, _, body = text[3:].partition("\n---")
    meta = {}
    for line in head.strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, body.lstrip("\n")


@lru_cache(maxsize=1)
def _library() -> dict[str, dict]:
    topics = {}
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        if path.stem in NOT_TOPICS:
            continue
        meta, body = _split_front_matter(path.read_text(encoding="utf-8"))
        key = meta.get("topic") or path.stem
        topics[key] = {"key": key, "title": meta.get("title", key), "meta": meta,
                       "body": body, "path": path}
    return topics


def list_topics() -> list[str]:
    return list(_library())


def topic_titles() -> dict[str, str]:
    return {k: t["title"] for k, t in _library().items()}


def get_topics(keys: list[str]) -> str:
    """The full text of the requested topics, joined for one tool result."""
    library = _library()
    unknown = [k for k in keys if k not in library]
    if unknown:
        raise KeyError(", ".join(unknown))
    return "\n\n".join(library[k]["body"] for k in keys)


@lru_cache(maxsize=1)
def principles() -> str:
    path = KNOWLEDGE_DIR / "principles.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""
