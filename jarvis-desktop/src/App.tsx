import { useState, useEffect } from "react";
import "./App.css";
import WelcomePage from "./components/WelcomePage";
import MainPage from "./components/MainPage";


function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [repoAgentId, setRepoAgentId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<"welcome" | "main">("welcome");

  useEffect(() => {
    const storedFolders = localStorage.getItem("jarvis-folders");
    if (storedFolders) {
      try {
        const folders = JSON.parse(storedFolders);
        if (Array.isArray(folders) && folders.length > 0) {
          const firstFolder = folders[0];
          setSelectedFolder(firstFolder.path);
          setRepoAgentId(firstFolder.repoAgentId);
          setCurrentPage("main");
        }
      } catch (error) {
        console.error("Failed to parse stored folders:", error);
      }
    }
  }, []);

  const handleGetStarted = (folderPath: string, nextRepoAgentId: string) => {
    setSelectedFolder(folderPath);
    setRepoAgentId(nextRepoAgentId);
    setCurrentPage("main");
  };

  return (
    <div className="app">
      {/* Custom Title Bar with native macOS buttons */}
      <div className="titlebar" data-tauri-drag-region>
        <div className="titlebar-text" data-tauri-drag-region>
          JARVIS
        </div>
      </div>

      {currentPage === "welcome" ? (
        <WelcomePage onGetStarted={handleGetStarted} />
      ) : (
        <MainPage
          initialFolder={selectedFolder!}
          initialRepoAgentId={repoAgentId || undefined}
        />
      )}
    </div>
  );
}

export default App;
