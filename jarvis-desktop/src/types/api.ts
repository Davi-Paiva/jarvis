// API Request/Response Types

export interface CreateRepoAgentInput {
  repo_path: string;
  display_name?: string;
  branch_name?: string;
}

export interface CreateRepoAgentOutput {
  repo_agent_id: string;
  repo_id: string;
  thread_id: string;
  phase: string;
}

export interface ApiError {
  detail: string;
  status_code: number;
}
