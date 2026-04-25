import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { apiService } from "../services/api";
import { ApiError } from "../types/api";
import "./WelcomePage.css";

interface WelcomePageProps {
  onGetStarted: (folderPath: string, repoId: string) => void;
}

function WelcomePage({ onGetStarted }: WelcomePageProps) {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSelectFolder = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Select Project Folder",
      });

      if (selected && typeof selected === "string") {
        setSelectedFolder(selected);
      }
    } catch (error) {
      console.error("Error selecting folder:", error);
      setError("Failed to select folder");
    } finally {
      setIsLoading(false);
    }
  };

  const handleGetStarted = async () => {
    if (!selectedFolder) return;

    try {
      setIsLoading(true);
      setError(null);

      // Extract folder name for display
      const folderName = selectedFolder.split("/").pop() || "Project";

      // Call backend API to activate the folder
      const result = await apiService.activateFolder(selectedFolder, folderName);

      // Navigate to main page on success with repoId
      onGetStarted(selectedFolder, result.repo_id);
    } catch (err) {
      const apiError = err as ApiError;
      console.error("Error activating folder:", apiError);
      
      if (apiError.status_code === 400) {
        setError("Invalid repository path. Please select a valid Git repository.");
      } else if (apiError.status_code === 403) {
        setError("This folder is not allowed. Please check permissions.");
      } else if (apiError.status_code === 0) {
        setError("Cannot connect to backend server. Please ensure it's running.");
      } else {
        setError(apiError.detail || "Failed to activate folder");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="welcome-page">
      <div className="workspace-section">
        <h2 className="section-title">Workspace</h2>
        <p className="section-description">
          Select a project folder to begin working
        </p>

        {error && (
          <div className="error-message">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            {error}
          </div>
        )}

        {!selectedFolder ? (
          <button
            className="folder-button"
            onClick={handleSelectFolder}
            disabled={isLoading}
          >
            <svg
              className="folder-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            {isLoading ? "Opening..." : "Select Project Folder"}
          </button>
        ) : null}

        {selectedFolder && (
          <div className="selected-folder">
            <div className="folder-label">Selected Folder:</div>
            <div className="folder-path">{selectedFolder}</div>
            <button
              className="change-folder-button"
              onClick={handleSelectFolder}
              disabled={isLoading}
            >
              Change Folder
            </button>
          </div>
        )}

        {selectedFolder && (
          <button 
            className="get-started-button" 
            onClick={handleGetStarted}
            disabled={isLoading}
          >
            {isLoading ? "Activating..." : "Get Started"}
          </button>
        )}
      </div>
    </main>
  );
}

export default WelcomePage;
