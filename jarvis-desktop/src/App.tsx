import { useState } from "react";
import "./App.css";
import WelcomePage from "./components/WelcomePage";
import MainPage from "./components/MainPage";


function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [repoAgentId, setRepoAgentId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<"welcome" | "main">("welcome");

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
