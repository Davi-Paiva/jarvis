package com.jarvis.intellij.model

data class ArchitectureDiagram(
    val nodes: List<DiagramNode> = emptyList(),
    val edges: List<DiagramEdge> = emptyList(),
)

data class DiagramNode(
    val id: String,
    val label: String,
    val path: String,
    val folder: String,
    val color: String,
    val status: DiagramNodeStatus,
    val x: Int,
    val y: Int,
)

data class DiagramEdge(
    val from: String,
    val to: String,
    val kind: String = "import",
)

enum class DiagramNodeStatus(
    val colorHex: String,
    val label: String,
) {
    ADDED(colorHex = "#32c766", label = "New"),
    MODIFIED(colorHex = "#f5c451", label = "Modified"),
    UNCHANGED(colorHex = "#8d99ae", label = "Unchanged"),
}

data class CachedDiagram(
    val gitState: String,
    val diagram: ArchitectureDiagram,
)

data class GitDiagramSnapshot(
    val signature: String,
    val statuses: Map<String, DiagramNodeStatus>,
)

data class DiagramLoadResult(
    val html: String,
    val fromCache: Boolean,
    val nodeCount: Int,
    val edgeCount: Int,
)