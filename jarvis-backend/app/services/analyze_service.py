from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from pathlib import Path

from app.models.schemas import AnalyzeOutput
from app.services.openai_client import LLMClient


logger = logging.getLogger(__name__)


@dataclass
class ChangeInsight:
    change_type: str
    focus: str
    reason: str
    added_count: int
    removed_count: int
    touched_symbols: list[str]
    added_examples: list[str]
    removed_examples: list[str]


class AnalyzeService:
    """Builds change explanations, using the configured LLM when diff context is available."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client

    async def analyze(self, file_name: str, content: str, diff: str = "") -> AnalyzeOutput:
        normalized_name = file_name.lower()
        normalized_content = content.lower()
        line_count = len(content.splitlines()) or 1
        file_type = self._infer_file_type(file_name)
        role = self._infer_role(normalized_name, normalized_content)
        symbols = self._extract_symbols(content)
        imports_count = self._count_imports(content)
        change_insight = self._analyze_diff(diff)

        logger.info(
            "Generated analysis for %s as %s / %s",
            file_name,
            file_type,
            role,
        )

        if diff and self.llm_client is not None:
            return await self.llm_client.explain_file_change(
                file_name=file_name,
                content=content,
                diff=diff,
            )

        if change_insight is not None:
            return AnalyzeOutput(
                summary=self._build_change_summary(file_name, change_insight),
                steps=self._build_change_steps(change_insight),
            )

        return AnalyzeOutput(
            summary=self._build_summary(file_name, file_type, role, symbols, line_count),
            steps=self._build_steps(file_type, role, symbols, line_count, imports_count),
        )

    def _infer_file_type(self, file_name: str) -> str:
        extension = Path(file_name).suffix.lower()
        return {
            ".py": "Python module",
            ".ts": "TypeScript file",
            ".tsx": "React component",
            ".js": "JavaScript file",
            ".jsx": "React component",
            ".kt": "Kotlin file",
            ".java": "Java file",
            ".json": "JSON configuration file",
            ".md": "Markdown document",
        }.get(extension, "source file")

    def _infer_role(self, file_name: str, content: str) -> str:
        hints = f"{file_name}\n{content}"
        if "controller" in hints or "router" in hints or "endpoint" in hints:
            return "controller layer"
        if "service" in hints or "client" in hints or "repository" in hints:
            return "service layer"
        if "component" in hints or "useeffect" in hints or "jsx" in hints:
            return "UI layer"
        if "model" in hints or "schema" in hints or "basemodel" in hints:
            return "data model"
        if "test_" in file_name or file_name.endswith(("spec.ts", "test.ts", "test.py")):
            return "test file"
        return "application logic"

    def _extract_symbols(self, content: str) -> list[str]:
        pattern = re.compile(
            r"^(?:async\s+def|def|class|function|const|let|var|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)",
            re.MULTILINE,
        )
        symbols: list[str] = []
        for match in pattern.finditer(content):
            symbol = match.group(1)
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) == 3:
                break
        return symbols

    def _count_imports(self, content: str) -> int:
        return len(
            [
                line
                for line in content.splitlines()
                if line.strip().startswith(("import ", "from ", "using "))
            ]
        )

    def _analyze_diff(self, diff: str) -> ChangeInsight | None:
        if not diff.strip():
            return None

        added_lines: list[str] = []
        removed_lines: list[str] = []
        for raw_line in diff.splitlines():
            if raw_line.startswith(
                (
                    "diff --git ",
                    "index ",
                    "@@",
                    "--- ",
                    "+++ ",
                    "new file mode ",
                    "deleted file mode ",
                    "similarity index ",
                    "rename from ",
                    "rename to ",
                )
            ):
                continue

            if raw_line.startswith("+"):
                added_lines.append(raw_line[1:])
            elif raw_line.startswith("-"):
                removed_lines.append(raw_line[1:])

        if not added_lines and not removed_lines:
            return None

        added_examples = self._collect_examples(added_lines)
        removed_examples = self._collect_examples(removed_lines)
        touched_symbols = self._extract_changed_symbols(added_lines + removed_lines)
        hints = "\n".join(added_lines + removed_lines).lower()

        return ChangeInsight(
            change_type=self._infer_change_type(diff, added_lines, removed_lines),
            focus=self._infer_change_focus(hints),
            reason=self._infer_change_reason(hints, added_lines, removed_lines),
            added_count=len(added_lines),
            removed_count=len(removed_lines),
            touched_symbols=touched_symbols,
            added_examples=added_examples,
            removed_examples=removed_examples,
        )

    def _build_summary(
        self,
        file_name: str,
        file_type: str,
        role: str,
        symbols: list[str],
        line_count: int,
    ) -> str:
        symbols_text = self._format_symbols(symbols)
        if symbols_text:
            return (
                f"{file_name} appears to be a {file_type} in the {role}. "
                f"It defines {symbols_text} and spans {line_count} line(s)."
            )
        return (
            f"{file_name} appears to be a {file_type} in the {role}. "
            f"It spans {line_count} line(s) and focuses on project-specific logic."
        )

    def _build_change_summary(self, file_name: str, insight: ChangeInsight) -> str:
        balance = self._format_change_balance(insight.added_count, insight.removed_count)
        symbols_text = self._format_symbols(insight.touched_symbols)
        symbol_clause = (
            f" It directly touches {symbols_text}."
            if symbols_text
            else ""
        )
        return (
            f"This change {insight.change_type} {file_name} by {balance}. "
            f"It mainly changes {insight.focus}.{symbol_clause} "
            f"The change is meant to {insight.reason}."
        )

    def _build_steps(
        self,
        file_type: str,
        role: str,
        symbols: list[str],
        line_count: int,
        imports_count: int,
    ) -> list[str]:
        symbols_text = self._format_symbols(symbols) or "its top-level logic"
        import_text = (
            f"{imports_count} import(s)"
            if imports_count
            else "no obvious external dependencies"
        )
        return [
            f"Jarvis identifies the file as a {file_type} and classifies it as part of the {role}.",
            f"The main declarations are {symbols_text}, which indicate the central behavior in the file.",
            f"The file spans {line_count} line(s) and uses {import_text}, so review those dependencies to understand how it connects to the rest of the system.",
        ]

    def _build_change_steps(self, insight: ChangeInsight) -> list[str]:
        changed_parts = []
        if insight.added_examples:
            changed_parts.append(f"added {self._join_examples(insight.added_examples)}")
        if insight.removed_examples:
            changed_parts.append(f"removed {self._join_examples(insight.removed_examples)}")

        changed_text = "; ".join(changed_parts) if changed_parts else "changed the file contents"
        touched_symbols = self._format_symbols(insight.touched_symbols) or insight.focus
        return [
            f"What changed: this edit {changed_text}.",
            f"Where it changed: the update centers on {touched_symbols} and shifts {insight.focus}.",
            f"Why: this change is meant to {insight.reason}.",
        ]

    def _collect_examples(self, lines: list[str], limit: int = 2) -> list[str]:
        examples: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {"{", "}", "(", ")", "[", "]"}:
                continue
            if stripped not in examples:
                examples.append(self._shorten(stripped))
            if len(examples) == limit:
                break
        return examples

    def _extract_changed_symbols(self, lines: list[str]) -> list[str]:
        pattern = re.compile(
            r"(?:async\s+def|def|class|function|fun|interface|type|const|let|var|val)\s+([A-Za-z_][A-Za-z0-9_]*)"
        )
        symbols: list[str] = []
        for line in lines:
            match = pattern.search(line.strip())
            if not match:
                continue
            symbol = match.group(1)
            if symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) == 3:
                break
        return symbols

    def _infer_change_type(
        self,
        diff: str,
        added_lines: list[str],
        removed_lines: list[str],
    ) -> str:
        if "new file mode" in diff or (added_lines and not removed_lines):
            return "adds to"
        if "deleted file mode" in diff or (removed_lines and not added_lines):
            return "removes from"
        return "updates"

    def _infer_change_focus(self, hints: str) -> str:
        if any(token in hints for token in ("@router", "apirouter", "http", "request", "response")):
            return "HTTP behavior"
        if any(token in hints for token in ("git diff", "git ls-files", "changed file", "untracked")):
            return "git change detection"
        if any(token in hints for token in ("assert ", "test_", "expect(")):
            return "test coverage"
        if any(token in hints for token in ("schema", "basemodel", "field(", "pydantic")):
            return "the request or data contract"
        if any(token in hints for token in ("component", "useeffect", "render", "button", "label")):
            return "UI behavior"
        return "core logic"

    def _infer_change_reason(
        self,
        hints: str,
        added_lines: list[str],
        removed_lines: list[str],
    ) -> str:
        if any(token in hints for token in ("http_1_1", "timeout", "connecttimeout", "content-type", "localhost", "request")):
            return "fix integration reliability or HTTP compatibility"
        if any(token in hints for token in ("git diff", "git ls-files", "changed file", "untracked")):
            return "improve how the tool detects modified files"
        if any(token in hints for token in ("@router", "apirouter", "response_model", "status_code")):
            return "add or adjust an API endpoint"
        if any(token in hints for token in ("assert ", "test_", "expect(")):
            return "cover the behavior with tests or tighten an assertion"
        if any(token in hints for token in ("schema", "basemodel", "field(", "pydantic")):
            return "change the request or response contract"
        if added_lines and not removed_lines:
            return "introduce new behavior"
        if removed_lines and not added_lines:
            return "remove behavior that is no longer needed"
        return "refine existing behavior"

    def _format_change_balance(self, added_count: int, removed_count: int) -> str:
        if added_count and removed_count:
            return f"adding {added_count} line(s) and removing {removed_count} line(s)"
        if added_count:
            return f"adding {added_count} line(s)"
        return f"removing {removed_count} line(s)"

    def _join_examples(self, examples: list[str]) -> str:
        if len(examples) == 1:
            return f"`{examples[0]}`"
        return ", ".join(f"`{example}`" for example in examples)

    def _shorten(self, text: str, max_length: int = 80) -> str:
        return text if len(text) <= max_length else text[: max_length - 3] + "..."

    def _format_symbols(self, symbols: list[str]) -> str:
        if not symbols:
            return ""
        if len(symbols) == 1:
            return symbols[0]
        if len(symbols) == 2:
            return f"{symbols[0]} and {symbols[1]}"
        return f"{symbols[0]}, {symbols[1]}, and {symbols[2]}"