from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.services.openai_client import FakeLLMClient
from app.services.orchestrator import JarvisOrchestrator
from app.services.repo_discovery import RepoDiscoveryService
from app.services.voice_command_router import VoiceCommandRouter, VoiceCommandType


def test_voice_command_router_parses_control_commands():
    router = VoiceCommandRouter()

    assert router.parse("abre el repo jarvis").type == VoiceCommandType.OPEN_REPO
    assert router.parse("cambia al repo api").type == VoiceCommandType.SWITCH_REPO
    assert router.parse("nuevo chat").type == VoiceCommandType.NEW_CHAT
    assert router.parse("finaliza chat").type == VoiceCommandType.END_CHAT
    assert router.parse("que pendientes hay").type == VoiceCommandType.LIST_PENDING
    assert router.parse("sí").type == VoiceCommandType.APPROVE
    assert router.parse("no").type == VoiceCommandType.REJECT


def test_repo_discovery_resolves_unique_match_and_detects_ambiguity(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    discovery = RepoDiscoveryService(orchestrator.settings, orchestrator.registry)

    alpha = tmp_path / "alpha-app"
    beta = tmp_path / "beta-app"
    alpha.mkdir()
    beta.mkdir()
    (alpha / ".git").mkdir()
    (beta / ".git").mkdir()

    resolved, candidates = discovery.resolve_repo_by_name("alpha")
    assert resolved is not None
    assert resolved.repo_path == str(alpha.resolve())
    assert candidates[0].display_name == "alpha-app"

    alpha_alt = tmp_path / "alpha-tools"
    alpha_alt.mkdir()
    (alpha_alt / ".git").mkdir()

    resolved_ambiguous, candidates_ambiguous = discovery.resolve_repo_by_name("alpha")
    assert resolved_ambiguous is None
    assert len(candidates_ambiguous) >= 2


def _orchestrator(tmp_path):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return JarvisOrchestrator.create(settings=settings, llm_client=FakeLLMClient())
