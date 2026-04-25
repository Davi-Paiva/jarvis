# Jarvis Backend Agents

This backend implements the local orchestration core for Jarvis. The first HTTP
route is `POST /folder`, and future API adapters should keep calling
`JarvisOrchestrator` instead of duplicating domain logic.

## Main Flow

1. Create an orchestrator with `app.main.create_orchestrator()`.
2. Or start the HTTP app from `app.main:app` and call `POST /folder` to
   activate a local repository.
3. Call `start_task(repo_agent_id, message, acceptance_criteria)` to begin
   intake and planning.
4. Read the next visible turn with `get_next_turn()`.
5. Approve or reject with `submit_user_response(turn_id, response, approved)`.
6. On approval, the repository agent creates temporary task agents, executes the
   approved plan, finalizes, writes memory, and enqueues a completion turn.

## Important Modules

- `app/api/routes.py`: thin FastAPI transport with `POST /folder`.
- `app/services/orchestrator.py`: public facade for future endpoints.
- `app/services/global_manager.py`: deterministic turn/event coordinator.
- `app/services/turn_scheduler.py`: priority queue and intake lock rules.
- `app/services/repository_registry.py`: repository and agent state registry.
- `app/services/memory_service.py`: structured Markdown memory renderer and
  compactor.
- `app/services/local_executor.py`: only layer allowed to touch filesystem, git
  or commands.
- `app/agents/repository_agent.py`: intake, planning, approval, execution and
  finalization flow.
- `app/agents/task_agent.py`: temporary subtask worker.
- `app/graphs/*.py`: optional LangGraph state-machine shape. If LangGraph is
  unavailable, the backend still runs with the deterministic Python flow.

## Memory

The backend uses two memory layers:

- Operational memory in SQLite at `JARVIS_DB_PATH`, storing repository agents,
  task agents, turns and manager events. When LangGraph checkpoint packages are
  installed, the graph builders also receive a SQLite checkpointer backed by the
  same path.
- Human-readable Markdown memory at `JARVIS_MEMORY_DIR`, one structured file per
  repository agent. It stores compact reusable context: summary, preferences,
  conventions, learnings, useful commands, active decisions, risks and completed
  task summaries.

LLM calls do not own hidden memory. Each intelligent step receives the current
state, repository context and a bounded rendered memory view from
`MemoryService.render_memory_for_llm(...)`, not the full Markdown file when it
gets large.

The active Markdown file uses stable front matter and fixed sections:

```md
---
repo_agent_id: repo_agent_123
repo_id: repo_abc
user_id: demo
memory_version: 1
last_updated: 2026-04-25T18:30:00Z
---

# Repository Memory

## Current Summary
## User Preferences
## Active Conventions
## Repository Learnings
## Useful Commands
## Active Decisions
## Known Risks
## Completed Tasks
```

`MemoryService` filters large logs, patches, stdout/stderr blobs and obvious
secrets from Markdown. SQLite remains the complete operational/audit record.
If the active Markdown grows past `JARVIS_MEMORY_MAX_CHARS`, older completed
tasks are archived under `JARVIS_MEMORY_DIR/archive/`.

## GlobalManager Calls

Agents never talk directly to UI or future API routes. They enqueue `TurnRequest`
objects through `GlobalManager.enqueue_turn(...)`.

`GlobalManager` decides the visible turn using:

- `intake_lock_agent_id`, so active intake cannot be interrupted.
- Higher priority first.
- Older turn first when priorities match.

User responses enter through `JarvisOrchestrator.submit_user_response(...)`,
which records the response in `GlobalManager` and resumes the correct
repository agent.

## HTTP Activation

Run the backend with:

```bash
uvicorn app.main:app --reload
```

The first endpoint is:

```http
POST /folder
Content-Type: application/json
```

Request body:

```json
{
  "repo_path": "/absolute/path/to/repo",
  "display_name": "Optional Repo Name",
  "branch_name": "optional-branch"
}
```

