import { useState } from "react";
import "./App.css";
import WelcomePage from "./components/WelcomePage";
import MainPage from "./components/MainPage";


function App() {
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<"welcome" | "main">("welcome");

  const handleGetStarted = (folderPath: string, repoId: string) => {
    setSelectedFolder(folderPath);
    setRepoId(repoId);
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
        <MainPage initialFolder={selectedFolder!} repoId={repoId || undefined} />
      )}
    </div>
  );
}

export default App;
