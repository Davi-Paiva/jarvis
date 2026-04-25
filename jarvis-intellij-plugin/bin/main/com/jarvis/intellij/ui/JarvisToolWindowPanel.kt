package com.jarvis.intellij.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.editor.ScrollType
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.jarvis.intellij.model.AnalyzeResponse
import com.jarvis.intellij.services.ProjectAnalysisCoordinator
import java.awt.CardLayout
import java.awt.BorderLayout
import java.awt.Dimension
import javax.swing.Box
import javax.swing.BoxLayout
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JEditorPane
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JSplitPane
import javax.swing.ListSelectionModel

class JarvisToolWindowPanel(private val project: Project) : JPanel(BorderLayout()), Disposable {
    private val logger = Logger.getInstance(JarvisToolWindowPanel::class.java)
    private val analysisCoordinator = ProjectAnalysisCoordinator(project)

    private val analyzeChangesButton = JButton("Analyze Changes")
    private val viewDiagramButton = JButton("View Diagram")
    private val nextStepButton = JButton("Next Step")
    private val statusLabel = JLabel("Click Analyze Changes to load changed files.")
    private val fileListModel = DefaultListModel<ProjectFileItem>()
    private val fileList = JBList(fileListModel)
    private val resultsArea = JBTextArea()
    private val analysisScrollPane = JBScrollPane(resultsArea)
    private val contentLayout = CardLayout()
    private val contentPanel = JPanel(contentLayout)
    private val diagramBrowser = if (JBCefApp.isSupported()) JBCefBrowser() else null
    private val diagramFallback = JEditorPane("text/html", "")
    private val diagramPanel = JPanel(BorderLayout())

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
            add(viewDiagramButton)
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

        diagramFallback.isEditable = false
        diagramFallback.text = diagramMessageHtml(
            title = "Architecture Diagram",
            message = "Click View Diagram to generate a visual map of the project.",
        )

        if (diagramBrowser != null) {
            diagramPanel.add(diagramBrowser.component, BorderLayout.CENTER)
        } else {
            diagramPanel.add(JBScrollPane(diagramFallback), BorderLayout.CENTER)
        }

        contentPanel.add(analysisScrollPane, ANALYSIS_CARD)
        contentPanel.add(diagramPanel, DIAGRAM_CARD)

        nextStepButton.isEnabled = false

        val splitPane = JSplitPane(
            JSplitPane.HORIZONTAL_SPLIT,
            JBScrollPane(fileList),
            contentPanel,
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

        viewDiagramButton.addActionListener {
            loadArchitectureDiagram()
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
        showAnalysisView()
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

    private fun loadArchitectureDiagram() {
        logger.info("View Diagram clicked for ${project.name}")
        viewDiagramButton.isEnabled = false
        nextStepButton.isEnabled = false
        statusLabel.text = "Building architecture diagram..."
        showDiagramView()
        renderDiagramHtml(
            diagramMessageHtml(
                title = "Building Diagram",
                message = "Grouping the codebase into architecture areas and rendering a Mermaid diagram.",
            ),
        )

        analysisCoordinator.loadArchitectureDiagram(
            onSuccess = { result ->
                viewDiagramButton.isEnabled = true
                renderDiagramHtml(result.html)
                statusLabel.text = if (result.fromCache) {
                    "Loaded cached diagram (${result.nodeCount} groups, ${result.edgeCount} relationships)."
                } else {
                    "Updated diagram cache (${result.nodeCount} groups, ${result.edgeCount} relationships)."
                }
            },
            onError = { message ->
                viewDiagramButton.isEnabled = true
                statusLabel.text = message
                renderDiagramHtml(
                    diagramMessageHtml(
                        title = "Diagram Unavailable",
                        message = message,
                    ),
                )
            },
        )
    }

    private fun analyzeSelectedFile(item: ProjectFileItem) {
        logger.info("Analyzing file ${item.displayPath}")
        showAnalysisView()
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

        showAnalysisView()
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

    private fun showAnalysisView() {
        contentLayout.show(contentPanel, ANALYSIS_CARD)
    }

    private fun showDiagramView() {
        contentLayout.show(contentPanel, DIAGRAM_CARD)
    }

    private fun renderDiagramHtml(html: String) {
        if (diagramBrowser != null) {
            diagramBrowser.loadHTML(html)
        } else {
            diagramFallback.text = diagramMessageHtml(
                title = "JCEF Required",
                message = "This IDE does not support the embedded browser needed for the interactive diagram view.",
            )
        }
    }

    private fun diagramMessageHtml(title: String, message: String): String =
        """
            <html>
            <body style="margin:0;padding:24px;font-family:Segoe UI, sans-serif;background:#f8fbff;color:#0f172a;">
                <div style="max-width:560px;padding:24px;border-radius:20px;background:white;border:1px solid rgba(148,163,184,0.25);box-shadow:0 20px 50px rgba(15,23,42,0.08);">
                    <h2 style="margin:0 0 12px;font-size:24px;">${escapeHtml(title)}</h2>
                    <p style="margin:0;font-size:14px;line-height:1.6;color:#475569;">${escapeHtml(message)}</p>
                </div>
            </body>
            </html>
        """.trimIndent()

    private fun escapeHtml(value: String): String = buildString(value.length) {
        value.forEach { character ->
            when (character) {
                '&' -> append("&amp;")
                '<' -> append("&lt;")
                '>' -> append("&gt;")
                '"' -> append("&quot;")
                else -> append(character)
            }
        }
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

    override fun dispose() {
        diagramBrowser?.dispose()
    }

    companion object {
        private const val ANALYSIS_CARD = "analysis"
        private const val DIAGRAM_CARD = "diagram"
    }
}

private data class ProjectFileItem(
    val displayPath: String,
    val file: VirtualFile,
) {
    override fun toString(): String = displayPath
}
