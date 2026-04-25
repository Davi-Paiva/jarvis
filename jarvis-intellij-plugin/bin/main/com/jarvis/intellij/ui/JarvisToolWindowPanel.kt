package com.jarvis.intellij.ui

import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.editor.ScrollType
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.jarvis.intellij.model.AnalyzeResponse
import com.jarvis.intellij.services.ProjectAnalysisCoordinator
import java.awt.BorderLayout
import java.awt.Dimension
import javax.swing.Box
import javax.swing.BoxLayout
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JSplitPane
import javax.swing.ListSelectionModel

class JarvisToolWindowPanel(private val project: Project) : JPanel(BorderLayout()) {
    private val logger = Logger.getInstance(JarvisToolWindowPanel::class.java)
    private val analysisCoordinator = ProjectAnalysisCoordinator(project)

    private val analyzeChangesButton = JButton("Analyze Changes")
    private val nextStepButton = JButton("Next Step")
    private val statusLabel = JLabel("Click Analyze Changes to load changed files.")
    private val fileListModel = DefaultListModel<ProjectFileItem>()
    private val fileList = JBList(fileListModel)
    private val resultsArea = JBTextArea()

    private var currentAnalysis: AnalyzeResponse? = null
    private var currentFileItem: ProjectFileItem? = null
    private var currentChangedLines: List<Int> = emptyList()
    private var currentLineSummaries: Map<Int, String> = emptyMap()
    private var currentChangedLineIndex = 0

    init {
        buildUi()
        registerListeners()
    }

