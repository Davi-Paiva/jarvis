# Jarvis Backend - Contexto para Agente de IA

## 1. Alcance y objetivo
Este documento resume el contexto tecnico mas importante de jarvis-backend para que un agente de IA pueda:
- entender la arquitectura real,
- navegar los puntos de entrada,
- respetar las restricciones de seguridad,
- y modificar el sistema sin romper los flujos principales.

## 2. Arquitectura general (capas)
- API/Transport: FastAPI HTTP + WebSocket.
- Orquestacion: JarvisOrchestrator como facade principal.
- Coordinacion de turnos/eventos: GlobalManager + TurnScheduler.
- Estado y persistencia: RepositoryRegistry + SQLitePersistence.
- Ejecucion local segura: LocalExecutor (filesystem/git/comandos).
- Memoria: MemoryService (Markdown estructurado) + SQLite (registro operacional).
- Agentes: RepositoryAgent (macroflujo) + TaskAgent (subtareas).
- Voz: VoiceSessionService + protocolo de mensajes de voz.

## 3. Puntos de entrada importantes
- App FastAPI: app/main.py
  - create_orchestrator(...)
  - create_app(...)
  - app = create_app()
- HTTP:
  - POST /folder en app/api/routes.py
- WebSocket de voz:
  - WS /ws en app/api/voice_ws.py

## 4. Estructuras de datos mas importantes

### 4.1 Estado de agentes y fases
- app/models/state.py
  - RepositoryAgentPhase:
    - INTAKE, PLANNING, WAITING_APPROVAL, EXECUTING, WAITING_FOR_USER, FINALIZING, DONE, FAILED
  - TaskAgentStatus:
    - CREATED, INSPECTING, WORKING, WAITING_FOR_USER, VALIDATING, DONE, FAILED, DEAD

### 4.2 Repositorio y agentes
- app/models/repository.py
  - RepositoryRecord:
    - repo_id, user_id, repo_path, display_name, created_at
  - RepositoryAgentState:
    - repo_agent_id, repo_id, repo_path, branch_name, phase, thread_id
    - task_goal, requirements, acceptance_criteria, plan
    - task_agents, changed_files, test_results
    - final_report, last_error, created_at, updated_at

### 4.3 Tareas
- app/models/task.py
  - TaskPlanItem:
    - title, description, scope
  - TaskAgentState:
    - task_agent_id, repo_agent_id, title, description, scope
    - status, proposed_patch, changed_files, test_results
    - blocking_question, result_summary, last_error

### 4.4 Turnos y respuestas de usuario
- app/models/turns.py
  - TurnType: INTAKE, BLOCKING_QUESTION, APPROVAL, COMPLETION, PROGRESS
  - TurnRequest:
    - id, user_id, agent_id, repo_agent_id, type, priority
    - message, context, requires_user_response, handled, metadata
  - TurnResponse:
    - turn_id, response, approved, metadata

### 4.5 Eventos de manager
- app/models/events.py
  - ManagerEventType:
    - turn.created, user_response.received, agent.progress, approval.required, agent.completed, agent.failed
  - ManagerEvent:
    - id, type, repo_agent_id, task_agent_id, turn_id, message, payload, created_at

### 4.6 Chat y sesion de voz
- app/models/chat.py
  - ChatSession: chat_id, repo_agent_id, status(active/closed), title, timestamps
  - ChatMessage: message_id, chat_id, repo_agent_id, role(user/assistant/system), content, turn_id
- app/models/voice_protocol.py
  - Cliente -> servidor:
    - SESSION_START, USER_TRANSCRIPT
  - Servidor -> cliente:
    - SESSION_STATE, CHAT_MESSAGE, AI_RESPONSE, PENDING_TURN
    - AUDIO_STREAM_START, AUDIO_STREAM_CHUNK, AUDIO_STREAM_END

### 4.7 Memoria estructurada
- app/models/memory.py
  - MemoryFrontMatter
  - RepositoryMemory (secciones de memoria)
  - CompletedTaskMemory (resumen reutilizable por tarea)
  - RenderedMemoryView (texto truncado para LLM)

