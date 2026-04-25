package com.jarvis.intellij.model

data class ArchitectureDiagram(
	val mermaid: String,
	val nodes: List<DiagramNode> = emptyList(),
	val edges: List<DiagramEdge> = emptyList(),
)

data class DiagramNode(
	val id: String,
	val surface: String,
	val title: String,
	val description: String,
	val status: DiagramNodeStatus,
)

data class DiagramEdge(
	val from: String,
	val to: String,
	val label: String? = null,
)

enum class DiagramNodeStatus {
	ADDED,
	MODIFIED,
	UNCHANGED,
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