    private fun buildUi() {
        val controlsPanel = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.X_AXIS)
            add(analyzeChangesButton)
            add(Box.createHorizontalStrut(8))
            add(nextStepButton)
        }

        val headerPanel = JPanel(BorderLayout(8, 0)).apply {
            add(controlsPanel, BorderLayout.WEST)
            add(statusLabel, BorderLayout.CENTER)
        }

        fileList.selectionMode = ListSelectionModel.SINGLE_SELECTION

        resultsArea.isEditable = false
        resultsArea.lineWrap = true
        resultsArea.wrapStyleWord = true
        resultsArea.text = "Jarvis results will appear here."

        nextStepButton.isEnabled = false

        val splitPane = JSplitPane(
            JSplitPane.HORIZONTAL_SPLIT,
            JBScrollPane(fileList),
            JBScrollPane(resultsArea),
        ).apply {
            resizeWeight = 0.35
            preferredSize = Dimension(800, 500)
        }

        add(headerPanel, BorderLayout.NORTH)
        add(splitPane, BorderLayout.CENTER)
    }

    private fun registerListeners() {
        analyzeChangesButton.addActionListener {
            loadChangedFiles()
        }

        nextStepButton.addActionListener {
            showNextStep()
        }

        fileList.addListSelectionListener { event ->
            if (!event.valueIsAdjusting) {
                val selectedItem = fileList.selectedValue ?: return@addListSelectionListener
                analyzeSelectedFile(selectedItem)
            }
        }
    }

    private fun loadChangedFiles() {
        logger.info("Analyze Changes clicked for ${project.name}")
        analyzeChangesButton.isEnabled = false
        nextStepButton.isEnabled = false
        fileListModel.clear()
        currentAnalysis = null
        currentFileItem = null
        currentChangedLines = emptyList()
        currentLineSummaries = emptyMap()
        currentChangedLineIndex = 0
        resultsArea.text = "Loading changed files..."
        statusLabel.text = "Running git diff..."

        analysisCoordinator.loadChangedFiles(
            onSuccess = { files ->
                analyzeChangesButton.isEnabled = true
                files.forEach { file ->
                    fileListModel.addElement(ProjectFileItem(toDisplayPath(file), file))
                }

                if (files.isEmpty()) {
                    statusLabel.text = "No changes detected"
                    resultsArea.text = "Jarvis did not find any changed files to analyze."
                } else {
                    statusLabel.text = "Loaded ${files.size} changed file(s). Select one to analyze."
                    resultsArea.text = "Choose a changed file on the left to send it to Jarvis."
                }
            },
            onError = { message ->
                analyzeChangesButton.isEnabled = true
                statusLabel.text = message
                resultsArea.text = message
            },
        )
    }

    private fun analyzeSelectedFile(item: ProjectFileItem) {
        logger.info("Analyzing file ${item.displayPath}")
        currentFileItem = item
        nextStepButton.isEnabled = false
        currentAnalysis = null
        currentChangedLines = emptyList()
        currentLineSummaries = emptyMap()
        currentChangedLineIndex = 0
        statusLabel.text = "Analyzing ${item.displayPath}..."
        resultsArea.text = "Reading ${item.displayPath} and sending it to Jarvis..."
        openFile(item.file)

        analysisCoordinator.analyzeFile(
            file = item.file,
            fileLabel = item.displayPath,
            onSuccess = { result ->
                currentAnalysis = result.response
                currentChangedLines = result.changedLines
                currentLineSummaries = result.response.lineExplanations
                    .associate { it.lineNumber to it.summary }
                currentChangedLineIndex = 0
                focusCurrentChangedLine()
            },
            onError = { message ->
                statusLabel.text = message
                resultsArea.text = message
            },
        )
    }

    private fun renderAnalysis() {
        val analysis = currentAnalysis ?: return
        val currentLine = currentChangedLines.getOrNull(currentChangedLineIndex)
        val currentLineSummary = currentLine?.let { currentLineSummaries[it] }

        resultsArea.text = buildString {
            append(analysis.summary.ifBlank { "No summary returned." })

            if (currentLine != null && !currentLineSummary.isNullOrBlank()) {
                appendLine()
                appendLine()
                appendLine("Changed line ${currentChangedLineIndex + 1}/${currentChangedLines.size} (L$currentLine)")
                append(currentLineSummary)
            }
        }
        resultsArea.caretPosition = 0
        updateNextStepButton()
    }

    private fun showNextStep() {
        if (currentChangedLines.isEmpty()) {
            return
        }

        currentChangedLineIndex = (currentChangedLineIndex + 1) % currentChangedLines.size
        focusCurrentChangedLine()
    }

    private fun updateNextStepButton() {
        if (currentChangedLines.size <= 1) {
            nextStepButton.isEnabled = false
            nextStepButton.text = "Next Step"
            return
        }

        nextStepButton.isEnabled = true
        nextStepButton.text = "Next Step"
    }

    private fun focusCurrentChangedLine() {
        val item = currentFileItem ?: return
        val changedLine = currentChangedLines.getOrNull(currentChangedLineIndex)
        val editor = openFile(item.file, changedLine)

        if (changedLine == null) {
            statusLabel.text = "Analysis ready for ${item.displayPath}."
            renderAnalysis()
            return
        }

        editor?.let { highlightLine(it, changedLine) }
        statusLabel.text = "Analysis ready for ${item.displayPath}. Changed line ${currentChangedLineIndex + 1}/${currentChangedLines.size}."
        renderAnalysis()
    }

    private fun openFile(file: VirtualFile, lineNumber: Int? = null) =
        FileEditorManager.getInstance(project).openTextEditor(
            OpenFileDescriptor(
                project,
                file,
                ((lineNumber ?: 1) - 1).coerceAtLeast(0),
                0,
            ),
            true,
        )

    private fun highlightLine(editor: com.intellij.openapi.editor.Editor, lineNumber: Int) {
        val document = editor.document
        if (document.lineCount == 0) {
            return
        }

        val zeroBasedLine = (lineNumber - 1).coerceIn(0, document.lineCount - 1)
        val startOffset = document.getLineStartOffset(zeroBasedLine)
        val endOffset = document.getLineEndOffset(zeroBasedLine)

        editor.caretModel.moveToOffset(startOffset)
        editor.selectionModel.setSelection(startOffset, endOffset)
        editor.scrollingModel.scrollToCaret(ScrollType.CENTER)
    }

    private fun toDisplayPath(file: VirtualFile): String {
        val basePath = project.basePath?.replace('\\', '/') ?: return file.name
        val filePath = file.path.replace('\\', '/')
        val prefix = "$basePath/"
        return if (filePath.startsWith(prefix)) {
            filePath.removePrefix(prefix)
        } else {
            file.name
        }
    }
}

private data class ProjectFileItem(
    val displayPath: String,
    val file: VirtualFile,
) {
    override fun toString(): String = displayPath
}
