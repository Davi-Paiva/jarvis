package com.jarvis.intellij.features.documentation

import com.intellij.ide.BrowserUtil
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.ui.Messages
import java.awt.MouseInfo
import java.awt.Point
import javax.swing.SwingUtilities

class OpenImportDocumentationAction : AnAction(), DumbAware {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT

    override fun update(event: AnActionEvent) {
        val editor = event.getData(CommonDataKeys.EDITOR)
        event.presentation.isEnabled = editor != null && resolveImportReference(editor) != null
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val editor = event.getData(CommonDataKeys.EDITOR)
        if (editor == null) {
            Messages.showInfoMessage(
                project,
                "Open a file and place the mouse over an import, or put the caret on one, before triggering import documentation.",
                "Open Import Documentation",
            )
            return
        }

        val importReference = resolveImportReference(editor)
        if (importReference == null) {
            Messages.showInfoMessage(
                project,
                "Jarvis could not detect an import under the mouse or caret.",
                "Open Import Documentation",
            )
            return
        }

        var matchedEntry: DependencyDocumentationEntry? = null

        ProgressManager.getInstance().run(
            object : Task.Backgroundable(project, "Jarvis: Open Import Documentation", true) {
                override fun run(indicator: ProgressIndicator) {
                    indicator.isIndeterminate = false
                    indicator.text = "Scanning project dependencies"
                    indicator.text2 = importReference

                    val service = DependencyDocumentationService(project)
                    val dependencies = service.collectDependencies(indicator)
                    matchedEntry = service.findDocumentationEntryForImport(importReference, dependencies)
                }

                override fun onSuccess() {
                    val entry = matchedEntry
                    if (entry == null) {
                        Messages.showInfoMessage(
                            project,
                            "Jarvis did not find dependency documentation for '$importReference'.",
                            "Open Import Documentation",
                        )
                        return
                    }

                    BrowserUtil.browse(entry.documentationUrl)
                }

                override fun onThrowable(error: Throwable) {
                    Messages.showErrorDialog(
                        project,
                        error.message ?: "Unable to resolve import documentation.",
                        "Open Import Documentation",
                    )
                }
            },
        )
    }

    private fun resolveImportReference(editor: Editor): String? {
        val document = editor.document
        if (document.textLength == 0) {
            return null
        }

        val offset = resolveMouseOffset(editor) ?: editor.caretModel.offset
        val boundedOffset = offset.coerceIn(0, document.textLength - 1)
        val lineNumber = document.getLineNumber(boundedOffset)
        val lineStart = document.getLineStartOffset(lineNumber)
        val lineEnd = document.getLineEndOffset(lineNumber)
        val lineText = document.charsSequence.subSequence(lineStart, lineEnd).toString()
        val column = boundedOffset - lineStart

        val candidates = extractImportCandidates(lineText)
        val hoveredCandidate = candidates.firstOrNull { column in it.start until it.endExclusive }
        return hoveredCandidate?.value ?: candidates.singleOrNull()?.value
    }

    private fun resolveMouseOffset(editor: Editor): Int? {
        val contentComponent = editor.contentComponent
        if (!contentComponent.isShowing) {
            return null
        }

        val pointerLocation = MouseInfo.getPointerInfo()?.location ?: return null
        val localPoint = Point(pointerLocation)
        SwingUtilities.convertPointFromScreen(localPoint, contentComponent)

        if (
            localPoint.x < 0 ||
            localPoint.y < 0 ||
            localPoint.x > contentComponent.width ||
            localPoint.y > contentComponent.height
        ) {
            return null
        }

        val logicalPosition = editor.xyToLogicalPosition(localPoint)
        return editor.logicalPositionToOffset(logicalPosition)
    }

    private fun extractImportCandidates(lineText: String): List<ImportCandidate> {
        val candidates = mutableListOf<ImportCandidate>()

        JAVASCRIPT_FROM_REGEX.findAll(lineText).forEach { match ->
            candidates.add(match.groupCandidate())
        }

        JAVASCRIPT_SIDE_EFFECT_IMPORT_REGEX.findAll(lineText).forEach { match ->
            candidates.add(match.groupCandidate())
        }

        JAVASCRIPT_REQUIRE_REGEX.findAll(lineText).forEach { match ->
            candidates.add(match.groupCandidate())
        }

        PYTHON_FROM_REGEX.find(lineText)?.let { match ->
            candidates.add(match.groupCandidate())
        }

        PYTHON_IMPORT_REGEX.find(lineText)?.groups?.get(1)?.let { group ->
            PYTHON_IMPORT_ITEM_REGEX.findAll(group.value).forEach { itemMatch ->
                val moduleName = itemMatch.groupValues[1].trim()
                if (moduleName.isNotBlank()) {
                    candidates.add(
                        ImportCandidate(
                            value = moduleName,
                            start = group.range.first + itemMatch.range.first,
                            endExclusive = group.range.first + itemMatch.range.last + 1,
                        ),
                    )
                }
            }
        }

        JAVA_IMPORT_REGEX.find(lineText)?.let { match ->
            candidates.add(match.groupCandidate())
        }

        RUST_USE_REGEX.find(lineText)?.groups?.get(1)?.let { group ->
            val root = group.value
                .substringBefore("::")
                .substringBefore('{')
                .substringBefore(';')
                .trim()
            if (root.isNotBlank()) {
                candidates.add(
                    ImportCandidate(
                        value = root,
                        start = group.range.first,
                        endExclusive = group.range.first + root.length,
                    ),
                )
            }
        }

        return candidates.distinctBy { it.value.lowercase() }
    }

    private fun MatchResult.groupCandidate(index: Int = 1): ImportCandidate {
        val group = groups[index] ?: error("Missing import group $index")
        return ImportCandidate(
            value = group.value.trim(),
            start = group.range.first,
            endExclusive = group.range.last + 1,
        )
    }

    private data class ImportCandidate(
        val value: String,
        val start: Int,
        val endExclusive: Int,
    )

    companion object {
        private val JAVASCRIPT_FROM_REGEX = Regex("\\bfrom\\s+[\"']([^\"']+)[\"']")
        private val JAVASCRIPT_SIDE_EFFECT_IMPORT_REGEX = Regex("^\\s*import\\s+[\"']([^\"']+)[\"']")
        private val JAVASCRIPT_REQUIRE_REGEX = Regex("\\brequire\\(\\s*[\"']([^\"']+)[\"']\\s*\\)")
        private val PYTHON_FROM_REGEX = Regex("^\\s*from\\s+([A-Za-z0-9_.]+)\\s+import\\b")
        private val PYTHON_IMPORT_REGEX = Regex("^\\s*import\\s+([^;]+)$")
        private val PYTHON_IMPORT_ITEM_REGEX = Regex("([A-Za-z0-9_.]+)(?:\\s+as\\s+[A-Za-z0-9_]+)?")
        private val JAVA_IMPORT_REGEX = Regex("^\\s*import\\s+(?:static\\s+)?([A-Za-z0-9_.*]+)")
        private val RUST_USE_REGEX = Regex("^\\s*use\\s+([^;]+)")
    }
}