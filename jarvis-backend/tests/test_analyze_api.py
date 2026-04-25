from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.openai_client import FakeLLMClient


def test_post_analyze_returns_mock_analysis(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/analyze",
            json={
                "fileName": "user_service.py",
                "content": "import os\n\nclass UserService:\n    pass\n",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "service" in payload["summary"].lower()
    assert payload["steps"]
    assert len(payload["steps"]) == 3


def test_post_analyze_describes_the_change_and_reason_when_diff_is_present(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/analyze",
            json={
                "fileName": "jarvis-intellij-plugin/src/main/kotlin/com/jarvis/intellij/network/JarvisApiClient.kt",
                "content": "class JarvisApiClient {\n    private val httpClient = HttpClient.newBuilder()\n        .version(HttpClient.Version.HTTP_1_1)\n        .build()\n}\n",
                "diff": """diff --git a/jarvis-intellij-plugin/src/main/kotlin/com/jarvis/intellij/network/JarvisApiClient.kt b/jarvis-intellij-plugin/src/main/kotlin/com/jarvis/intellij/network/JarvisApiClient.kt
@@ -1,3 +1,4 @@
+        .version(HttpClient.Version.HTTP_1_1)
-        .build()
+        .build()
""",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert "likely reason" in payload["summary"].lower()
    assert "http compatibility" in payload["summary"].lower()
    assert payload["steps"][0].lower().startswith("what changed:")
    assert payload["steps"][2].lower().startswith("why it likely changed:")


def test_post_analyze_returns_400_when_required_fields_are_missing(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/analyze", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "fileName and content are required."


def _app(tmp_path):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return create_app(settings=settings, llm_client=FakeLLMClient())