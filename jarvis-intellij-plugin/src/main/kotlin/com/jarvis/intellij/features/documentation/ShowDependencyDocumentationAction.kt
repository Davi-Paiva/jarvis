package com.jarvis.intellij.features.documentation

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.ui.Messages

class ShowDependencyDocumentationAction : AnAction(), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return

        var discoveredDependencies: List<DependencyDocumentationEntry> = emptyList()

        ProgressManager.getInstance().run(
            object : Task.Backgroundable(project, "Jarvis: Build Dependency Documentation Index", true) {
                override fun run(indicator: ProgressIndicator) {
                    indicator.isIndeterminate = false
                    discoveredDependencies = DependencyDocumentationService(project).collectDependencies(indicator)
                }

                override fun onSuccess() {
                    if (discoveredDependencies.isEmpty()) {
                        Messages.showInfoMessage(
                            project,
                            "Jarvis could not find supported dependency manifest files in this project.",
                            "Dependency Documentation",
                        )
                        return
                    }

                    DependencyDocumentationDialog(project, discoveredDependencies).show()
                }

                override fun onThrowable(error: Throwable) {
                    Messages.showErrorDialog(
                        project,
                        error.message ?: "Unable to load dependency documentation.",
                        "Dependency Documentation",
                    )
                }
            },
        )
    }
}
