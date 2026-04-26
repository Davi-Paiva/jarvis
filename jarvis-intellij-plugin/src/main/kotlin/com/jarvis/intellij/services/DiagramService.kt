package com.jarvis.intellij.services

import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.jarvis.intellij.model.ArchitectureDiagram
import com.jarvis.intellij.model.DiagramEdge
import com.jarvis.intellij.model.DiagramNode
import com.jarvis.intellij.model.DiagramNodeStatus
import com.jarvis.intellij.model.GitDiagramSnapshot

class DiagramService(
	private val fileService: FileService = FileService(),
) {
	private val logger = Logger.getInstance(DiagramService::class.java)

	fun buildDiagram(
		project: Project,
		files: List<VirtualFile>,
		gitSnapshot: GitDiagramSnapshot,
	): ArchitectureDiagram {
		val projectRoot = project.basePath ?: throw IllegalStateException("Project root is unavailable.")
		val nodes = files
			.mapNotNull { file ->
				val relativePath = toRelativePath(projectRoot, file) ?: return@mapNotNull null
				classifyNode(relativePath, gitSnapshot.statuses)
			}
			.groupBy { it.id }
			.map { (_, descriptors) ->
				val first = descriptors.first()
				first.copy(status = aggregateStatus(descriptors.map { it.status }))
			}
			.sortedWith(compareBy<DiagramNode> { SURFACE_ORDER[it.surface] ?: DEFAULT_SURFACE_ORDER }.thenBy { it.title.lowercase() })

		val edges = buildEdges(nodes)
		val mermaid = buildMermaid(nodes, edges)

		logger.info("Built Mermaid architecture diagram for ${project.name}: ${nodes.size} nodes, ${edges.size} edges")
		return ArchitectureDiagram(
			mermaid = mermaid,
			nodes = nodes,
			edges = edges,
		)
	}

	fun renderHtml(projectName: String, diagram: ArchitectureDiagram): String {
		val escapedMermaid = escapeHtml(diagram.mermaid)
		val escapedTitle = escapeHtml(projectName)
		return """
			<!DOCTYPE html>
			<html lang="en">
			<head>
				<meta charset="UTF-8" />
				<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
				<style>
					body {
						margin: 0;
						background: #ffffff;
						color: #0f172a;
						font-family: "Segoe UI", sans-serif;
					}

					.shell {
						height: 100vh;
						display: flex;
						flex-direction: column;
					}

					.toolbar {
						display: flex;
						align-items: center;
						justify-content: space-between;
						gap: 12px;
						padding: 10px 12px;
						border-bottom: 1px solid #e2e8f0;
					}

					.title {
						margin: 0;
						font-size: 14px;
						font-weight: 600;
						color: #334155;
					}

					.controls {
						display: inline-flex;
						align-items: center;
						gap: 6px;
					}

					.zoom-button {
						min-width: 32px;
						height: 30px;
						padding: 0 10px;
						border: 1px solid #cbd5e1;
						border-radius: 6px;
						background: #ffffff;
						color: #0f172a;
						font: inherit;
						cursor: pointer;
					}

					.zoom-button:hover {
						background: #f8fafc;
					}

					.viewport {
						flex: 1;
						overflow: auto;
						padding: 16px;
						overscroll-behavior: contain;
					}

					.diagram-host {
						width: max-content;
						min-width: 100%;
					}

					.mermaid {
						margin: 0;
						font-size: 14px;
					}

					.mermaid svg {
						display: block;
						max-width: none;
					}
				</style>
			</head>
			<body>
				<div class="shell">
					<div class="toolbar">
						<div class="title">$escapedTitle Architecture</div>
						<div class="controls">
							<button class="zoom-button" id="zoom-out" type="button">-</button>
							<button class="zoom-button" id="zoom-reset" type="button">100%</button>
							<button class="zoom-button" id="zoom-in" type="button">+</button>
						</div>
					</div>
					<div class="viewport" id="diagram-viewport">
						<div class="diagram-host">
							<pre class="mermaid" id="diagram-source">$escapedMermaid</pre>
						</div>
					</div>
				</div>
				<script>
					mermaid.initialize({
						startOnLoad: false,
						theme: 'base',
						securityLevel: 'loose',
						flowchart: {
							htmlLabels: true,
							curve: 'basis'
						},
						themeVariables: {
							primaryTextColor: '#0f172a',
							lineColor: '#94a3b8',
							tertiaryColor: '#ffffff',
							clusterBkg: '#ffffff',
							clusterBorder: '#cbd5e1',
							fontFamily: 'Segoe UI'
						}
					});

					const source = document.getElementById('diagram-source');
					const viewport = document.getElementById('diagram-viewport');
					const zoomOutButton = document.getElementById('zoom-out');
					const zoomResetButton = document.getElementById('zoom-reset');
					const zoomInButton = document.getElementById('zoom-in');
					let zoomLevel = 1;
					let baseWidth = 0;
					let baseHeight = 0;

					function clamp(value, min, max) {
						return Math.min(max, Math.max(min, value));
					}

					function getSvg() {
						return source.querySelector('svg');
					}

					function measureSvg(svg) {
						const viewBox = svg.viewBox && svg.viewBox.baseVal;
						if (viewBox && viewBox.width && viewBox.height) {
							return { width: viewBox.width, height: viewBox.height };
						}
						const box = svg.getBBox();
						return {
							width: Math.max(box.width, 800),
							height: Math.max(box.height, 480),
						};
					}

					function applyZoom() {
						const svg = getSvg();
						if (!svg) {
							return;
						}

						if (!baseWidth || !baseHeight) {
							const measured = measureSvg(svg);
							baseWidth = measured.width;
							baseHeight = measured.height;
						}

						svg.style.width = (baseWidth * zoomLevel) + 'px';
						svg.style.height = (baseHeight * zoomLevel) + 'px';
						zoomResetButton.textContent = Math.round(zoomLevel * 100) + '%';
					}

					function setZoom(nextZoom) {
						const previousZoom = zoomLevel;
						zoomLevel = clamp(nextZoom, 0.4, 2.5);
						const ratio = previousZoom === 0 ? 1 : (zoomLevel / previousZoom);
						const previousScrollLeft = viewport.scrollLeft;
						const previousScrollTop = viewport.scrollTop;
						applyZoom();
						if (ratio !== 1) {
							viewport.scrollLeft = previousScrollLeft * ratio;
							viewport.scrollTop = previousScrollTop * ratio;
						}
					}

					zoomInButton.addEventListener('click', () => setZoom(zoomLevel + 0.15));
					zoomOutButton.addEventListener('click', () => setZoom(zoomLevel - 0.15));
					zoomResetButton.addEventListener('click', () => setZoom(1));

					viewport.addEventListener('wheel', (event) => {
						event.preventDefault();
						if (!event.ctrlKey) {
							viewport.scrollBy({
								left: -event.deltaX,
								top: -event.deltaY,
								behavior: 'auto'
							});
							return;
						}

						const zoomDelta = event.deltaY < 0 ? 0.12 : -0.12;
						setZoom(zoomLevel + zoomDelta);
					}, { passive: false });

					(async () => {
						await mermaid.run({ nodes: [source] });
						applyZoom();
					})();
				</script>
			</body>
			</html>
		""".trimIndent()
	}

	private fun buildEdges(nodes: List<DiagramNode>): List<DiagramEdge> {
		val ids = nodes.map { it.id }.toSet()
		return DEFAULT_EDGES
			.filter { edge -> edge.from in ids && edge.to in ids }
			.distinctBy { edge -> "${edge.from}|${edge.to}|${edge.label.orEmpty()}" }
	}

	private fun buildMermaid(nodes: List<DiagramNode>, edges: List<DiagramEdge>): String {
		if (nodes.isEmpty()) {
			return "graph TD\n    empty[\"No architecture groups detected\"]"
		}

		val builder = StringBuilder()
		builder.appendLine("graph TD")

		nodes.groupBy { it.surface }
			.toSortedMap(compareBy<String> { SURFACE_ORDER[it] ?: DEFAULT_SURFACE_ORDER }.thenBy { it.lowercase() })
			.forEach { (surface, surfaceNodes) ->
				builder.appendLine("    subgraph surface_${mermaidId(surface)}[\"${escapeMermaidLabel(surface)}\"]")
				surfaceNodes.sortedBy { it.title.lowercase() }.forEach { node ->
					builder.appendLine("        ${node.id}[\"${nodeLabel(node)}\"]")
				}
				builder.appendLine("    end")
			}

		edges.forEach { edge ->
			val edgeLabel = edge.label?.takeIf { it.isNotBlank() }
			if (edgeLabel != null) {
				builder.appendLine("    ${edge.from} -->|${escapeMermaidLabel(edgeLabel)}| ${edge.to}")
			} else {
				builder.appendLine("    ${edge.from} --> ${edge.to}")
			}
		}

		builder.appendLine("    classDef added fill:#E8F7ED,stroke:#2E8B57,color:#0F172A,stroke-width:2px;")
		builder.appendLine("    classDef modified fill:#FFF8DC,stroke:#C79016,color:#0F172A,stroke-width:2px;")
		builder.appendLine("    classDef stable fill:#FFFFFF,stroke:#94A3B8,color:#0F172A,stroke-width:1px;")

		nodes.forEach { node ->
			val className = when (node.status) {
				DiagramNodeStatus.ADDED -> "added"
				DiagramNodeStatus.MODIFIED -> "modified"
				DiagramNodeStatus.UNCHANGED -> "stable"
			}
			builder.appendLine("    class ${node.id} $className;")
		}

		return builder.toString().trim()
	}

	private fun classifyNode(
		relativePath: String,
		statuses: Map<String, DiagramNodeStatus>,
	): DiagramNode? {
		val normalized = relativePath.lowercase()
		val status = statuses[normalizePath(relativePath)] ?: DiagramNodeStatus.UNCHANGED

		return when {
			normalized.startsWith("jarvis-backend/app/api/") || normalized == "jarvis-backend/app/main.py" -> {
				node("backend_api", "Backend", "API", "Routes and websocket entry points", status)
			}

			normalized.startsWith("jarvis-backend/app/services/") || normalized.startsWith("jarvis-backend/app/tools/") -> {
				node("backend_services", "Backend", "Services", "Orchestration, memory, and integrations", status)
			}

			normalized.startsWith("jarvis-backend/app/agents/") || normalized.startsWith("jarvis-backend/app/graphs/") -> {
				node("backend_agents", "Backend", "Agents", "Repository and task execution flows", status)
			}

			normalized.startsWith("jarvis-backend/app/models/") -> {
				node("backend_models", "Backend", "Models", "Schemas, state, and shared contracts", status)
			}

			normalized.startsWith("jarvis-intellij-plugin/src/main/kotlin/") &&
				(normalized.contains("/ui/") || normalized.contains("/toolwindow/")) -> {
				node("plugin_ui", "IntelliJ Plugin", "UI", "Tool window and user interactions", status)
			}

			normalized.startsWith("jarvis-intellij-plugin/src/main/kotlin/") &&
				(normalized.contains("/services/") || normalized.contains("/network/")) -> {
				node("plugin_services", "IntelliJ Plugin", "Services", "Git, cache, and backend coordination", status)
			}

			normalized.startsWith("jarvis-intellij-plugin/src/main/kotlin/") && normalized.contains("/features/") -> {
				node("plugin_features", "IntelliJ Plugin", "Features", "IDE helpers and focused plugin flows", status)
			}

			normalized.startsWith("jarvis-web/src/voice/") -> {
				node("web_voice", "Web App", "Voice", "Voice capture and voice session UX", status)
			}

			normalized.startsWith("jarvis-web/src/shared/") -> {
				node("web_shared", "Web App", "Shared", "Reusable client-side primitives and services", status)
			}

			normalized.startsWith("jarvis-web/src/") -> {
				node("web_app", "Web App", "App", "Browser screens and feature flows", status)
			}

			normalized.startsWith("jarvis-desktop/src-tauri/") -> {
				node("desktop_shell", "Desktop App", "Shell", "Tauri runtime and desktop bridge", status)
			}

			normalized.startsWith("jarvis-desktop/src/") -> {
				node("desktop_ui", "Desktop App", "UI", "Desktop-facing frontend", status)
			}

			else -> null
		}
	}

	private fun node(
		id: String,
		surface: String,
		title: String,
		description: String,
		status: DiagramNodeStatus,
	): DiagramNode = DiagramNode(
		id = id,
		surface = surface,
		title = title,
		description = description,
		status = status,
	)

	private fun aggregateStatus(statuses: List<DiagramNodeStatus>): DiagramNodeStatus {
		return when {
			statuses.any { it == DiagramNodeStatus.ADDED } -> DiagramNodeStatus.ADDED
			statuses.any { it == DiagramNodeStatus.MODIFIED } -> DiagramNodeStatus.MODIFIED
			else -> DiagramNodeStatus.UNCHANGED
		}
	}

	private fun nodeLabel(node: DiagramNode): String {
		return escapeMermaidLabel("${node.title}<br/>${node.description}")
	}

	private fun mermaidId(value: String): String = value.lowercase().replace(Regex("[^a-z0-9]+"), "_").trim('_')

	private fun toRelativePath(projectRoot: String, file: VirtualFile): String? {
		val normalizedRoot = normalizePath(projectRoot)
		val normalizedPath = normalizePath(file.path)
		val prefix = "$normalizedRoot/"
		return when {
			normalizedPath == normalizedRoot -> file.name
			normalizedPath.startsWith(prefix) -> normalizedPath.removePrefix(prefix)
			else -> null
		}
	}

	private fun normalizePath(path: String): String = path.replace('\\', '/').trim('/')

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

	private fun escapeMermaidLabel(value: String): String {
		return value
			.replace("\\", "\\\\")
			.replace("\"", "&quot;")
	}

	companion object {
		private const val DEFAULT_SURFACE_ORDER = 99

		private val SURFACE_ORDER = mapOf(
			"Backend" to 0,
			"IntelliJ Plugin" to 1,
			"Web App" to 2,
			"Desktop App" to 3,
		)

		private val DEFAULT_EDGES = listOf(
			DiagramEdge(from = "plugin_ui", to = "plugin_services", label = "uses"),
			DiagramEdge(from = "plugin_features", to = "plugin_services", label = "uses"),
			DiagramEdge(from = "plugin_services", to = "backend_api", label = "calls"),
			DiagramEdge(from = "backend_api", to = "backend_services", label = "routes to"),
			DiagramEdge(from = "backend_services", to = "backend_agents", label = "coordinates"),
			DiagramEdge(from = "backend_services", to = "backend_models", label = "uses"),
			DiagramEdge(from = "backend_agents", to = "backend_models", label = "shares state"),
			DiagramEdge(from = "web_app", to = "web_shared", label = "uses"),
			DiagramEdge(from = "web_voice", to = "web_shared", label = "uses"),
			DiagramEdge(from = "web_app", to = "backend_api", label = "calls"),
			DiagramEdge(from = "web_voice", to = "backend_api", label = "streams to"),
			DiagramEdge(from = "desktop_ui", to = "desktop_shell", label = "runs in"),
			DiagramEdge(from = "desktop_shell", to = "backend_api", label = "calls"),
		)
	}
}
