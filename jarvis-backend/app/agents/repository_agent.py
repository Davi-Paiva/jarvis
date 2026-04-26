from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, List, Optional

from app.agents.task_agent import TaskAgent
from app.graphs.repository_agent_graph import build_repository_agent_graph
from app.models.repository import RepositoryAgentState
from app.models.state import RepositoryAgentPhase, TaskAgentStatus
from app.models.task import TaskAgentState, TaskPlanItem
from app.models.turns import TurnRequest, TurnResponse, TurnType
from app.services.global_manager import GlobalManager
from app.services.local_executor import LocalExecutor
from app.services.memory_service import MemoryService
from app.services.openai_client import LLMClient
from app.services.repo_context_builder import (
    build_file_content_sections,
    pick_candidate_files,
    render_repo_tree,
    select_context_files,
    summarize_repo_files,
)
from app.services.repository_registry import RepositoryRegistry


class RepositoryAgent:
    def __init__(
        self,
        state: RepositoryAgentState,
        registry: RepositoryRegistry,
        manager: GlobalManager,
        executor: LocalExecutor,
        llm_client: LLMClient,
        memory_service: MemoryService,
        graph_checkpointer: Optional[Any] = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self.manager = manager
        self.executor = executor
        self.llm_client = llm_client
        self.memory_service = memory_service
        self.graph_checkpointer = graph_checkpointer
        self.graph = build_repository_agent_graph(checkpointer=graph_checkpointer)

    async def start_task(
        self,
        message: str,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> RepositoryAgentState:
        self.manager.acquire_intake_lock(self.state.repo_agent_id)
        self.state.phase = RepositoryAgentPhase.INTAKE
        self.state.task_goal = message
        self.state.acceptance_criteria = acceptance_criteria or []
        self.registry.save_agent_state(self.state)
        self.memory_service.record_task_started(self.state)

        self.manager.emit_progress(self.state.repo_agent_id, "Intake started.")
        repo_context = self._build_repo_context()
        self.state.planning_context = repo_context
        memory_context = self.memory_service.render_memory_for_llm(self.state.repo_agent_id).text

        self.state.phase = RepositoryAgentPhase.PLANNING
        self.state.requirements = await self.llm_client.extract_requirements(
            task_goal=message,
            acceptance_criteria=self.state.acceptance_criteria,
            repo_context=repo_context,
            memory_context=memory_context,
        )
        self.state.plan = await self.llm_client.create_plan(
            state=self.state,
            repo_context=repo_context,
            memory_context=memory_context,
        )
        self.state.phase = RepositoryAgentPhase.WAITING_APPROVAL
        self.registry.save_agent_state(self.state)
        self.memory_service.record_plan_proposed(self.state)

        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.APPROVAL,
                priority=60,
                message=(
                    "Plan ready for the project. %s Approve this plan to start execution?"
                    % (self.state.plan or "")
                ),
                context="RepositoryAgent is waiting for plan approval.",
                requires_user_response=True,
            )
        )
        return self.state

    async def answer_code_question(self, message: str) -> RepositoryAgentState:
        self.state.intent_type = "EXPLAIN_CODE"
        self.state.original_user_prompt = message
        self.state.phase = RepositoryAgentPhase.ANSWERING_QUESTION
        self.registry.save_agent_state(self.state)

        repo_context = self._build_repo_context()
        self.state.planning_context = repo_context
        memory_context = self.memory_service.render_memory_for_llm(self.state.repo_agent_id).text

        explanation = None
        if hasattr(self.llm_client, "answer_code_question"):
            explanation_method = getattr(self.llm_client, "answer_code_question")
            explanation = await explanation_method(
                repo_state=self.state,
                question=message,
                repo_context=repo_context,
                memory_context=memory_context,
            )
        if not explanation:
            explanation = (
                "I can help explain the repository at `%s`, but there is not a dedicated LLM "
                "explanation flow implemented yet. I gathered repository and memory context for this "
                "question, so the next step is to wire a specialized explanation responder."
            ) % self.state.repo_path

        self.state.last_explanation = explanation
        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.EXPLANATION,
                priority=40,
                message=explanation,
                context="RepositoryAgent answered a code question.",
                requires_user_response=False,
            )
        )
        self.state.phase = RepositoryAgentPhase.INTAKE
        self.registry.save_agent_state(self.state)
        return self.state

    async def start_modification_flow(
        self,
        message: str,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> RepositoryAgentState:
        self.manager.acquire_intake_lock(self.state.repo_agent_id)
        self.state.intent_type = "MODIFY_CODE"
        self.state.original_user_prompt = message
        self.state.task_goal = message
        self.state.acceptance_criteria = acceptance_criteria or []
        self.state.branch_decision = None
        self.state.requested_branch_name = None
        self.state.confirmed_branch_name = None
        self.state.branch_created = False
        self.state.plan_steps = []
        self.state.current_plan_step_index = 0
        self.state.execution_approved = False
        self.state.planning_context = None
        self.state.task_agents = []
        self.state.changed_files = []
        self.state.test_results = []
        self.state.final_report = None
        self.state.last_error = None
        self.state.phase = RepositoryAgentPhase.BRANCH_PERMISSION
        self.registry.save_agent_state(self.state)
        self.memory_service.record_task_started(self.state)

        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.BRANCH_PERMISSION,
                priority=80,
                message=(
                    "This requires code changes. Do you want me to create a new branch for these "
                    "changes, or should I work on the current branch?"
                ),
                context=(
                    "RepositoryAgent is asking whether to create a branch before modifying code."
                ),
                requires_user_response=True,
            )
        )
        return self.state

    async def handle_user_response(
        self,
        turn: TurnRequest,
        response: TurnResponse,
    ) -> RepositoryAgentState:
        if turn.type == TurnType.BRANCH_PERMISSION:
            return await self._handle_branch_permission_response(response.response)
        if turn.type == TurnType.BRANCH_NAME:
            return self._handle_branch_name_response(response.response)
        if turn.type == TurnType.BRANCH_CONFIRMATION:
            return await self._handle_branch_confirmation_response(turn, response.response)
        if turn.type == TurnType.PLAN_STEP_REVIEW:
            return await self._handle_plan_step_review(turn, response.response)
        if turn.type == TurnType.EXECUTION_APPROVAL:
            return await self._handle_execution_approval(response.response)
        if turn.type == TurnType.APPROVAL:
            approved = response.approved
            if approved is None:
                approved = _looks_like_approval(response.response)
            if not approved:
                return self._handle_plan_rejection(response.response)
            return await self.execute_approved_plan()
        return self.state

    async def execute_approved_plan(self) -> RepositoryAgentState:
        # Check if we're in the new conversational flow with plan steps
        if self.state.plan_steps:
            # New flow with user-approved plan steps
            if self.state.intent_type == "MODIFY_CODE" and not self.state.execution_approved:
                # Haven't received explicit approval yet
                self.state.phase = RepositoryAgentPhase.WAITING_EXECUTION_APPROVAL
                self.registry.save_agent_state(self.state)
                self._enqueue_turn(
                    turn_type=TurnType.EXECUTION_APPROVAL,
                    priority=80,
                    message="The plan has not been approved for execution yet. Do you want me to execute it now?",
                    context="RepositoryAgent is waiting for execution approval before proceeding.",
                    requires_user_response=True,
                )
                return self.state
            
            # Filter approved steps only
            approved_steps = [step for step in self.state.plan_steps if step.get("status") == "APPROVED"]
            
            if not approved_steps:
                # No steps were approved
                self.state.phase = RepositoryAgentPhase.PLAN_STEP_REVIEW
                self.registry.save_agent_state(self.state)
                self._enqueue_turn(
                    turn_type=TurnType.PLAN_STEP_REVIEW,
                    priority=70,
                    message="No plan steps were approved for execution. Please review and approve the steps before proceeding.",
                    context="RepositoryAgent found no approved steps to execute.",
                    requires_user_response=True,
                    metadata={"step_index": 0},
                )
                return self.state
            
            # Use approved steps directly (new conversational flow)
            task_plan_steps = approved_steps
        else:
            # Old flow: use split_tasks for backward compatibility
            task_plan_steps = None
        
        self.manager.release_intake_lock(self.state.repo_agent_id)
        self.state.phase = RepositoryAgentPhase.EXECUTING
        self.registry.save_agent_state(self.state)

        # Determine task plan: either from approved steps or by calling LLM
        if task_plan_steps is not None and self.state.intent_type == "MODIFY_CODE":
            execution_task_state = self._build_execution_task(task_plan_steps)
            task_states = [execution_task_state]
            completed_task = await self._execute_task_agent(execution_task_state)
            if completed_task is None:
                return self.state
        else:
            # Old flow: split tasks using LLM
            try:
                task_plan = await self.llm_client.split_tasks(self.state, self.state.plan or "")
            except Exception as exc:
                return self._fail_planning_step(
                    user_message=(
                        "I couldn't prepare executable subtasks from the approved plan, so I "
                        "stopped before touching the repository. Please try again."
                    ),
                    context="RepositoryAgent failed while deriving executable subtasks.",
                    exc=exc,
                )
            task_states: List[TaskAgentState] = []
            for raw_task_item in task_plan:
                task_item = (
                    raw_task_item
                    if isinstance(raw_task_item, TaskPlanItem)
                    else TaskPlanItem.model_validate(raw_task_item)
                )
                task_state = TaskAgentState(
                    repo_agent_id=self.state.repo_agent_id,
                    title=task_item.title,
                    description=task_item.description,
                    scope=task_item.scope,
                )
                completed_task = await self._execute_task_agent(task_state)
                if completed_task is None:
                    return self.state
                task_states.append(completed_task)

        return await self._finalize_execution()

    async def _handle_branch_permission_response(self, text: str) -> RepositoryAgentState:
        if _looks_like_yes(text):
            # Try to extract branch name from the response first
            extracted_name = _extract_branch_name_from_text(text)
            
            if extracted_name:
                # User provided the branch name in their response
                self.state.branch_decision = "create_new"
                self.state.requested_branch_name = extracted_name
                self.state.phase = RepositoryAgentPhase.BRANCH_CONFIRMATION
                self.registry.save_agent_state(self.state)
                self._enqueue_turn(
                    turn_type=TurnType.BRANCH_CONFIRMATION,
                    priority=80,
                    message=f"I'm going to create the branch {extracted_name}. Is that correct?",
                    context="RepositoryAgent is confirming the transcribed branch name before creating it.",
                    requires_user_response=True,
                    metadata={"branch_name": extracted_name},
                )
                return self.state
            
            # No branch name found, ask for it
            self.state.branch_decision = "create_new"
            self.state.phase = RepositoryAgentPhase.BRANCH_NAME
            self.registry.save_agent_state(self.state)
            self._enqueue_turn(
                turn_type=TurnType.BRANCH_NAME,
                priority=80,
                message="Great. What name should I use for the new branch?",
                context="RepositoryAgent is asking for the new branch name.",
                requires_user_response=True,
            )
            return self.state

        if _looks_like_no(text):
            self.state.branch_decision = "use_current"
            self.state.requested_branch_name = None
            self.state.confirmed_branch_name = None
            self.state.branch_created = False
            self.registry.save_agent_state(self.state)
            return await self._start_stepwise_planning()

        self.state.phase = RepositoryAgentPhase.BRANCH_PERMISSION
        self.registry.save_agent_state(self.state)
        self._enqueue_turn(
            turn_type=TurnType.BRANCH_PERMISSION,
            priority=80,
            message=(
                "I am not sure whether you want a new branch. Do you want me to create a new "
                "branch, or should I use the current branch?"
            ),
            context="RepositoryAgent is clarifying the branch creation preference.",
            requires_user_response=True,
        )
        return self.state

    def _handle_branch_name_response(self, text: str) -> RepositoryAgentState:
        normalized_name = _normalize_branch_name(text)
        if not normalized_name:
            self.state.phase = RepositoryAgentPhase.BRANCH_NAME
            self.registry.save_agent_state(self.state)
            self._enqueue_turn(
                turn_type=TurnType.BRANCH_NAME,
                priority=80,
                message="I could not get a valid branch name. What branch name should I use?",
                context="RepositoryAgent needs a valid branch name.",
                requires_user_response=True,
            )
            return self.state

        self.state.requested_branch_name = normalized_name
        self.state.phase = RepositoryAgentPhase.BRANCH_CONFIRMATION
        self.registry.save_agent_state(self.state)
        self._enqueue_turn(
            turn_type=TurnType.BRANCH_CONFIRMATION,
            priority=80,
            message="I'm going to create the branch %s. Is that correct?" % normalized_name,
            context=(
                "RepositoryAgent is confirming the transcribed branch name before creating it."
            ),
            requires_user_response=True,
            metadata={"branch_name": normalized_name},
        )
        return self.state

    async def _handle_branch_confirmation_response(
        self,
        turn: TurnRequest,
        text: str,
    ) -> RepositoryAgentState:
        if _looks_like_no(text):
            self.state.phase = RepositoryAgentPhase.BRANCH_NAME
            self.registry.save_agent_state(self.state)
            self._enqueue_turn(
                turn_type=TurnType.BRANCH_NAME,
                priority=80,
                message="Okay. What branch name should I use instead?",
                context="RepositoryAgent is requesting a corrected branch name.",
                requires_user_response=True,
            )
            return self.state

        if _looks_like_yes(text):
            branch_name = str(turn.metadata.get("branch_name") or self.state.requested_branch_name or "")
            try:
                code, _stdout, stderr = await self.executor.create_branch(self.state.repo_path, branch_name)
                if code != 0:
                    raise RuntimeError(stderr.strip() or "Branch creation failed.")
            except Exception as exc:
                self.state.last_error = str(exc)
                self.state.phase = RepositoryAgentPhase.BRANCH_NAME
                self.registry.save_agent_state(self.state)
                self._enqueue_turn(
                    turn_type=TurnType.BRANCH_NAME,
                    priority=80,
                    message="I couldn't create that branch. Please give me another branch name.",
                    context="RepositoryAgent failed to create the requested branch.",
                    requires_user_response=True,
                )
                return self.state

            self.state.confirmed_branch_name = branch_name
            self.state.branch_name = branch_name
            self.state.branch_created = True
            self.registry.save_agent_state(self.state)
            return await self._start_stepwise_planning()

        normalized_name = _normalize_branch_name(text)
        if normalized_name:
            self.state.requested_branch_name = normalized_name
            self.state.phase = RepositoryAgentPhase.BRANCH_CONFIRMATION
            self.registry.save_agent_state(self.state)
            self._enqueue_turn(
                turn_type=TurnType.BRANCH_CONFIRMATION,
                priority=80,
                message="I'm going to create the branch %s. Is that correct?" % normalized_name,
                context=(
                    "RepositoryAgent is confirming the transcribed branch name before creating it."
                ),
                requires_user_response=True,
                metadata={"branch_name": normalized_name},
            )
            return self.state

        self.state.phase = RepositoryAgentPhase.BRANCH_CONFIRMATION
        self.registry.save_agent_state(self.state)
        self._enqueue_turn(
            turn_type=TurnType.BRANCH_CONFIRMATION,
            priority=80,
            message=(
                "I could not tell whether you confirmed the branch name. Is it correct, or do you want another name?"
            ),
            context="RepositoryAgent is clarifying the branch name confirmation.",
            requires_user_response=True,
            metadata={"branch_name": self.state.requested_branch_name or ""},
        )
        return self.state

    async def _start_stepwise_planning(self) -> RepositoryAgentState:
        self.state.phase = RepositoryAgentPhase.PLANNING
        self.registry.save_agent_state(self.state)

        repo_context = self._build_repo_context()
        self.state.planning_context = repo_context
        memory_context = self.memory_service.render_memory_for_llm(self.state.repo_agent_id).text

        task_goal = self.state.task_goal or self.state.original_user_prompt or ""
        try:
            self.state.requirements = await self.llm_client.extract_requirements(
                task_goal=task_goal,
                acceptance_criteria=self.state.acceptance_criteria,
                repo_context=repo_context,
                memory_context=memory_context,
            )
            self.state.plan = await self.llm_client.create_plan(
                state=self.state,
                repo_context=repo_context,
                memory_context=memory_context,
            )
            self.registry.save_agent_state(self.state)

            task_plan = await self.llm_client.split_tasks(self.state, self.state.plan or "")
        except Exception as exc:
            return self._fail_planning_step(
                user_message=(
                    "I couldn't turn that request into a usable step-by-step plan, so I stopped "
                    "before making changes. Please try again once the planning output is valid."
                ),
                context="RepositoryAgent failed while generating the reviewable task plan.",
                exc=exc,
            )
        plan_steps = []
        for idx, raw_task_item in enumerate(task_plan):
            task_item = (
                raw_task_item
                if isinstance(raw_task_item, TaskPlanItem)
                else TaskPlanItem.model_validate(raw_task_item)
            )
            plan_steps.append(
                {
                    "index": idx,
                    "title": task_item.title,
                    "description": task_item.description,
                    "scope": task_item.scope or [],
                    "status": "PROPOSED",
                    "user_feedback": [],
                }
            )

        if not plan_steps:
            raise RuntimeError("Planning agent did not return any reviewable plan steps.")

        self.state.plan_steps = plan_steps
        self.state.current_plan_step_index = 0
        self.state.execution_approved = False
        self.state.phase = RepositoryAgentPhase.PLAN_STEP_REVIEW
        self.registry.save_agent_state(self.state)

        if plan_steps:
            first_step = plan_steps[0]
            scope_info = (
                f" This will primarily work with {_format_files_for_voice(first_step['scope'])}."
                if first_step.get('scope')
                else ""
            )
            message = (
                f"Let me walk you through the plan step by step. "
                f"Step 1 would be to {first_step['title']}. "
                f"{first_step['description']}{scope_info} "
                f"What do you think? Feel free to ask questions, request changes, or say approve to proceed."
            )
            self._enqueue_turn(
                turn_type=TurnType.PLAN_STEP_REVIEW,
                priority=70,
                message=message,
                context="RepositoryAgent is asking the user to review the first plan step.",
                requires_user_response=True,
                metadata={"step_index": 0},
            )
        else:
            self.state.phase = RepositoryAgentPhase.WAITING_EXECUTION_APPROVAL
            self.registry.save_agent_state(self.state)
            self._enqueue_turn(
                turn_type=TurnType.EXECUTION_APPROVAL,
                priority=80,
                message="No plan steps were generated. Do you want me to proceed with the task?",
                context="RepositoryAgent is waiting for execution approval after empty plan.",
                requires_user_response=True,
            )

        return self.state

    async def _handle_plan_step_review(self, turn: TurnRequest, text: str) -> RepositoryAgentState:
        step_index = turn.metadata.get("step_index", self.state.current_plan_step_index)
        
        if step_index >= len(self.state.plan_steps):
            step_index = len(self.state.plan_steps) - 1
        
        if _looks_like_approval(text):
            if step_index < len(self.state.plan_steps):
                self.state.plan_steps[step_index]["status"] = "APPROVED"
            
            self.state.current_plan_step_index = step_index + 1
            self.registry.save_agent_state(self.state)
            
            if self.state.current_plan_step_index < len(self.state.plan_steps):
                next_step = self.state.plan_steps[self.state.current_plan_step_index]
                step_num = self.state.current_plan_step_index + 1
                scope_info = (
                    f" This will primarily work with {_format_files_for_voice(next_step['scope'])}."
                    if next_step.get('scope')
                    else ""
                )
                message = (
                    f"Great! Moving on to the next step. "
                    f"Step {step_num} would be to {next_step['title']}. "
                    f"{next_step['description']}{scope_info} "
                    f"What do you think about this step? Ask any questions, or say approve to continue."
                )
                self._enqueue_turn(
                    turn_type=TurnType.PLAN_STEP_REVIEW,
                    priority=70,
                    message=message,
                    context="RepositoryAgent is asking the user to review the next plan step.",
                    requires_user_response=True,
                    metadata={"step_index": self.state.current_plan_step_index},
                )
                self.state.phase = RepositoryAgentPhase.PLAN_STEP_REVIEW
                self.registry.save_agent_state(self.state)
            else:
                self.state.phase = RepositoryAgentPhase.WAITING_EXECUTION_APPROVAL
                self.registry.save_agent_state(self.state)
                self._enqueue_turn(
                    turn_type=TurnType.EXECUTION_APPROVAL,
                    priority=80,
                    message="All plan steps are approved. Do you want me to execute the plan now?",
                    context="RepositoryAgent is waiting for final execution approval.",
                    requires_user_response=True,
                )
            return self.state
        else:
            # Non-approval response: classify intent (question vs revision)
            if step_index < len(self.state.plan_steps):
                current_step = TaskPlanItem(
                    title=self.state.plan_steps[step_index].get("title", "Task"),
                    description=self.state.plan_steps[step_index].get("description", ""),
                    scope=self.state.plan_steps[step_index].get("scope", []),
                )
                
                # Classify user intent
                try:
                    intent = await self.llm_client.classify_user_intent(text, current_step)
                except Exception:
                    # Fallback: assume question if classification fails
                    intent = "QUESTION"
                
                repo_context = self._build_repo_context()
                memory_context = self.memory_service.render_memory_for_llm(
                    self.state.repo_agent_id
                ).text
                
                if intent == "QUESTION":
                    # Handle as conversational discussion - no revision
                    try:
                        discussion_response = await self.llm_client.discuss_plan_step(
                            state=self.state,
                            current_step=current_step,
                            user_question=text,
                            repo_context=repo_context,
                            memory_context=memory_context,
                        )
                    except Exception as exc:
                        # Fallback response if LLM fails
                        discussion_response = (
                            f"Let me clarify this step for you. "
                            f"This is about {current_step.title}. "
                            f"{current_step.description} "
                            f"This step will work with {_format_files_for_voice(current_step.scope) if current_step.scope else 'general codebase changes'}. "
                            f"Feel free to ask more questions, or say approve when ready to proceed."
                        )
                    
                    step_num = step_index + 1
                    # Enqueue discussion message without changing the step
                    self._enqueue_turn(
                        turn_type=TurnType.PLAN_STEP_REVIEW,
                        priority=70,
                        message=discussion_response,
                        context=f"RepositoryAgent is discussing step {step_num} with the user.",
                        requires_user_response=True,
                        metadata={"step_index": step_index},
                    )
                    self.registry.save_agent_state(self.state)
                    return self.state
                else:
                    # Handle as revision request
                    self.state.plan_steps[step_index]["user_feedback"].append(text)
                    try:
                        revised_step = await self.llm_client.revise_plan_step(
                            state=self.state,
                            current_step=current_step,
                            user_feedback=text,
                            repo_context=repo_context,
                            memory_context=memory_context,
                        )
                        if not isinstance(revised_step, TaskPlanItem):
                            revised_step = TaskPlanItem.model_validate(revised_step)
                    except Exception as exc:
                        return self._fail_planning_step(
                            user_message=(
                                "I couldn't revise that plan step because the generated planning output "
                                "was not usable. Please try again."
                            ),
                            context="RepositoryAgent failed while revising a plan step.",
                            exc=exc,
                        )
                    self.state.plan_steps[step_index]["title"] = revised_step.title
                    self.state.plan_steps[step_index]["description"] = revised_step.description
                    self.state.plan_steps[step_index]["scope"] = revised_step.scope
                    self.state.plan_steps[step_index]["status"] = "PROPOSED"
                    
                    self.registry.save_agent_state(self.state)
                    
                    step_num = step_index + 1
                    scope_text = f" The scope includes {_format_files_for_voice(revised_step.scope)}" if revised_step.scope else ""
                    message = (
                        f"I've updated step {step_num} based on your feedback. "
                        f"The revised step {step_num} is to {revised_step.title}. "
                        f"{revised_step.description}{scope_text}. "
                        f"The changes incorporate your request to {text}. "
                        f"Does this revised approach work for you? Feel free to ask questions or request further changes, "
                        f"or say approve to proceed."
                    )
                    self._enqueue_turn(
                        turn_type=TurnType.PLAN_STEP_REVIEW,
                        priority=70,
                        message=message,
                        context="RepositoryAgent is asking the user to review the updated plan step.",
                        requires_user_response=True,
                        metadata={"step_index": step_index},
                    )
                    self.state.phase = RepositoryAgentPhase.PLAN_STEP_REVIEW
                    self.registry.save_agent_state(self.state)
                    return self.state
            
            # Fallback if step_index is invalid
            self.registry.save_agent_state(self.state)
            return self.state

    async def _handle_execution_approval(self, text: str) -> RepositoryAgentState:
        if _looks_like_approval(text):
            self.state.execution_approved = True
            self.registry.save_agent_state(self.state)
            return await self.execute_approved_plan()
        else:
            self.state.phase = RepositoryAgentPhase.PLAN_STEP_REVIEW
            self.state.current_plan_step_index = 0
            self.registry.save_agent_state(self.state)
            first_step_title = (
                self.state.plan_steps[0].get("title", "N/A") if self.state.plan_steps else "N/A"
            )
            self._enqueue_turn(
                turn_type=TurnType.PLAN_STEP_REVIEW,
                priority=70,
                message=(
                    f"Understood. Let's review the plan steps again. Step 1: {first_step_title}. "
                    "Does this look good?"
                ),
                context="RepositoryAgent is restarting plan step review after execution rejection.",
                requires_user_response=True,
                metadata={"step_index": 0},
            )
            return self.state

    def _handle_plan_rejection(self, feedback: str) -> RepositoryAgentState:
        self.state.phase = RepositoryAgentPhase.INTAKE
        self.registry.save_agent_state(self.state)
        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.INTAKE,
                priority=100,
                message="Plan rejected. Add the missing requirements or clarifications.",
                context=feedback,
                requires_user_response=True,
            )
        )
        return self.state

    def _enqueue_turn(
        self,
        turn_type: TurnType,
        priority: int,
        message: str,
        context: str,
        requires_user_response: bool,
        metadata: Optional[dict] = None,
    ) -> TurnRequest:
        turn = TurnRequest(
            user_id=self.state.user_id,
            agent_id=self.state.repo_agent_id,
            repo_agent_id=self.state.repo_agent_id,
            type=turn_type,
            priority=priority,
            message=message,
            context=context,
            requires_user_response=requires_user_response,
            metadata=metadata or {},
        )
        self.manager.enqueue_turn(turn)
        return turn

    def _build_execution_task(self, approved_steps: List[dict]) -> TaskAgentState:
        aggregated_scope = _merge_plan_step_scope(approved_steps)
        repo_files = self.executor.list_files(self.state.repo_path, max_files=400)
        capability_summary = _summarize_repo_capabilities(repo_files)
        creation_allowed = _goal_allows_new_files(self.state.task_goal or self.state.original_user_prompt or "")
        brief_sections = [
            "Implementation brief for the approved repository change.",
            "Primary goal:\n%s" % (self.state.task_goal or self.state.original_user_prompt or "Implement the approved change."),
        ]
        if self.state.requirements:
            brief_sections.append(
                "Requirements:\n%s" % "\n".join("- %s" % item for item in self.state.requirements)
            )
        if approved_steps:
            brief_sections.append(
                "Approved plan steps:\n%s"
                % "\n".join(
                    "%s. %s - %s"
                    % (
                        index + 1,
                        step.get("title", "Step"),
                        step.get("description", ""),
                    )
                    for index, step in enumerate(approved_steps)
                )
            )
        if aggregated_scope:
            brief_sections.append(
                "Focus paths from the approved plan:\n%s"
                % "\n".join("- %s" % item for item in aggregated_scope)
            )
        if capability_summary:
            brief_sections.append("Repository capability summary:\n%s" % capability_summary)
        brief_sections.append(
            "Execution guidance:\n"
            "- Treat the approved inspection and design steps as already-resolved context.\n"
            "- This phase is for implementing the approved change in code.\n"
            "- Ground your implementation in the real repository files and the detected stack.\n"
            "- If you still need repository details, request specific files through needed_files.\n"
            "- You may create new files when the requested feature has no existing target file.\n"
            "- Prefer extending an existing surface when one exists.\n"
            "- If no matching UI/template/static surface exists but the task explicitly asks for a new page, stylesheet, endpoint, or other new feature surface, create the smallest viable grounded entrypoint consistent with the detected stack instead of stopping."
        )
        brief_sections.append(
            "File creation policy:\n"
            "- Creation allowed: %s\n"
            "- Do not invent unrelated frameworks or product structure.\n"
            "- If the repo already indicates a web stack, integrate there.\n"
            "- If the repo has no existing web surface and the request is explicitly for a new HTML/CSS or docs page, prefer a minimal standalone surface such as docs/ or static/ unless existing server files indicate a better integration point."
            % ("yes" if creation_allowed else "no, unless it is required to complete the approved change")
        )
        return TaskAgentState(
            repo_agent_id=self.state.repo_agent_id,
            title="Implement approved repository change",
            description="\n\n".join(section for section in brief_sections if section.strip()),
            scope=[],
        )

    async def _execute_task_agent(self, task_state: TaskAgentState) -> Optional[TaskAgentState]:
        self.registry.save_task_state(task_state)
        self.state.task_agents.append(task_state.task_agent_id)
        self.registry.save_agent_state(self.state)

        task_agent = TaskAgent(
            state=task_state,
            registry=self.registry,
            executor=self.executor,
            llm_client=self.llm_client,
            memory_service=self.memory_service,
            graph_checkpointer=self.graph_checkpointer,
        )
        completed_task = await task_agent.execute(self.state)
        self.state.changed_files.extend(
            item for item in completed_task.changed_files if item not in self.state.changed_files
        )
        self.state.test_results.extend(completed_task.test_results)
        if completed_task.status == TaskAgentStatus.FAILED:
            self.state.phase = RepositoryAgentPhase.FAILED
            self.state.last_error = completed_task.last_error
            self.registry.save_agent_state(self.state)
            self.manager.emit_failed(
                self.state.repo_agent_id,
                completed_task.last_error or "Task agent failed.",
            )
            return None
        return completed_task

    async def _finalize_execution(self) -> RepositoryAgentState:
        self.state.phase = RepositoryAgentPhase.FINALIZING
        self.registry.save_agent_state(self.state)
        all_task_states = [
            task
            for task_id in self.state.task_agents
            for task in [self.registry.persistence.get_task_agent(task_id)]
            if task is not None
        ]
        self.state.final_report = await self.llm_client.final_report(self.state, all_task_states)
        self.state.phase = RepositoryAgentPhase.DONE
        self.registry.save_agent_state(self.state)
        self.memory_service.record_task_completed(self.state, all_task_states)

        for task_state in all_task_states:
            task_agent = TaskAgent(
                state=task_state,
                registry=self.registry,
                executor=self.executor,
                llm_client=self.llm_client,
                memory_service=self.memory_service,
                graph_checkpointer=self.graph_checkpointer,
            )
            task_agent.mark_dead()

        completion_message = (
            f"{self.state.final_report}\n\nYou can review the changes in the desktop app."
            if self.state.final_report
            else "I've completed the task. You can review the changes in the desktop app."
        )
        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.COMPLETION,
                priority=40,
                message=completion_message,
                context="RepositoryAgent final report.",
                requires_user_response=False,
            )
        )
        self.manager.emit_completed(self.state.repo_agent_id, "Execution completed.")
        return self.state

    def _fail_planning_step(
        self,
        user_message: str,
        context: str,
        exc: Exception,
    ) -> RepositoryAgentState:
        self.manager.release_intake_lock(self.state.repo_agent_id)
        self.state.phase = RepositoryAgentPhase.FAILED
        self.state.last_error = str(exc)
        self.registry.save_agent_state(self.state)
        self._enqueue_turn(
            turn_type=TurnType.COMPLETION,
            priority=40,
            message=user_message,
            context="%s Error: %s" % (context, exc),
            requires_user_response=False,
        )
        return self.state

    def _build_repo_context(self) -> str:
        files = self.executor.list_files(self.state.repo_path, max_files=1200)
        text_chunks = [
            self.state.task_goal or "",
            self.state.original_user_prompt or "",
            " ".join(self.state.requirements or []),
            " ".join(self.state.acceptance_criteria or []),
        ]
        context_files = select_context_files(text_chunks, files, limit=160)
        candidate_files = pick_candidate_files(text_chunks, context_files, limit=10)
        file_contents = build_file_content_sections(
            repo_path=self.state.repo_path,
            files=candidate_files,
            read_file=self.executor.read_file,
            max_files=10,
            max_chars=5000,
            max_lines=140,
        )

        sections = [
            "Repository capability summary:\n%s" % summarize_repo_files(context_files),
            "Visible files:\n%s" % "\n".join("- %s" % item for item in context_files[:160]),
            "Repository tree:\n%s" % render_repo_tree(context_files[:160]),
        ]
        if file_contents:
            sections.append("Initial planning file contents:\n%s" % file_contents)
        return "\n\n".join(section for section in sections if section.strip())