## 5. Flujos principales

### 5.1 Activacion de repositorio (HTTP)
1. Cliente llama POST /folder con repo_path (+ opcional display_name, branch_name).
2. routes.activate_folder() usa orchestrator.activate_repo_agent(...).
3. RepositoryRegistry valida path y roots permitidas.
4. Si ya existe agente para ese repo: retorna 200.
5. Si es nuevo: crea RepositoryRecord + RepositoryAgentState + memoria inicial, retorna 201.

### 5.2 Flujo de tarea principal (RepositoryAgent)
1. start_task(...):
   - adquiere intake lock,
   - guarda objetivo y criterios,
   - extrae requirements y plan via LLMClient,
   - pasa a WAITING_APPROVAL,
   - encola TurnRequest de tipo APPROVAL.
2. submit_user_response(...):
   - GlobalManager marca turn handled,
   - RepositoryAgent.handle_user_response(...).
3. Si aprobado:
   - execute_approved_plan():
     - split_tasks(...)
     - crea TaskAgent por subtask
     - ejecuta subtareas
     - agrega changed_files/test_results
     - si falla subtask -> phase FAILED + emit_failed
     - si todo ok -> final_report + phase DONE + completion turn
4. Si rechazado:
   - vuelve a INTAKE y encola turno de aclaraciones.

### 5.3 Flujo de subtarea (TaskAgent)
1. INSPECTING: construye contexto de repo filtrado por scope.
2. WORKING: LLM implement_task(...).
3. Si hay patch: LocalExecutor.apply_patch(...).
4. VALIDATING: run_allowed_command(...) si hay test_command.
5. DONE o FAILED.
6. Cuando termina repositorio completo, los task agents se marcan DEAD.

### 5.4 Flujo de turnos y eventos (GlobalManager)
1. enqueue_turn(...) guarda turno y emite evento.
2. get_next_turn(...) selecciona por prioridad y created_at.
3. intake_lock_agent_id restringe el siguiente turno al repo en intake.
4. record_user_response(...) marca handled y emite user_response.received.
5. listeners en memoria reciben eventos realtime (usado por WS).

### 5.5 Flujo de voz (WS /ws + VoiceSessionService)
1. Cliente abre WS /ws.
2. SESSION_START crea o retoma VoiceSessionRuntime.
3. USER_TRANSCRIPT:
   - parse de comandos de voz (open repo, switch repo, new chat, end chat, approve/reject, list pending),
   - o inicio de task con orchestrator.start_task(...),
   - o respuesta a turnos pendientes.
4. Mensajes de salida:
   - estado de sesion,
   - chat persistido,
   - prompts de aprobacion/pending turns,
   - AI_RESPONSE con fallback o streaming de audio.
5. Streaming audio:
   - AUDIO_STREAM_START -> N * AUDIO_STREAM_CHUNK -> AUDIO_STREAM_END
   - fallback a AI_RESPONSE con audioBase64 si streaming no disponible.

### 5.6 Flujo de memoria
1. Al crear/activar agente, se asegura memoria Markdown estructurada.
2. record_task_started / record_plan_proposed / record_task_completed actualizan memoria.
3. render_memory_for_llm(...) genera vista truncada para contexto del LLM.
4. compact_if_needed(...) recorta y archiva tareas antiguas cuando excede limites.

## 6. Funciones y metodos principales (referencia rapida)

### 6.1 Orquestador
- app/services/orchestrator.py
  - JarvisOrchestrator.create(...)
  - activate_repo_agent(...)
  - start_task(...)
  - submit_user_response(...)
  - get_next_turn(...)
  - list_pending_turns(...)
  - get_memory_view(...)

### 6.2 Coordinacion
- app/services/global_manager.py
  - enqueue_turn(...)
  - get_next_turn(...)
  - record_user_response(...)
  - emit_progress(...), emit_completed(...), emit_failed(...)
  - register_listener(...), unregister_listener(...)

