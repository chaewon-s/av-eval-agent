from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DOC_ROOTS = [
    "av_eval_agent/README.md",
    "av_eval_agent/docs",
    "docs",
]

SEARCHABLE_SUFFIXES = {
    ".md",
    ".rst",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
}

SKIP_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "data",
    "cache",
    "output_frames",
    "output_video",
    "tmp",
}


def _relative_path(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_root_files(project_root: Path, root_text: str) -> Iterable[Path]:
    root = project_root / root_text
    if root.is_file() and root.suffix.lower() in SEARCHABLE_SUFFIXES:
        yield root
        return
    if not root.exists() or not root.is_dir():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SEARCHABLE_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(project_root).parts):
            continue
        yield path


def iter_documents(project_root: Path, roots: list[str] | None = None) -> list[Path]:
    documents: dict[str, Path] = {}
    for root_text in roots or DEFAULT_DOC_ROOTS:
        for path in _iter_root_files(project_root, root_text):
            documents[str(path.resolve())] = path
    return sorted(documents.values(), key=lambda item: _relative_path(project_root, item))


def _terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[\w가-힣.-]+", query) if len(term) >= 2]


def _snippet(text: str, terms: list[str], *, radius: int = 140) -> str:
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return text[: radius * 2].replace("\n", " ").strip()
    center = min(positions)
    start = max(0, center - radius)
    end = min(len(text), center + radius)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return (prefix + text[start:end] + suffix).replace("\n", " ").strip()


def search_documents(
    project_root: Path,
    query: str,
    *,
    limit: int = 8,
    roots: list[str] | None = None,
) -> list[dict[str, Any]]:
    terms = _terms(query)
    if not terms:
        return []

    matches: list[dict[str, Any]] = []
    for path in iter_documents(project_root, roots):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        relative = _relative_path(project_root, path)
        filename = path.name.lower()
        score = 0
        for term in terms:
            score += lowered.count(term)
            if term in filename:
                score += 3
            if term in relative.lower():
                score += 2
        if score <= 0:
            continue
        matches.append(
            {
                "path": relative,
                "score": score,
                "snippet": _snippet(text, terms),
            }
        )

    matches.sort(key=lambda item: (item["score"], item["path"]), reverse=True)
    return matches[:limit]

