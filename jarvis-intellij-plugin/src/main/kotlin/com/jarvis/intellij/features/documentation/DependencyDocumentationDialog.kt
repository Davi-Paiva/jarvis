package com.jarvis.intellij.features.documentation

import com.intellij.ide.BrowserUtil
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.ui.ColoredListCellRenderer
import com.intellij.ui.SearchTextField
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.speedSearch.ListSpeedSearch
import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.event.KeyEvent
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.DefaultListModel
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.KeyStroke
import javax.swing.event.DocumentEvent
import javax.swing.event.DocumentListener

class DependencyDocumentationDialog(
    private val project: Project,
    private val dependencies: List<DependencyDocumentationEntry>,
) : DialogWrapper(project) {
    private val searchField = SearchTextField()
    private val countLabel = JLabel()
    private val listModel = DefaultListModel<DependencyDocumentationEntry>()
    private val dependencyList = JBList(listModel)

    init {
        title = "Jarvis Dependency Documentation"
        setCancelButtonText("Close")
        init()
        applyFilter()
    }

    override fun createCenterPanel(): JComponent {
        dependencyList.cellRenderer = object : ColoredListCellRenderer<DependencyDocumentationEntry>() {
            override fun customizeCellRenderer(
                list: JBList<out DependencyDocumentationEntry>,
                value: DependencyDocumentationEntry?,
                index: Int,
                selected: Boolean,
                hasFocus: Boolean,
            ) {
                if (value == null) {
                    return
                }

                append(value.name, SimpleTextAttributes.REGULAR_BOLD_ATTRIBUTES)
                value.version?.takeIf { it.isNotBlank() }?.let { version ->
                    append("  $version", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                }
                append("  ${value.ecosystem.displayName}", SimpleTextAttributes.GRAYED_ATTRIBUTES)
                val remaining = (value.manifests.size - 2).coerceAtLeast(0)
                val truncatedLabel = if (remaining > 0) " +$remaining" else ""
                append(
                    "  ${value.manifests.joinToString(limit = 2, truncated = truncatedLabel)}",
                    SimpleTextAttributes.GRAYED_SMALL_ATTRIBUTES,
                )
            }
        }

        dependencyList.addMouseListener(
            object : MouseAdapter() {
                override fun mouseClicked(event: MouseEvent) {
                    if (event.button != MouseEvent.BUTTON1 || event.clickCount != 1) {
                        return
                    }
                    val index = dependencyList.locationToIndex(event.point)
                    if (index < 0) {
                        return
                    }
                    val bounds = dependencyList.getCellBounds(index, index) ?: return
                    if (!bounds.contains(event.point)) {
                        return
                    }
                    dependencyList.selectedIndex = index
                    openSelectedDocumentation()
                }
            },
        )

        dependencyList.registerKeyboardAction(
            { openSelectedDocumentation() },
            KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0),
            JComponent.WHEN_FOCUSED,
        )

        ListSpeedSearch(dependencyList) { entry -> entry.searchableText() }

        searchField.textEditor.document.addDocumentListener(
            object : DocumentListener {
                override fun insertUpdate(event: DocumentEvent) = applyFilter()

                override fun removeUpdate(event: DocumentEvent) = applyFilter()

                override fun changedUpdate(event: DocumentEvent) = applyFilter()
            },
        )

        val topPanel = JPanel(BorderLayout(8, 8)).apply {
            add(searchField, BorderLayout.CENTER)
            add(countLabel, BorderLayout.EAST)
        }

        return JPanel(BorderLayout(0, 8)).apply {
            preferredSize = Dimension(860, 520)
            add(topPanel, BorderLayout.NORTH)
            add(JBScrollPane(dependencyList), BorderLayout.CENTER)
        }
    }

    override fun createActions() = arrayOf(cancelAction)

    private fun applyFilter() {
        val query = searchField.text.trim().lowercase()
        val filtered = if (query.isBlank()) {
            dependencies
        } else {
            dependencies.filter { dependency ->
                dependency.searchableText().contains(query)
            }
        }

        listModel.removeAllElements()
        filtered.forEach { dependency ->
            listModel.addElement(dependency)
        }

        countLabel.text = "${filtered.size}/${dependencies.size}"

        if (filtered.isNotEmpty()) {
            dependencyList.selectedIndex = 0
        }
    }

    private fun openSelectedDocumentation() {
        val selected = dependencyList.selectedValue ?: return
        BrowserUtil.browse(selected.documentationUrl)
    }
}
