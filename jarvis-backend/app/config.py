from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


def _dotenv_candidates(env_file: str = ".env") -> List[Path]:
    project_root_env = Path(__file__).resolve().parents[1] / env_file
    cwd_env = Path(env_file)
    candidates = [cwd_env, project_root_env]

    # Keep order while removing duplicates.
    deduped: List[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item.resolve()) if item.exists() else str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _load_dotenv(env_file: str = ".env") -> None:
    """Tiny dotenv loader so the core can run without a framework dependency."""
    for path in _dotenv_candidates(env_file):
        if not path.exists():
            continue

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            # Keep explicit environment overrides, but treat empty values as unset.
            if key not in os.environ or os.environ.get(key, "") == "":
                os.environ[key] = value


def _split_csv(value: Optional[str], default: List[str]) -> List[str]:
    if value is None or value.strip() == "":
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseModel):
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-5.4-mini"
    jarvis_env: str = "local"
    jarvis_user_id: str = "demo"
    jarvis_data_dir: str = "./data"
    jarvis_db_path: str = "./data/jarvis.db"
    jarvis_memory_dir: str = "./data/memory"
    jarvis_allowed_repo_roots: List[str] = Field(
        default_factory=lambda: ["/Users/joanvm/Desktop/Projects"]
    )
    jarvis_allowed_commands: List[str] = Field(
        default_factory=lambda: [
            "pytest",
            "npm test",
            "npm run test",
            "npm run build",
            "git status",
            "git diff",
        ]
    )
    log_level: str = "INFO"

    @classmethod
    def load(cls, env_file: str = ".env") -> "Settings":
        _load_dotenv(env_file)
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            jarvis_env=os.getenv("JARVIS_ENV", "local"),
            jarvis_user_id=os.getenv("JARVIS_USER_ID", "demo"),
            jarvis_data_dir=os.getenv("JARVIS_DATA_DIR", "./data"),
            jarvis_db_path=os.getenv("JARVIS_DB_PATH", "./data/jarvis.db"),
            jarvis_memory_dir=os.getenv("JARVIS_MEMORY_DIR", "./data/memory"),
            jarvis_allowed_repo_roots=_split_csv(
                os.getenv("JARVIS_ALLOWED_REPO_ROOTS"),
                ["/Users/joanvm/Desktop/Projects"],
            ),
            jarvis_allowed_commands=_split_csv(
                os.getenv("JARVIS_ALLOWED_COMMANDS"),
                [
                    "pytest",
                    "npm test",
                    "npm run test",
                    "npm run build",
                    "git status",
                    "git diff",
                ],
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def ensure_directories(self) -> None:
        Path(self.jarvis_data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.jarvis_memory_dir).mkdir(parents=True, exist_ok=True)
        Path(self.jarvis_db_path).parent.mkdir(parents=True, exist_ok=True)


def load_settings(env_file: str = ".env") -> Settings:
    settings = Settings.load(env_file)
    settings.ensure_directories()
    return settings

