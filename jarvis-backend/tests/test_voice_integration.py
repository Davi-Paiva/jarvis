"""
Validation tests for voice session service integration with new conversational flow.
Simplified tests focusing on key changes:
- handle_user_message routing
- _summarize_turn with new TurnTypes
- _status_from_phase mapping
"""

import pytest
from app.models.turns import TurnType
from app.services.voice_session_service import VoiceSessionService, _status_from_phase

from app.config import Settings
from app.models.turns import TurnRequest
from app.services.openai_client import FakeLLMClient
from app.services.orchestrator import JarvisOrchestrator


class TestStatusMapping:
    """Tests for _status_from_phase mapping new phases."""

    def test_status_for_branch_permission_phase(self):
        """BRANCH_PERMISSION phase should map to waiting_approval."""
        status = _status_from_phase("BRANCH_PERMISSION")
        assert status == "waiting_approval"

    def test_status_for_branch_name_phase(self):
        """BRANCH_NAME phase should map to waiting_approval."""
        status = _status_from_phase("BRANCH_NAME")
        assert status == "waiting_approval"

    def test_status_for_branch_confirmation_phase(self):
        """BRANCH_CONFIRMATION phase should map to waiting_approval."""
        status = _status_from_phase("BRANCH_CONFIRMATION")
        assert status == "waiting_approval"

    def test_status_for_plan_step_review_phase(self):
        """PLAN_STEP_REVIEW phase should map to waiting_approval."""
        status = _status_from_phase("PLAN_STEP_REVIEW")
        assert status == "waiting_approval"

    def test_status_for_waiting_execution_approval_phase(self):
        """WAITING_EXECUTION_APPROVAL phase should map to waiting_approval."""
        status = _status_from_phase("WAITING_EXECUTION_APPROVAL")
        assert status == "waiting_approval"

    def test_status_for_answering_question_phase(self):
        """ANSWERING_QUESTION phase should map to running."""
        status = _status_from_phase("ANSWERING_QUESTION")
        assert status == "running"

    def test_status_for_done_phase(self):
        """DONE phase should map to idle."""
        status = _status_from_phase("DONE")
        assert status == "idle"

    def test_status_for_failed_phase(self):
        """FAILED phase should map to idle."""
        status = _status_from_phase("FAILED")
        assert status == "idle"

    def test_status_for_old_phases_unchanged(self):
        """Old phases should continue mapping as before."""
        assert _status_from_phase("WAITING_APPROVAL") == "waiting_approval"
        assert _status_from_phase("PLANNING") == "running"
        assert _status_from_phase("EXECUTING") == "running"
        assert _status_from_phase("FINALIZING") == "running"


class TestTurnTypesSupportedInVoice:
    """Tests verifying that new TurnTypes are valid and recognized."""

    def test_explanation_turn_type_exists(self):
        """EXPLANATION TurnType should exist for code explanation flow."""
        assert hasattr(TurnType, "EXPLANATION")

    def test_branch_permission_turn_type_exists(self):
        """BRANCH_PERMISSION TurnType should exist."""
        assert hasattr(TurnType, "BRANCH_PERMISSION")

    def test_branch_name_turn_type_exists(self):
        """BRANCH_NAME TurnType should exist."""
        assert hasattr(TurnType, "BRANCH_NAME")

    def test_branch_confirmation_turn_type_exists(self):
        """BRANCH_CONFIRMATION TurnType should exist."""
        assert hasattr(TurnType, "BRANCH_CONFIRMATION")

    def test_plan_step_review_turn_type_exists(self):
        """PLAN_STEP_REVIEW TurnType should exist."""
        assert hasattr(TurnType, "PLAN_STEP_REVIEW")

    def test_execution_approval_turn_type_exists(self):
        """EXECUTION_APPROVAL TurnType should exist."""
        assert hasattr(TurnType, "EXECUTION_APPROVAL")


class TestVoiceSessionServiceHasUpdatedMethods:
    """Tests verifying VoiceSessionService has required methods."""

    def test_voice_service_has_summarize_turn_method(self):
        """VoiceSessionService should have _summarize_turn method."""
        from app.services.voice_session_service import VoiceSessionService
        assert hasattr(VoiceSessionService, "_summarize_turn")

    def test_voice_service_has_handle_repo_request_method(self):
        """VoiceSessionService should have _handle_repo_request method."""
        from app.services.voice_session_service import VoiceSessionService
        assert hasattr(VoiceSessionService, "_handle_repo_request")

    def test_voice_service_has_status_from_phase_function(self):
        """Module should have _status_from_phase function."""
        from app.services.voice_session_service import _status_from_phase
        assert callable(_status_from_phase)

    def test_summarize_turn_keeps_full_plan_step_message(self, tmp_path):
        settings = Settings(
            jarvis_data_dir=str(tmp_path / "data"),
            jarvis_db_path=str(tmp_path / "jarvis.db"),
            jarvis_memory_dir=str(tmp_path / "memory"),
            jarvis_allowed_repo_roots=[str(tmp_path)],
        )
        orchestrator = JarvisOrchestrator.create(settings=settings, llm_client=FakeLLMClient())
        service = VoiceSessionService(orchestrator=orchestrator)
        long_message = (
            "Step 1: Implement a websocket purchase notification endpoint with repository-specific "
            "details that should remain fully visible to the user without being truncated at the end."
        )
        turn = TurnRequest(
            agent_id="repo_agent_demo",
            repo_agent_id="repo_agent_demo",
            type=TurnType.PLAN_STEP_REVIEW,
            priority=70,
            message=long_message,
            requires_user_response=True,
        )

        assert service._summarize_turn(turn, "demo-repo") == long_message
