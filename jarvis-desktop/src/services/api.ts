import { CreateRepoAgentInput, CreateRepoAgentOutput, ApiError } from "../types/api";

// Base API configuration
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

class ApiService {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  /**
   * Activate a folder/repository agent
   */
  async activateFolder(
    repoPath: string,
    displayName?: string,
    branchName?: string
  ): Promise<CreateRepoAgentOutput> {
    const payload: CreateRepoAgentInput = {
      repo_path: repoPath,
      display_name: displayName,
      branch_name: branchName,
    };

    try {
      const response = await fetch(`${this.baseUrl}/folder`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({
          detail: "Unknown error occurred",
        }));
        const error: ApiError = {
          detail: errorData.detail || "Failed to activate folder",
          status_code: response.status,
        };
        throw error;
      }

      const data: CreateRepoAgentOutput = await response.json();
      return data;
    } catch (error) {
      if ((error as ApiError).status_code) {
        throw error;
      }
      // Network or other errors
      throw {
        detail: "Failed to connect to backend server",
        status_code: 0,
      } as ApiError;
    }
  }

  /**
   * Health check endpoint
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        method: "GET",
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}

// Export singleton instance
export const apiService = new ApiService();

// Export class for testing
export default ApiService;