def _looks_like_approval(response: str) -> bool:
    normalized = _normalize_short_response(response)
    approvals = {
        "yes",
        "yeah",
        "yep",
        "y",
        "sure",
        "ok",
        "okay",
        "approved",
        "approve",
        "go ahead",
        "looks good",
        "sounds good",
        "do it",
        "proceed",
        "continue",
        "ship it",
        "si",
        "sí",
        "vale",
        "dale",
        "its ok",
        "it's ok",
        "thats ok",
        "that's ok",
        "fine",
        "works for me",
        "all good",
    }
    # Exact match or starts with approve
    if normalized in approvals or normalized.startswith("approve"):
        return True
    # Check if any approval keyword is in the response
    return any(item in normalized for item in approvals if len(item) > 2)


def _merge_plan_step_scope(plan_steps: List[dict]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for step in plan_steps:
        for item in step.get("scope", []) or []:
            normalized = str(item).strip().strip("/")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _goal_allows_new_files(goal: str) -> bool:
    normalized = (goal or "").lower()
    creation_terms = (
        "create ",
        "build ",
        "add a page",
        "add page",
        "new page",
        "landing page",
        "html",
        "css",
        "stylesheet",
        "endpoint",
        "websocket",
        "template",
        "static page",
        "docs page",
        "view",
        "screen",
    )
    return any(term in normalized for term in creation_terms)


def _summarize_repo_capabilities(files: List[str]) -> str:
    if not files:
        return "- No repository files were listed."

    lowered = [path.lower() for path in files]
    frontend_files = [
        path for path in files
        if path.lower().endswith((".html", ".css", ".scss", ".tsx", ".jsx", ".ts", ".js"))
        or any(segment in path.lower() for segment in ("/src/", "/pages/", "/components/", "/public/", "/templates/", "/static/"))
    ]
    python_files = [path for path in files if path.lower().endswith(".py")]
    docs_files = [path for path in files if path.lower().startswith("docs/") or path.lower().endswith(".md")]
    package_files = [path for path in files if path.lower().endswith(("package.json", "vite.config.ts", "vite.config.js"))]
    requirements_files = [path for path in files if path.lower().endswith(("requirements.txt", "pyproject.toml", "poetry.lock"))]
    fastapi_files = [path for path in files if path.lower().endswith(".py") and any(name in path.lower() for name in ("main.py", "app.py", "server.py"))]
    template_dirs = [path for path in files if any(segment in path.lower() for segment in ("/templates/", "/static/"))]

    lines = [
        "- Repository file sample size: %s" % len(files),
        "- Frontend/template/static files detected: %s" % ("yes" if frontend_files else "no"),
        "- Python application files detected: %s" % ("yes" if python_files else "no"),
        "- Package or Vite-style frontend markers detected: %s" % ("yes" if package_files else "no"),
        "- Python dependency markers detected: %s" % ("yes" if requirements_files else "no"),
    ]
    if frontend_files:
        lines.append(
            "- Example frontend or presentation files: %s"
            % ", ".join(frontend_files[:5])
        )
    if template_dirs:
        lines.append(
            "- Example template/static paths: %s"
            % ", ".join(template_dirs[:5])
        )
    if fastapi_files:
        lines.append(
            "- Example Python app entry files: %s"
            % ", ".join(fastapi_files[:5])
        )
    elif python_files:
        lines.append(
            "- Example Python files: %s"
            % ", ".join(python_files[:5])
        )
    if docs_files:
        lines.append(
            "- Example docs or markdown files: %s"
            % ", ".join(docs_files[:5])
        )
    if not frontend_files and python_files:
        lines.append(
            "- If a new UI surface is required and no existing web surface is present, prefer the smallest grounded addition rather than assuming an entire framework."
        )
    return "\n".join(lines)
def _looks_like_yes(text: str) -> bool:
    normalized = _normalize_short_response(text)
    positives = {
        "yes",
        "yeah",
        "yep",
        "sure",
        "go ahead",
        "looks good",
        "sounds good",
        "create a branch",
        "create one",
        "make a branch",
        "make a new branch",
        "new branch",
        "use a new branch",
        "yes create it",
        "yes please",
        "please create a branch",
        "si",
        "sí",
        "y",
        "ok",
        "okay",
        "vale",
        "crea una rama",
        "nueva rama",
        "branch nueva",
        "haz una nueva",
    }
    return normalized in positives or any(item in normalized for item in positives if len(item) > 3)


def _looks_like_no(text: str) -> bool:
    normalized = _normalize_short_response(text)
    negatives = {
        "no",
        "nope",
        "don't",
        "do not",
        "don't create one",
        "do not create a branch",
        "use current",
        "use the current branch",
        "current branch",
        "same branch",
        "keep current",
        "keep the current branch",
        "no need",
        "not necessary",
        "without a branch",
        "actual",
        "rama actual",
        "branch actual",
        "sin rama",
        "no hace falta",
        "usa la actual",
    }
    return normalized in negatives or any(item in normalized for item in negatives if len(item) > 3)


def _extract_branch_name_from_text(text: str) -> str:
    """Extract branch name from phrases like 'create a branch called photobooth' or 'branch name is feature-x'."""
    lower_text = text.lower().strip()
    
    # Patterns to match branch name extraction
    patterns = [
        r"branch called ([\w-]+)",
        r"branch named ([\w-]+)",
        r"call it ([\w-]+)",
        r"name it ([\w-]+)",
        r"called ([\w-]+)",
        r"named ([\w-]+)",
        r"branch name is ([\w-]+)",
        r"branch name ([\w-]+)",
        r"create ([\w-]+) branch",
        r"make ([\w-]+) branch",
        r"rama llamada ([\w-]+)",
        r"rama ([\w-]+)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, lower_text)
        if match:
            candidate = match.group(1)
            # Don't return common words that aren't branch names
            if candidate not in {"a", "the", "new", "it", "one", "branch"}:
                return _normalize_branch_name(candidate)
    
    return ""


def _format_files_for_voice(file_paths: List[str]) -> str:
    """Convert file paths to natural voice-friendly descriptions using just filenames.
    
    Examples:
        ['app/services/openai_client.py'] -> 'openai_client.py'
        ['app/agents/repo.py', 'app/models/task.py'] -> 'repo.py and task.py'
        ['*.py'] -> 'Python files'
    """
    if not file_paths:
        return "the codebase"
    
    descriptions = []
    for path in file_paths[:5]:  # Limit to first 5 for voice brevity
        # Skip empty or meaningless patterns
        if not path or path in ['*', '**', '.']:
            continue
            
        # Clean up path by removing ** and * for analysis
        clean_path = path.replace('**/', '').replace('/**', '').replace('**', '')
        path_obj = Path(clean_path)
        
        # Handle wildcards
        if '*' in path:
            # Determine file type from extension
            if '*.py' in path:
                file_type = "Python files"
            elif '*.ts' in path or '*.tsx' in path:
                file_type = "TypeScript files"
            elif '*.js' in path or '*.jsx' in path:
                file_type = "JavaScript files"
            else:
                file_type = "files"
            
            descriptions.append(file_type)
            continue
        
        # Regular file path - just use filename.extension
        full_name = path_obj.name  # Filename with extension
        
        # Skip if we couldn't extract a meaningful name
        if not full_name or full_name in ['*', '**']:
            continue
        
        descriptions.append(full_name)
    
    # If we filtered everything out, return generic
    if not descriptions:
        return "various files in the codebase"
    
    # Handle cases with many files
    if len(file_paths) > 5:
        descriptions.append(f"and {len(file_paths) - 5} other files")
    
    # Join naturally
    if len(descriptions) == 1:
        return descriptions[0]
    elif len(descriptions) == 2:
        return f"{descriptions[0]} and {descriptions[1]}"
    else:
        return ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"


def _normalize_branch_name(text: str) -> str:
    normalized = _normalize_short_response(text).strip("\"'")
    normalized = normalized.replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9._/-]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    normalized = re.sub(r"/{2,}", "/", normalized)
    normalized = normalized.strip("-./")
    if normalized in {
        "si",
        "yes",
        "yeah",
        "yep",
        "no",
        "nope",
        "ok",
        "okay",
        "sure",
        "vale",
        "go-ahead",
    }:
        return ""
    return normalized


def _normalize_short_response(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("’", "'")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _format_list(items: List[str]) -> str:
    if not items:
        return "- Not provided"
    return "\n".join("- %s" % item for item in items)
