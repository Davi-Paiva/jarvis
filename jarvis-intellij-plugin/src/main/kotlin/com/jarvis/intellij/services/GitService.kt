package com.jarvis.intellij.services

import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

class GitService {
    private val logger = Logger.getInstance(GitService::class.java)

    fun listChangedFiles(project: Project): List<String> {
        val projectRoot = project.basePath ?: throw GitServiceException("Project root is unavailable.")
        val trackedChanges = runGitCommand(projectRoot, "git", "diff", "--name-only", "HEAD")
        val untrackedChanges = runGitCommand(projectRoot, "git", "ls-files", "--others", "--exclude-standard")

        val trackedFiles = when {
            trackedChanges.exitCode == 0 -> parsePaths(trackedChanges.output)
            trackedChanges.output.contains("not a git repository", ignoreCase = true) -> {
                throw GitServiceException("No git repository found")
            }

            trackedChanges.output.contains("bad revision 'HEAD'", ignoreCase = true) -> emptyList()
            trackedChanges.output.contains("ambiguous argument 'HEAD'", ignoreCase = true) -> emptyList()
            else -> {
                logger.warn(
                    "git diff failed for $projectRoot with exit code ${trackedChanges.exitCode}: ${trackedChanges.output}",
                )
                throw GitServiceException("Unable to read git changes.")
            }
        }

        val untrackedFiles = when {
            untrackedChanges.exitCode == 0 -> parsePaths(untrackedChanges.output)
            untrackedChanges.output.contains("not a git repository", ignoreCase = true) -> {
                throw GitServiceException("No git repository found")
            }

            else -> {
                logger.warn(
                    "git ls-files failed for $projectRoot with exit code ${untrackedChanges.exitCode}: ${untrackedChanges.output}",
                )
                throw GitServiceException("Unable to read git changes.")
            }
        }

        val changedFiles = (trackedFiles + untrackedFiles)
            .map(String::trim)
            .filter(String::isNotEmpty)
            .distinct()
            .toList()

        logger.info(
            "Found ${changedFiles.size} changed file(s) for ${project.name} (${trackedFiles.size} tracked, ${untrackedFiles.size} untracked)",
        )
        return changedFiles
    }

    fun getDiffForFile(project: Project, relativePath: String, currentContent: String): String {
        val projectRoot = project.basePath ?: throw GitServiceException("Project root is unavailable.")
        val normalizedPath = normalizePath(relativePath)
        val trackedDiff = runGitCommand(
            projectRoot,
            "git",
            "diff",
            "--no-color",
            "--unified=0",
            "HEAD",
            "--",
            normalizedPath,
        )

        when {
            trackedDiff.exitCode == 0 && trackedDiff.output.isNotBlank() -> return trackedDiff.output
            trackedDiff.output.contains("not a git repository", ignoreCase = true) -> {
                throw GitServiceException("No git repository found")
            }

            trackedDiff.exitCode != 0 &&
                !trackedDiff.output.contains("bad revision 'HEAD'", ignoreCase = true) &&
                !trackedDiff.output.contains("ambiguous argument 'HEAD'", ignoreCase = true) -> {
                logger.warn(
                    "git diff failed for $projectRoot with exit code ${trackedDiff.exitCode}: ${trackedDiff.output}",
                )
                throw GitServiceException("Unable to read git changes.")
            }
        }

        if (isUntrackedFile(projectRoot, normalizedPath)) {
            return buildAddedFileDiff(normalizedPath, currentContent)
        }

        return trackedDiff.output
    }

    private fun runGitCommand(projectRoot: String, vararg command: String): GitCommandResult {
        val process = try {
            ProcessBuilder(*command)
                .directory(File(projectRoot))
                .redirectErrorStream(true)
                .start()
        } catch (exception: IOException) {
            logger.warn("Failed to start ${command.joinToString(" ")} for $projectRoot", exception)
            throw GitServiceException("Git is not available.", exception)
        }

        val output = process.inputStream.bufferedReader().use { it.readText().trim() }

        return try {
            if (!process.waitFor(15, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                throw GitServiceException("Git command timed out.")
            }

            GitCommandResult(output = output, exitCode = process.exitValue())
        } catch (exception: InterruptedException) {
            Thread.currentThread().interrupt()
            throw GitServiceException("Git command was interrupted.", exception)
        }
    }

    private fun parsePaths(output: String): List<String> =
        output.lineSequence()
            .map(String::trim)
            .filter(String::isNotEmpty)
            .toList()

    private fun isUntrackedFile(projectRoot: String, relativePath: String): Boolean {
        val untrackedCheck = runGitCommand(
            projectRoot,
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            relativePath,
        )

        return when {
            untrackedCheck.exitCode == 0 -> parsePaths(untrackedCheck.output)
                .map(::normalizePath)
                .contains(relativePath)

            untrackedCheck.output.contains("not a git repository", ignoreCase = true) -> {
                throw GitServiceException("No git repository found")
            }

            else -> {
                logger.warn(
                    "git ls-files failed for $projectRoot with exit code ${untrackedCheck.exitCode}: ${untrackedCheck.output}",
                )
                throw GitServiceException("Unable to read git changes.")
            }
        }
    }

    private fun buildAddedFileDiff(relativePath: String, currentContent: String): String {
        val lines = currentContent.replace("\r\n", "\n").split("\n")
        val hunkSize = if (lines.size == 1 && lines[0].isEmpty()) 0 else lines.size
        val header = listOf(
            "diff --git a/$relativePath b/$relativePath",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/$relativePath",
            "@@ -0,0 +1,$hunkSize @@",
        )
        val body = if (hunkSize == 0) {
            emptyList()
        } else {
            lines.map { line -> "+$line" }
        }
        return (header + body).joinToString("\n")
    }

    private fun normalizePath(path: String): String = path.replace('\\', '/').trim()
}

class GitServiceException(message: String, cause: Throwable? = null) : Exception(message, cause)

private data class GitCommandResult(
    val output: String,
    val exitCode: Int,
)