### 6.3 Registro y persistencia
- app/services/repository_registry.py
  - get_or_create_repo_agent(...)
  - get_agent_state(...)
  - save_agent_state(...)
  - save_task_state(...)
- app/services/persistence.py
  - save/get/list para repositories, repo_agents, task_agents, turns, events, chat_sessions, chat_messages

### 6.4 Ejecucion segura
- app/services/local_executor.py
  - list_files(...), read_file(...), search_code(...)
  - apply_patch(...)
  - run_allowed_command(...)
  - create_branch(...), git_status(...), git_diff(...)

### 6.5 Agentes
- app/agents/repository_agent.py
  - start_task(...)
  - handle_user_response(...)
  - execute_approved_plan(...)
- app/agents/task_agent.py
  - execute(...)
  - mark_dead(...)

### 6.6 Voz
- app/services/voice_session_service.py
  - start_session(...)
  - handle_user_transcript(...)
  - handle_manager_event(...)
  - list_pending_turns(...), get_repo_summaries(...)
- app/api/voice_ws.py
  - websocket_voice(...)
  - send_audio_stream(...)
  - synthesize_with_elevenlabs(...)

## 7. Recursos utilizados

### 7.1 Persistencia y almacenamiento
- SQLite local (JARVIS_DB_PATH) para estado operacional:
  - repositories, repo_agents, task_agents, turns, events, chat_sessions, chat_messages
- Memoria Markdown por repo agent (JARVIS_MEMORY_DIR):
  - archivo por repo_agent_id
  - carpeta archive para compactacion

### 7.2 Recursos externos
- OpenAI Agents SDK (opcional, fallback deterministico si no disponible):
  - implementado en OpenAIAgentsClient
- ElevenLabs (opcional) para sintesis/streaming de audio:
  - usa ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID

### 7.3 Dependencias clave
- fastapi, uvicorn, pydantic, httpx, pytest
- openai-agents (opcional)
- langgraph + langgraph-checkpoint-sqlite (opcional)

### 7.4 Configuracion critica (env)
- OPENAI_API_KEY, OPENAI_MODEL
- JARVIS_ENV, JARVIS_USER_ID
- JARVIS_DATA_DIR, JARVIS_DB_PATH, JARVIS_MEMORY_DIR
- JARVIS_ALLOWED_REPO_ROOTS
- JARVIS_ALLOWED_COMMANDS
- JARVIS_MEMORY_MAX_CHARS, JARVIS_MEMORY_VIEW_MAX_CHARS, JARVIS_MEMORY_MAX_COMPLETED_TASKS
- ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID, ELEVENLABS_OUTPUT_FORMAT

## 8. Restricciones y reglas operativas importantes
- No ejecutar comandos fuera de allowlist (LocalExecutor + test_tools).
- No tocar rutas fuera del repo ni fuera de roots permitidas.
- No aplicar patches fuera del scope de la tarea.
- Turnos con prioridad + lock de intake controlan interaccion de usuario.
- El backend puede funcionar sin OpenAI/LangGraph gracias a fallback.
- La voz funciona con estado de sesion y chat persistido por repo.

## 9. Riesgos tecnicos conocidos para un agente IA
- Conflictos de merge sin resolver rompen import/parse inmediatamente.
- Si puerto 8000 esta ocupado, Uvicorn falla aunque el codigo sea correcto.
- Cambios en protocolo de voz deben mantenerse sincronizados con frontend.
- Memoria grande se compacta y puede truncarse para contexto LLM.

## 10. Comandos de arranque/prueba
- Backend:
  - uvicorn app.main:app --reload --port 8000
- Tests:
  - python -m pytest

## 11. Checklist rapido antes de modificar codigo
- Confirmar modulo/flujo afectado (HTTP, orquestacion, agentes, voz, memoria).
- Revisar impacto en TurnRequest/TurnResponse y ManagerEvent.
- Validar restricciones de LocalExecutor (scope, roots, allowlist).
- Mantener compatibilidad de protocolo de voz con frontend.
- Ejecutar al menos tests relevantes del area tocada.
