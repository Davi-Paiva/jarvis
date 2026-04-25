package com.jarvis.intellij.ui

import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
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
    private var currentStepIndex = 0

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
        currentStepIndex = 0
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
        nextStepButton.isEnabled = false
        currentAnalysis = null
        currentStepIndex = 0
        statusLabel.text = "Analyzing ${item.displayPath}..."
        resultsArea.text = "Reading ${item.displayPath} and sending it to Jarvis..."

        analysisCoordinator.analyzeFile(
            file = item.file,
            fileLabel = item.displayPath,
            onSuccess = { response ->
                currentAnalysis = response
                currentStepIndex = 0
                statusLabel.text = "Analysis ready for ${item.displayPath}."
                renderAnalysis()
            },
            onError = { message ->
                statusLabel.text = message
                resultsArea.text = message
            },
        )
    }

    private fun renderAnalysis() {
        val analysis = currentAnalysis ?: return
        resultsArea.text = buildString {
            appendLine("Summary")
            appendLine(analysis.summary.ifBlank { "No summary returned." })
            appendLine()

            if (analysis.steps.isEmpty()) {
                appendLine("Steps")
                appendLine("No explanation steps returned.")
            } else {
                appendLine("Current Step (${currentStepIndex + 1}/${analysis.steps.size})")
                appendLine(analysis.steps[currentStepIndex])
                appendLine()
                appendLine("All Steps")
                analysis.steps.forEachIndexed { index, step ->
                    val prefix = if (index == currentStepIndex) ">" else "-"
                    appendLine("$prefix ${index + 1}. $step")
                }
            }
        }.trim()
        resultsArea.caretPosition = 0
        updateNextStepButton()
    }

    private fun showNextStep() {
        val analysis = currentAnalysis ?: return
        if (analysis.steps.isEmpty()) {
            return
        }

        currentStepIndex = (currentStepIndex + 1) % analysis.steps.size
        renderAnalysis()
    }

    private fun updateNextStepButton() {
        val steps = currentAnalysis?.steps.orEmpty()
        if (steps.size <= 1) {
            nextStepButton.isEnabled = false
            nextStepButton.text = "Next Step"
            return
        }

        nextStepButton.isEnabled = true
        nextStepButton.text = if (currentStepIndex == steps.lastIndex) {
            "Restart Steps"
        } else {
            "Next Step"
        }
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
