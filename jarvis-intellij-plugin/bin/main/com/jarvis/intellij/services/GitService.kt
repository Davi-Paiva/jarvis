package com.jarvis.intellij.services

import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.jarvis.intellij.model.DiagramNodeStatus
import com.jarvis.intellij.model.GitDiagramSnapshot
import java.io.File
import java.io.IOException
import kotlin.math.max
import java.util.concurrent.TimeUnit

class GitService {
    private val logger = Logger.getInstance(GitService::class.java)

    fun getDiagramGitSnapshot(project: Project): GitDiagramSnapshot {
        val projectRoot = project.basePath ?: throw GitServiceException("Project root is unavailable.")
        val trackedOutput = readTrackedNameStatus(projectRoot)
        val untrackedFiles = readUntrackedFiles(projectRoot)

        val statuses = linkedMapOf<String, DiagramNodeStatus>()
        trackedOutput.lineSequence()
            .map(String::trim)
            .filter(String::isNotEmpty)
            .forEach { line ->
                val parts = line.split('\t').filter { it.isNotBlank() }
                if (parts.size < 2) {
                    return@forEach
                }

                val statusCode = parts.first().trim()
                val rawPath = parts.last().trim()
                val normalizedPath = normalizePath(rawPath)
                when {
                    statusCode.startsWith("A", ignoreCase = true) -> {
                        statuses[normalizedPath] = DiagramNodeStatus.ADDED
                    }

                    statusCode.startsWith("M", ignoreCase = true) ||
                        statusCode.startsWith("R", ignoreCase = true) ||
                        statusCode.startsWith("C", ignoreCase = true) -> {
                        statuses[normalizedPath] = DiagramNodeStatus.MODIFIED
                    }
                }
            }

        untrackedFiles.forEach { path ->
            statuses[path] = DiagramNodeStatus.ADDED
        }

        val signature = buildString {
            trackedOutput.lineSequence()
                .map(String::trim)
                .filter(String::isNotEmpty)
                .sorted()
                .forEach { appendLine(it) }
            appendLine("--untracked--")
            untrackedFiles.sorted().forEach { appendLine(it) }
        }.trim()

        logger.info(
            "Collected git snapshot for ${project.name}: ${statuses.size} changed file(s)",
        )
        return GitDiagramSnapshot(signature = signature, statuses = statuses)
    }

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

    fun getChangedLineNumbers(diff: String): List<Int> {
        if (diff.isBlank()) {
            return emptyList()
        }

        val changedLines = linkedSetOf<Int>()
        diff.lineSequence().forEach { line ->
            val match = HUNK_HEADER_REGEX.find(line) ?: return@forEach
            val startLine = match.groupValues[1].toIntOrNull() ?: return@forEach
            val count = match.groupValues[2].toIntOrNull() ?: 1

            if (count == 0) {
                if (startLine > 0) {
                    changedLines += max(1, startLine)
                }
                return@forEach
            }

            for (lineNumber in startLine until (startLine + count)) {
                if (lineNumber > 0) {
                    changedLines += lineNumber
                }
            }
        }

        return changedLines.toList()
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

    private fun readTrackedNameStatus(projectRoot: String): String {
        val trackedChanges = runGitCommand(projectRoot, "git", "diff", "--name-status", "HEAD")
        return when {
            trackedChanges.exitCode == 0 -> trackedChanges.output
            trackedChanges.output.contains("not a git repository", ignoreCase = true) -> {
                throw GitServiceException("No git repository found")
            }

            trackedChanges.output.contains("bad revision 'HEAD'", ignoreCase = true) -> ""
            trackedChanges.output.contains("ambiguous argument 'HEAD'", ignoreCase = true) -> ""
            else -> {
                logger.warn(
                    "git diff --name-status failed for $projectRoot with exit code ${trackedChanges.exitCode}: ${trackedChanges.output}",
                )
                throw GitServiceException("Unable to read git changes.")
            }
        }
    }

    private fun readUntrackedFiles(projectRoot: String): List<String> {
        val untrackedChanges = runGitCommand(projectRoot, "git", "ls-files", "--others", "--exclude-standard")
        return when {
            untrackedChanges.exitCode == 0 -> parsePaths(untrackedChanges.output).map(::normalizePath)
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
    }

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

    companion object {
        private val HUNK_HEADER_REGEX = Regex("@@ -\\d+(?:,\\d+)? \\+(\\d+)(?:,(\\d+))? @@")
    }
}

class GitServiceException(message: String, cause: Throwable? = null) : Exception(message, cause)

private data class GitCommandResult(
    val output: String,
    val exitCode: Int,
)