Response body:

```json
{
  "repo_agent_id": "repo_agent_123",
  "repo_id": "repo_abc",
  "thread_id": "repo_agent:repo_agent_123",
  "phase": "INTAKE"
}
```

Status codes:

- `201` if the repository agent is created for the first time.
- `200` if the same folder was already activated and the existing agent is reused.
- `400` if the path does not exist or is not a directory.
- `403` if the path is outside `JARVIS_ALLOWED_REPO_ROOTS`.

## Voice Websocket

`jarvis-web` now connects directly to `WS /ws` on the backend. The websocket is
the voice/session transport for local development and does not pass through the
desktop app.

Client messages:

- `SESSION_START`: creates or resumes a local voice session.
- `USER_TRANSCRIPT`: sends a spoken utterance with optional `sessionId`,
  `repoAgentId` and `turnId`.

Server messages:

- `SESSION_STATE`: current voice session state, active repo, active chat,
  active repo summary, pending turns and active chat history.
- `CHAT_MESSAGE`: persisted user/assistant/system message from the active chat.
- `AI_RESPONSE`: short spoken response for TTS playback, optionally including
  pre-synthesized audio from ElevenLabs.
- `PENDING_TURN`: summary of a pending approval or blocking question.

The backend uses `VoiceSessionService` as the adapter between websocket traffic
and `JarvisOrchestrator`. It handles:

- active repository switching by voice
- one active chat per repository
- repository activation by name inside `JARVIS_ALLOWED_REPO_ROOTS`
- approval routing to `submit_user_response(...)`
- cross-repo pending-turn notifications with "switch repo?" confirmation

`GlobalManager` also keeps in-memory realtime listeners so websocket sessions
receive approvals, blocking questions and completion notifications as soon as
other repository agents emit them.

## LocalExecutor Safety

`LocalExecutor` validates that all filesystem paths stay under the repository
and under `JARVIS_ALLOWED_REPO_ROOTS`. It rejects absolute paths, path traversal
and symlink escapes.

Writes and git branch creation are serialized with one async lock per
repository. Commands are executed with `shell=False` and must match
`JARVIS_ALLOWED_COMMANDS`.

## Environment For Local Testing

Create a `.env` in the directory where you run the backend:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini
JARVIS_ENV=local
JARVIS_USER_ID=demo
JARVIS_DATA_DIR=./data
JARVIS_DB_PATH=./data/jarvis.db
JARVIS_MEMORY_DIR=./data/memory
JARVIS_MEMORY_MAX_CHARS=30000
JARVIS_MEMORY_VIEW_MAX_CHARS=12000
JARVIS_MEMORY_MAX_COMPLETED_TASKS=12
JARVIS_ALLOWED_REPO_ROOTS=/Users/joanvm/Desktop/Projects
JARVIS_ALLOWED_COMMANDS=pytest,npm test,npm run test,npm run build,git status,git diff
LOG_LEVEL=INFO
```

`OPENAI_API_KEY` is optional for unit tests because they use `FakeLLMClient`.
For the demo with real model calls, set it before creating the orchestrator.

## Minimal Python Usage

```python
import asyncio

from app.main import create_orchestrator


async def main():
    orchestrator = create_orchestrator()
    agent = await orchestrator.create_repo_agent("/path/to/repo")
    result = await orchestrator.start_task(
        agent.repo_agent_id,
        "Explain and safely improve the selected repository",
        ["No auth work", "Keep changes scoped"],
    )
    approval_turn = result.next_turn
    await orchestrator.submit_user_response(
        approval_turn.id,
        "approved",
        approved=True,
    )
    memory_view = await orchestrator.get_memory_view(agent.repo_agent_id)
    print(memory_view.text)


asyncio.run(main())
```

## Tests

Run from `jarvis-backend`:

```bash
python -m pytest
```

The tests use temporary repositories and `FakeLLMClient`, so they do not need
network access or an OpenAI key.
