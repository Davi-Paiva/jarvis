from __future__ import annotations

import re
from typing import Callable, Iterable, List, Optional


def filter_scope(files: List[str], scope: Iterable[str]) -> List[str]:
    normalized_scope = [str(item).strip().strip("/") for item in scope if str(item).strip()]
    if not normalized_scope:
        return files
    return [
        path
        for path in files
        if any(path == item or path.startswith(item + "/") for item in normalized_scope)
    ]


def render_repo_tree(files: List[str], max_lines: int = 80) -> str:
    if not files:
        return "- (no visible files)"
    lines: List[str] = []
    seen = set()
    for file_path in files:
        parts = file_path.split("/")
        for depth, part in enumerate(parts):
            key = tuple(parts[: depth + 1])
            if key in seen:
                continue
            seen.add(key)
            indent = "  " * depth
            suffix = "/" if depth < len(parts) - 1 else ""
            lines.append("%s- %s%s" % (indent, part, suffix))
            if len(lines) >= max_lines:
                lines.append("  ...")
                return "\n".join(lines)
    return "\n".join(lines)


def summarize_repo_files(files: List[str]) -> str:
    if not files:
        return "- No visible repository files."

    frontend = [
        path for path in files
        if path.lower().endswith((".html", ".css", ".scss", ".tsx", ".jsx", ".ts", ".js"))
        or any(
            segment in path.lower()
            for segment in ("/src/", "/pages/", "/components/", "/templates/", "/static/", "/public/")
        )
    ]
    docs = [path for path in files if path.lower().startswith("docs/") or path.lower().endswith(".md")]
    python = [path for path in files if path.lower().endswith(".py")]
    server_entries = [
        path for path in files
        if path.lower().endswith(".py") and path.lower().rsplit("/", 1)[-1] in {"main.py", "app.py", "server.py"}
    ]
    lines = [
        "- Visible file count: %s" % len(files),
        "- Frontend/template/static surface detected: %s" % ("yes" if frontend else "no"),
        "- Python source detected: %s" % ("yes" if python else "no"),
        "- Docs or markdown detected: %s" % ("yes" if docs else "no"),
    ]
    if frontend:
        lines.append("- Example UI files: %s" % ", ".join(frontend[:5]))
    if server_entries:
        lines.append("- Example app entry files: %s" % ", ".join(server_entries[:5]))
    elif python:
        lines.append("- Example Python files: %s" % ", ".join(python[:5]))
    if docs:
        lines.append("- Example docs files: %s" % ", ".join(docs[:5]))
    return "\n".join(lines)


def task_keywords(text_chunks: Iterable[str], limit: int = 24) -> List[str]:
    text = " ".join(chunk for chunk in text_chunks if chunk).lower()
    words = re.findall(r"[a-z0-9_/-]{3,}", text)
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "you",
        "implementation",
        "approved",
        "change",
        "repository",
        "context",
        "phase",
        "code",
        "files",
        "steps",
        "plan",
        "task",
        "goal",
        "requirements",
    }
    keywords: List[str] = []
    seen = set()
    for word in words:
        normalized = word.strip("/-_")
        if not normalized or normalized in stop_words or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords[:limit]


def pick_candidate_files(
    text_chunks: Iterable[str],
    visible_files: List[str],
    limit: int = 8,
) -> List[str]:
    if not visible_files:
        return []
    keywords = task_keywords(text_chunks)
    priority_names = {
        "app",
        "homepage",
        "home",
        "layout",
        "routes",
        "router",
        "index",
        "main",
        "page",
        "hero",
        "landing",
        "style",
        "styles",
    }
    scored = []
    for index, path in enumerate(visible_files):
        lowered = path.lower()
        filename = lowered.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        score = 0
        for keyword in keywords:
            if keyword and keyword in stem:
                score += 5
            elif keyword and keyword in lowered:
                score += 3
        if stem in priority_names:
            score += 4
        if any(part in lowered for part in ("/pages/", "/components/", "/routes/", "/app/")):
            score += 2
        if filename.endswith((".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html", ".py", ".md")):
            score += 1
        scored.append((score, index, path))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [path for score, _index, path in scored[:limit] if score > 0]
    if selected:
        return selected
    return visible_files[: min(limit, len(visible_files))]


def select_context_files(
    text_chunks: Iterable[str],
    visible_files: List[str],
    limit: int = 120,
) -> List[str]:
    if len(visible_files) <= limit:
        return visible_files

    selected: List[str] = []
    seen = set()

    def add(path: str) -> None:
        if path in seen or len(selected) >= limit:
            return
        seen.add(path)
        selected.append(path)

    for path in pick_candidate_files(text_chunks, visible_files, limit=min(24, limit)):
        add(path)

    keywords = task_keywords(text_chunks)
    favored_segments = (
        "src/",
        "app/",
        "pages/",
        "components/",
        "routes/",
        "templates/",
        "static/",
        "public/",
        "docs/",
    )
    favored_extensions = (
        ".tsx",
        ".ts",
        ".jsx",
        ".js",
        ".css",
        ".scss",
        ".html",
        ".md",
        ".py",
    )

    for path in visible_files:
        lowered = path.lower()
        if any(segment in lowered for segment in favored_segments) or lowered.endswith(favored_extensions):
            add(path)
        if len(selected) >= limit:
            break

    if keywords and len(selected) < limit:
        for path in visible_files:
            lowered = path.lower()
            if any(keyword in lowered for keyword in keywords):
                add(path)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        for path in visible_files:
            add(path)
            if len(selected) >= limit:
                break

    return selected


def build_file_content_sections(
    repo_path: str,
    files: List[str],
    read_file: Callable[[str, str, int], str],
    max_files: int = 8,
    max_chars: int = 4000,
    max_lines: int = 120,
) -> str:
    sections: List[str] = []
    for relative_path in files[:max_files]:
        try:
            content = read_file(repo_path, relative_path, max_chars=max_chars)
        except Exception:
            continue
        snippet = "\n".join(content.splitlines()[:max_lines]).strip()
        if not snippet:
            continue
        sections.append("File: %s\n%s" % (relative_path, snippet))
    return "\n\n".join(sections)
