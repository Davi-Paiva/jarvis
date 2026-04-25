// API Request/Response Types

export interface CreateRepoAgentInput {
  repo_path: string;
  display_name?: string;
  branch_name?: string;
}

export interface CreateRepoAgentOutput {
  repo_id: string;
  repo_path: string;
  display_name: string;
  branch_name?: string;
  created_at: string;
  // Add other fields based on your backend response
}

export interface ApiError {
  detail: string;
  status_code: number;
}
