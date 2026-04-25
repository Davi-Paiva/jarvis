package com.jarvis.intellij.services

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.jarvis.intellij.model.AnalyzeResponse
import com.jarvis.intellij.network.JarvisApiClient
import com.jarvis.intellij.network.JarvisApiException

class ProjectAnalysisCoordinator(
    private val project: Project,
    private val gitService: GitService = GitService(),
    private val fileService: FileService = FileService(),
    private val apiClient: JarvisApiClient = JarvisApiClient(),
) {
    private val logger = Logger.getInstance(ProjectAnalysisCoordinator::class.java)

    fun loadChangedFiles(
        onSuccess: (List<VirtualFile>) -> Unit,
        onError: (String) -> Unit,
    ) {
        runAsync(
            taskName = "load changed files",
            work = {
                val changedPaths = gitService.listChangedFiles(project)
                fileService.findFilesByRelativePaths(project, changedPaths)
            },
            onSuccess = onSuccess,
            onError = onError,
        )
    }

    fun analyzeFile(
        file: VirtualFile,
        fileLabel: String,
        onSuccess: (FileAnalysisResult) -> Unit,
        onError: (String) -> Unit,
    ) {
        runAsync(
            taskName = "analyze $fileLabel",
            work = {
                val content = fileService.readFileContent(file)
                val diff = gitService.getDiffForFile(project, fileLabel, content)
                FileAnalysisResult(
                    response = apiClient.analyzeFile(fileLabel, content, diff),
                    changedLines = gitService.getChangedLineNumbers(diff),
                )
            },
            onSuccess = onSuccess,
            onError = onError,
        )
    }

    private fun <T> runAsync(
        taskName: String,
        work: () -> T,
        onSuccess: (T) -> Unit,
        onError: (String) -> Unit,
    ) {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                logger.info("Starting $taskName")
                val result = work()
                invokeOnUiThread {
                    onSuccess(result)
                }
            } catch (exception: JarvisApiException) {
                logger.warn("Jarvis API error during $taskName", exception)
                invokeOnUiThread {
                    onError(exception.message ?: "Jarvis request failed.")
                }
            } catch (exception: Exception) {
                logger.warn("Unexpected error during $taskName", exception)
                invokeOnUiThread {
                    onError(exception.message ?: "Something went wrong while processing the file.")
                }
            }
        }
    }

    private fun invokeOnUiThread(action: () -> Unit) {
        ApplicationManager.getApplication().invokeLater {
            if (!project.isDisposed) {
                action()
            }
        }
    }
}

data class FileAnalysisResult(
    val response: AnalyzeResponse,
    val changedLines: List<Int>,
)
