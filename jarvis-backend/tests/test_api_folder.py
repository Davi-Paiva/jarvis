from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.openai_client import FakeLLMClient


def test_post_folder_creates_and_reuses_repo_agent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    with TestClient(_app(tmp_path)) as client:
        first = client.post("/folder", json={"repo_path": str(repo)})
        second = client.post("/folder", json={"repo_path": str(repo)})

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["repo_agent_id"] == second.json()["repo_agent_id"]
    assert first.json()["repo_id"] == second.json()["repo_id"]
    assert first.json()["phase"] == "INTAKE"
    assert (tmp_path / "memory" / ("%s.md" % first.json()["repo_agent_id"])).exists()


def test_post_folder_returns_400_for_invalid_repo_path(tmp_path):
    missing = tmp_path / "missing-repo"

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/folder", json={"repo_path": str(missing)})

    assert response.status_code == 400
    assert "does not exist or is not a directory" in response.json()["detail"]


def test_post_folder_returns_403_for_disallowed_repo_path(tmp_path):
    outside = tmp_path.parent / "outside-repo"
    outside.mkdir(exist_ok=True)
    (outside / "main.py").write_text("print('hello')\n", encoding="utf-8")

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/folder", json={"repo_path": str(outside)})

    assert response.status_code == 403
    assert "outside allowed roots" in response.json()["detail"]


def _app(tmp_path):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return create_app(settings=settings, llm_client=FakeLLMClient())
