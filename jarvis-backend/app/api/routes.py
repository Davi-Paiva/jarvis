from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.models.schemas import CreateRepoAgentInput, CreateRepoAgentOutput
from app.services.errors import InvalidRepositoryPathError, RepositoryPathNotAllowedError


router = APIRouter()


@router.post(
    "/folder",
    response_model=CreateRepoAgentOutput,
    status_code=status.HTTP_201_CREATED,
)
async def activate_folder(
    payload: CreateRepoAgentInput,
    request: Request,
    response: Response,
) -> CreateRepoAgentOutput:
    orchestrator = request.app.state.orchestrator
    try:
        state, created = await orchestrator.activate_repo_agent(
            repo_path=payload.repo_path,
            display_name=payload.display_name,
            branch_name=payload.branch_name,
        )
    except InvalidRepositoryPathError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RepositoryPathNotAllowedError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    if not created:
        response.status_code = status.HTTP_200_OK
    return orchestrator.to_create_repo_agent_output(state)


@router.delete(
    "/folder/{repo_agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_folder(
    repo_agent_id: str,
    request: Request,
) -> None:
    orchestrator = request.app.state.orchestrator
    try:
        await orchestrator.deactivate_repo_agent(repo_agent_id)
    except KeyError:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

