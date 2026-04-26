package com.jarvis.intellij.services

import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ProjectFileIndex
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import java.io.File
import java.io.IOException

class FileService {
    private val logger = Logger.getInstance(FileService::class.java)

    fun listProjectFiles(project: Project): List<VirtualFile> {
        logger.info("Collecting files for ${project.name}")

        return ReadAction.compute<List<VirtualFile>, RuntimeException> {
            val files = mutableListOf<VirtualFile>()
            ProjectFileIndex.getInstance(project).iterateContent { file ->
                if (shouldInclude(file)) {
                    files += file
                }
                true
            }

            files.sortedWith(compareByDescending<VirtualFile> { it.timeStamp }.thenBy { it.path.lowercase() })
        }
    }

    fun readFileContent(file: VirtualFile): String =
        ReadAction.compute<String, RuntimeException> {
            if (!file.isValid) {
                throw IOException("The selected file is no longer available.")
            }
            VfsUtilCore.loadText(file)
        }

    fun findFilesByRelativePaths(project: Project, relativePaths: List<String>): List<VirtualFile> {
        if (relativePaths.isEmpty()) {
            return emptyList()
        }

        val projectRoot = project.basePath ?: throw IOException("Project root is unavailable.")
        logger.info("Resolving ${relativePaths.size} changed file(s) for ${project.name}")

        return relativePaths.mapNotNull { relativePath ->
            val filePath = File(projectRoot, relativePath).path.replace('\\', '/')
            val file = LocalFileSystem.getInstance().refreshAndFindFileByPath(filePath)

            when {
                file == null -> {
                    logger.warn("Changed file not found in project: $relativePath")
                    null
                }

                !ReadAction.compute<Boolean, RuntimeException> { shouldInclude(file) } -> null
                else -> file
            }
        }.distinctBy { it.path }
    }

    private fun shouldInclude(file: VirtualFile): Boolean {
        if (file.isDirectory || file.fileType.isBinary) {
            return false
        }

        val normalizedPath = file.path.replace('\\', '/').lowercase()
        return EXCLUDED_PATH_SEGMENTS.none { segment -> normalizedPath.contains(segment) }
    }

    companion object {
        private val EXCLUDED_PATH_SEGMENTS = listOf(
            "/.git/",
            "/.gradle/",
            "/.idea/",
            "/.venv/",
            "/build/",
            "/dist/",
            "/node_modules/",
            "/out/",
            "/target/",
        )
    }
}
