package com.jarvis.intellij.services

import com.google.gson.Gson
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.jarvis.intellij.model.ArchitectureDiagram
import com.jarvis.intellij.model.DiagramEdge
import com.jarvis.intellij.model.DiagramNode
import com.jarvis.intellij.model.DiagramNodeStatus
import com.jarvis.intellij.model.GitDiagramSnapshot
import java.io.File

class DiagramService(
    private val fileService: FileService = FileService(),
) {
    private val logger = Logger.getInstance(DiagramService::class.java)
    private val gson = Gson()

    fun buildDiagram(
        project: Project,
        files: List<VirtualFile>,
        gitSnapshot: GitDiagramSnapshot,
    ): ArchitectureDiagram {
        val projectRoot = project.basePath ?: throw IllegalStateException("Project root is unavailable.")
        val fileDescriptors = files.mapNotNull { file ->
            buildDescriptor(projectRoot, file, gitSnapshot.statuses)
        }

        val entityDescriptors = buildEntityDescriptors(fileDescriptors)
        val projectColumns = entityDescriptors
            .map { it.project }
            .distinct()
            .sorted()
            .withIndex()
            .associate { it.value to it.index }
        val projectStatuses = entityDescriptors
            .groupBy { it.project }
            .mapValues { (_, descriptors) -> aggregateStatus(descriptors.map { it.status }) }

        val projectNodes = projectColumns.entries
            .sortedBy { it.value }
            .map { (projectName, columnIndex) ->
                DiagramNode(
                    id = projectName,
                    label = projectName,
                    path = projectName,
                    folder = projectName,
                    color = projectStatuses[projectName]?.colorHex ?: DiagramNodeStatus.UNCHANGED.colorHex,
                    status = projectStatuses[projectName] ?: DiagramNodeStatus.UNCHANGED,
                    x = HORIZONTAL_PADDING + columnIndex * PROJECT_COLUMN_WIDTH,
                    y = PROJECT_Y,
                )
            }

        val entityNodes = entityDescriptors
            .sortedWith(compareBy<EntityDescriptor> { it.project }.thenBy { it.path.lowercase() })
            .groupBy { it.project }
            .flatMap { (projectName, descriptors) ->
                descriptors.sortedBy { it.path.lowercase() }.mapIndexed { index, descriptor ->
                    DiagramNode(
                        id = descriptor.path,
                        label = descriptor.label,
                        path = descriptor.path,
                        folder = descriptor.project,
                        color = descriptor.status.colorHex,
                        status = descriptor.status,
                        x = HORIZONTAL_PADDING + (projectColumns[projectName] ?: 0) * PROJECT_COLUMN_WIDTH,
                        y = ENTITY_START_Y + index * ENTITY_ROW_HEIGHT,
                    )
                }
            }

        val nodes = projectNodes + entityNodes
        val pathLookup = fileDescriptors.associateBy { normalizeLookupKey(it.relativePath) }
        val importIndex = buildImportIndex(fileDescriptors)
        val edges = buildEdges(fileDescriptors, entityDescriptors, pathLookup, importIndex)

        logger.info(
            "Built structural architecture diagram for ${project.name}: ${nodes.size} nodes, ${edges.size} edges",
        )
        return ArchitectureDiagram(nodes = nodes, edges = edges)
    }

    fun renderHtml(projectName: String, diagram: ArchitectureDiagram): String {
        val entityCount = diagram.nodes.count { it.path.contains('/') }
        val changedCount = diagram.nodes.count { it.path.contains('/') && it.status != DiagramNodeStatus.UNCHANGED }
        val diagramJson = gson.toJson(diagram)
        val title = escapeHtml(projectName)

        return """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8" />
                <style>
                    :root {
                        color-scheme: light;
                        --bg-top: #f8fbff;
                        --bg-bottom: #eef4ff;
                        --panel: rgba(255, 255, 255, 0.88);
                        --panel-border: rgba(148, 163, 184, 0.25);
                        --edge: rgba(148, 163, 184, 0.55);
                        --text: #0f172a;
                        --muted: #475569;
                        --shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
                    }

                    * {
                        box-sizing: border-box;
                    }

                    body {
                        margin: 0;
                        min-height: 100vh;
                        font-family: "Segoe UI", "SF Pro Text", sans-serif;
                        color: var(--text);
                        background: linear-gradient(180deg, var(--bg-top), var(--bg-bottom));
                    }

                    .page {
                        padding: 20px;
                    }

                    .header {
                        display: flex;
                        justify-content: space-between;
                        gap: 16px;
                        align-items: flex-start;
                        margin-bottom: 16px;
                    }

                    .title {
                        margin: 0;
                        font-size: 28px;
                        font-weight: 700;
                    }

                    .subtitle {
                        margin: 6px 0 0;
                        color: var(--muted);
                        font-size: 13px;
                    }

                    .legend {
                        display: flex;
                        gap: 10px;
                        flex-wrap: wrap;
                        justify-content: flex-end;
                    }

                    .legend-item {
                        display: inline-flex;
                        align-items: center;
                        gap: 8px;
                        padding: 8px 12px;
                        border-radius: 999px;
                        background: var(--panel);
                        border: 1px solid var(--panel-border);
                        font-size: 12px;
                        color: var(--muted);
                        box-shadow: var(--shadow);
                    }

                    .legend-swatch {
                        width: 10px;
                        height: 10px;
                        border-radius: 999px;
                    }

                    .canvas-wrap {
                        height: calc(100vh - 110px);
                        overflow: auto;
                        border-radius: 28px;
                        border: 1px solid var(--panel-border);
                        background: rgba(255, 255, 255, 0.55);
                        box-shadow: var(--shadow);
                    }

                    .diagram {
                        position: relative;
                        min-width: 100%;
                        min-height: 100%;
                        padding: 24px;
                        background-image:
                            radial-gradient(circle at top left, rgba(80, 120, 255, 0.08), transparent 28%),
                            linear-gradient(90deg, rgba(148, 163, 184, 0.07) 1px, transparent 1px),
                            linear-gradient(rgba(148, 163, 184, 0.07) 1px, transparent 1px);
                        background-size: auto, 28px 28px, 28px 28px;
                    }

                    .folder-label {
                        position: absolute;
                        top: 96px;
                        padding: 8px 12px;
                        border-radius: 999px;
                        background: rgba(15, 23, 42, 0.82);
                        color: white;
                        font-size: 12px;
                        letter-spacing: 0.02em;
                    }

                    .node {
                        position: absolute;
                        width: 220px;
                        min-height: 68px;
                        padding: 12px 14px;
                        border-radius: 18px;
                        background: rgba(255, 255, 255, 0.94);
                        border: 2px solid transparent;
                        box-shadow: 0 16px 32px rgba(15, 23, 42, 0.12);
                        backdrop-filter: blur(8px);
                    }

                    .node-name {
                        font-size: 14px;
                        font-weight: 700;
                        line-height: 1.25;
                    }

                    .node-path {
                        margin-top: 6px;
                        font-size: 11px;
                        color: var(--muted);
                        line-height: 1.35;
                        word-break: break-word;
                    }

                    .node-badge {
                        display: inline-block;
                        margin-top: 8px;
                        padding: 4px 8px;
                        border-radius: 999px;
                        font-size: 10px;
                        font-weight: 700;
                        text-transform: uppercase;
                        letter-spacing: 0.05em;
                        color: #0f172a;
                        background: rgba(148, 163, 184, 0.15);
                    }

                    .project-node {
                        background: rgba(15, 23, 42, 0.92);
                        color: white;
                        min-height: 74px;
                        box-shadow: 0 24px 44px rgba(15, 23, 42, 0.22);
                    }

                    .project-node .node-path {
                        color: rgba(255, 255, 255, 0.72);
                    }

                    svg {
                        position: absolute;
                        inset: 0;
                        width: 100%;
                        height: 100%;
                        overflow: visible;
                    }
                </style>
            </head>
            <body>
                <div class="page">
                    <div class="header">
                        <div>
                            <h1 class="title">$title Architecture Diagram</h1>
                            <p class="subtitle">$entityCount structural entities, $changedCount highlighted areas, ${diagram.edges.size} relationships</p>
                        </div>
                        <div class="legend">
                            <div class="legend-item"><span class="legend-swatch" style="background:#32c766"></span>New structural area</div>
                            <div class="legend-item"><span class="legend-swatch" style="background:#f5c451"></span>Changed area</div>
                            <div class="legend-item"><span class="legend-swatch" style="background:#8d99ae"></span>Stable area</div>
                        </div>
                    </div>
                    <div class="canvas-wrap">
                        <div class="diagram" id="diagram"></div>
                    </div>
                </div>
                <script>
                    const diagramData = $diagramJson;
                    const diagram = document.getElementById('diagram');
                    const nodeWidth = 220;
                    const nodeHeight = 74;
                    const width = Math.max(1100, ...diagramData.nodes.map(node => node.x + nodeWidth + 160));
                    const height = Math.max(680, ...diagramData.nodes.map(node => node.y + nodeHeight + 140));
                    diagram.style.width = width + 'px';
                    diagram.style.height = height + 'px';

                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
                    svg.setAttribute('aria-hidden', 'true');
                    diagram.appendChild(svg);

                    const nodesById = Object.fromEntries(diagramData.nodes.map(node => [node.id, node]));
                    const folders = new Map();

                    diagramData.nodes.forEach(node => {
                        if (!folders.has(node.folder)) {
                            folders.set(node.folder, node.x);
                        }
                    });

                    folders.forEach((x, folder) => {
                        const label = document.createElement('div');
                        label.className = 'folder-label';
                        label.style.left = x + 'px';
                        label.textContent = folder;
                        diagram.appendChild(label);
                    });

                    diagramData.edges.forEach(edge => {
                        const from = nodesById[edge.from];
                        const to = nodesById[edge.to];
                        if (!from || !to) {
                            return;
                        }

                        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                        line.setAttribute('x1', String(from.x + nodeWidth));
                        line.setAttribute('y1', String(from.y + nodeHeight / 2));
                        line.setAttribute('x2', String(to.x));
                        line.setAttribute('y2', String(to.y + nodeHeight / 2));
                        line.setAttribute('stroke', edge.kind === 'structure' ? 'rgba(148, 163, 184, 0.35)' : 'rgba(59, 130, 246, 0.55)');
                        line.setAttribute('stroke-width', edge.kind === 'structure' ? '1.5' : '2.25');
                        line.setAttribute('stroke-linecap', 'round');
                        svg.appendChild(line);
                    });

                    diagramData.nodes.forEach(node => {
                        const element = document.createElement('div');
                        element.className = 'node';
                        if (!node.path.includes('/')) {
                            element.classList.add('project-node');
                        }
                        element.style.left = node.x + 'px';
                        element.style.top = node.y + 'px';
                        element.style.borderColor = node.color;
                        element.innerHTML =
                            '<div class="node-name">' + escapeHtml(node.label) + '</div>' +
                            '<div class="node-path">' + escapeHtml(node.path) + '</div>' +
                            '<div class="node-badge">' + node.status + '</div>';
                        element.title = node.path;
                        diagram.appendChild(element);
                    });

                    function escapeHtml(value) {
                        return String(value)
                            .replaceAll('&', '&amp;')
                            .replaceAll('<', '&lt;')
                            .replaceAll('>', '&gt;')
                            .replaceAll('"', '&quot;');
                    }
                </script>
            </body>
            </html>
        """.trimIndent()
    }

    private fun buildDescriptor(
        projectRoot: String,
        file: VirtualFile,
        statuses: Map<String, DiagramNodeStatus>,
    ): FileDescriptor? {
        val relativePath = toRelativePath(projectRoot, file) ?: return null
        val content = try {
            fileService.readFileContent(file)
        } catch (_: Exception) {
            ""
        }

        return FileDescriptor(
            file = file,
            relativePath = relativePath,
            content = content,
            status = statuses[relativePath] ?: DiagramNodeStatus.UNCHANGED,
            importKeys = buildImportKeys(relativePath, content),
        )
    }

    private fun buildEntityDescriptors(fileDescriptors: List<FileDescriptor>): List<EntityDescriptor> {
        return fileDescriptors
            .groupBy { deriveEntityPath(it.relativePath) }
            .map { (entityPath, members) ->
                val project = entityPath.substringBefore('/')
                EntityDescriptor(
                    path = entityPath,
                    project = project,
                    label = buildEntityLabel(entityPath),
                    status = aggregateStatus(members.map { it.status }),
                )
            }
            .sortedWith(compareBy<EntityDescriptor> { it.project }.thenBy { it.path.lowercase() })
    }

    private fun buildImportIndex(descriptors: List<FileDescriptor>): Map<String, String> {
        val index = linkedMapOf<String, String>()
        descriptors.forEach { descriptor ->
            descriptor.importKeys.forEach { key ->
                index.putIfAbsent(key, descriptor.relativePath)
            }
        }
        return index
    }

    private fun buildEdges(
        fileDescriptors: List<FileDescriptor>,
        entityDescriptors: List<EntityDescriptor>,
        pathLookup: Map<String, FileDescriptor>,
        importIndex: Map<String, String>,
    ): List<DiagramEdge> {
        val entityLookup = fileDescriptors.associate { it.relativePath to deriveEntityPath(it.relativePath) }
        val entityPaths = entityDescriptors.map { it.path }.toSet()
        val edges = linkedSetOf<DiagramEdge>()

        entityDescriptors.forEach { entity ->
            if (entityPaths.contains(entity.path) && entity.project != entity.path) {
                edges += DiagramEdge(from = entity.project, to = entity.path, kind = "structure")
            }
        }

        fileDescriptors.forEach { descriptor ->
            collectImportCandidates(descriptor).take(MAX_EDGES_PER_FILE).forEach { candidate ->
                val targetPath = resolveImport(descriptor, candidate, pathLookup, importIndex) ?: return@forEach
                val sourceEntity = entityLookup[descriptor.relativePath] ?: return@forEach
                val targetEntity = entityLookup[targetPath] ?: return@forEach
                if (sourceEntity != targetEntity) {
                    edges += DiagramEdge(from = sourceEntity, to = targetEntity, kind = "flow")
                }
            }
        }

        return edges.toList()
    }

    private fun collectImportCandidates(descriptor: FileDescriptor): List<String> {
        val candidates = linkedSetOf<String>()
        descriptor.content.lineSequence().forEach { line ->
            val trimmedLine = line.trim()
            if (trimmedLine.startsWith("import ") || trimmedLine.startsWith("from ") || trimmedLine.contains("require(")) {
                RELATIVE_IMPORT_REGEX.findAll(trimmedLine).forEach { match ->
                    candidates += match.groupValues[1]
                }

                DIRECT_IMPORT_REGEX.find(trimmedLine)?.let { match ->
                    candidates += match.groupValues[1]
                }

                FROM_IMPORT_REGEX.find(trimmedLine)?.let { match ->
                    val module = match.groupValues[1]
                    candidates += module
                    match.groupValues[2]
                        .split(',')
                        .map(String::trim)
                        .filter { it.isNotEmpty() && it != "*" }
                        .forEach { importedName ->
                            candidates += "$module.$importedName"
                        }
                }
            }
        }
        return candidates.toList()
    }

    private fun resolveImport(
        descriptor: FileDescriptor,
        candidate: String,
        pathLookup: Map<String, FileDescriptor>,
        importIndex: Map<String, String>,
    ): String? {
        return if (candidate.startsWith("./") || candidate.startsWith("../")) {
            resolveRelativeImport(descriptor.relativePath, candidate, pathLookup)
        } else {
            importIndex[normalizeLookupKey(candidate)]
        }
    }

    private fun resolveRelativeImport(
        sourcePath: String,
        importPath: String,
        pathLookup: Map<String, FileDescriptor>,
    ): String? {
        val sourceDirectory = sourcePath.substringBeforeLast('/', "")
        val basePath = normalizePath(File(sourceDirectory, importPath).path)
        val normalizedBasePath = normalizeLookupKey(basePath)

        pathLookup[normalizedBasePath]?.let { return it.relativePath }

        if (basePath.contains('.')) {
            return null
        }

        COMMON_IMPORT_SUFFIXES.forEach { suffix ->
            val directPath = normalizeLookupKey(basePath + suffix)
            pathLookup[directPath]?.let { return it.relativePath }

            val indexPath = normalizeLookupKey("$basePath/index$suffix")
            pathLookup[indexPath]?.let { return it.relativePath }
        }

        return null
    }

    private fun buildImportKeys(relativePath: String, content: String): Set<String> {
        val keys = linkedSetOf<String>()
        val noExtension = relativePath.substringBeforeLast('.', relativePath)
        val fileNameWithoutExtension = File(relativePath).nameWithoutExtension

        keys += normalizeLookupKey(relativePath)
        keys += normalizeLookupKey(noExtension)
        keys += normalizeLookupKey(fileNameWithoutExtension)

        PACKAGE_REGEX.find(content)?.groupValues?.getOrNull(1)?.let { packageName ->
            keys += normalizeLookupKey("$packageName.$fileNameWithoutExtension")
        }

        SOURCE_ROOT_MARKERS.forEach { marker ->
            val markerIndex = relativePath.indexOf(marker)
            if (markerIndex >= 0) {
                val suffix = relativePath.substring(markerIndex + marker.length)
                val dotted = suffix.substringBeforeLast('.', suffix).replace('/', '.')
                val normalized = normalizeLookupKey(dotted)
                if (normalized.isNotBlank()) {
                    keys += normalized
                    if (normalized.endsWith(".__init__")) {
                        keys += normalized.removeSuffix(".__init__")
                    }
                }
            }
        }

        return keys.filter { it.isNotBlank() }.toSet()
    }

    private fun deriveEntityPath(relativePath: String): String {
        val segments = relativePath.split('/').filter { it.isNotBlank() }
        if (segments.isEmpty()) {
            return ROOT_LABEL
        }

        val project = segments.first()
        val directories = segments.drop(1).dropLast(1)
        val fileName = segments.last()
        if (directories.isEmpty()) {
            return "$project/${classifyRootFile(fileName)}"
        }

        val cleanedDirectories = directories.filterNot { it in STRUCTURE_NOISE_SEGMENTS }
        val significantDirectories = cleanedDirectories.filterNot { it in PACKAGE_NAMESPACE_SEGMENTS }
        val primary = significantDirectories.firstOrNull() ?: cleanedDirectories.firstOrNull() ?: directories.last()

        if (primary in DEEP_GROUP_SEGMENTS) {
            val next = significantDirectories.dropWhile { it != primary }.drop(1).firstOrNull()
            if (next != null) {
                return "$project/$primary/$next"
            }
        }

        return "$project/$primary"
    }

    private fun buildEntityLabel(entityPath: String): String {
        val segments = entityPath.split('/').filter { it.isNotBlank() }
        if (segments.size <= 1) {
            return entityPath
        }

        return when {
            segments.size >= 3 && segments[1] in COMPOSITE_LABEL_SEGMENTS -> "${segments[1]}/${segments[2]}"
            else -> segments.last()
        }
    }

    private fun classifyRootFile(fileName: String): String {
        val normalized = fileName.lowercase()
        return when {
            normalized in ENTRYPOINT_FILE_NAMES -> "entrypoints"
            normalized in CONFIG_FILE_NAMES || normalized.endsWith(".json") || normalized.endsWith(".toml") -> "config"
            normalized.endsWith(".md") -> "docs"
            else -> "root"
        }
    }

    private fun aggregateStatus(statuses: List<DiagramNodeStatus>): DiagramNodeStatus {
        return when {
            statuses.any { it == DiagramNodeStatus.ADDED } -> DiagramNodeStatus.ADDED
            statuses.any { it == DiagramNodeStatus.MODIFIED } -> DiagramNodeStatus.MODIFIED
            else -> DiagramNodeStatus.UNCHANGED
        }
    }

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

    private fun normalizePath(path: String): String = path.replace('\\', '/')

    private fun normalizeLookupKey(path: String): String = normalizePath(path).lowercase()

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

    private data class FileDescriptor(
        val file: VirtualFile,
        val relativePath: String,
        val content: String,
        val status: DiagramNodeStatus,
        val importKeys: Set<String>,
    )

    private data class EntityDescriptor(
        val path: String,
        val project: String,
        val label: String,
        val status: DiagramNodeStatus,
    )

    companion object {
        private const val ROOT_LABEL = "Project root"
        private const val HORIZONTAL_PADDING = 120
        private const val PROJECT_Y = 20
        private const val ENTITY_START_Y = 140
        private const val PROJECT_COLUMN_WIDTH = 320
        private const val ENTITY_ROW_HEIGHT = 96
        private const val MAX_EDGES_PER_FILE = 8

        private val STRUCTURE_NOISE_SEGMENTS = setOf(
            "src",
            "main",
            "kotlin",
            "java",
            "python",
            "resources",
            "gen",
            "public",
        )

        private val PACKAGE_NAMESPACE_SEGMENTS = setOf(
            "com",
            "org",
            "io",
            "net",
            "dev",
            "jarvis",
            "intellij",
        )

        private val DEEP_GROUP_SEGMENTS = setOf(
            "app",
            "features",
            "voice",
            "components",
            "shared",
            "src-tauri",
        )

        private val COMPOSITE_LABEL_SEGMENTS = setOf(
            "app",
            "features",
            "voice",
            "components",
            "shared",
            "src-tauri",
        )

        private val ENTRYPOINT_FILE_NAMES = setOf(
            "main.py",
            "main.tsx",
            "main.ts",
            "main.rs",
            "app.tsx",
            "app.ts",
            "plugin.xml",
        )

        private val CONFIG_FILE_NAMES = setOf(
            "package.json",
            "cargo.toml",
            "tauri.conf.json",
            "vite.config.ts",
            "vite.config.js",
            "eslint.config.js",
            "tsconfig.json",
            "tsconfig.app.json",
            "tsconfig.node.json",
            "requirements.txt",
            "build.gradle.kts",
            "gradle.properties",
            ".gitignore",
            ".env",
        )

        private val COMMON_IMPORT_SUFFIXES = listOf(
            ".kt",
            ".java",
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
        )

        private val SOURCE_ROOT_MARKERS = listOf(
            "src/main/kotlin/",
            "src/main/java/",
            "src/main/python/",
            "src/",
            "app/",
            "tests/",
        )

        private val PACKAGE_REGEX = Regex("^\\s*package\\s+([A-Za-z0-9_.]+)", setOf(RegexOption.MULTILINE))
        private val DIRECT_IMPORT_REGEX = Regex("^\\s*import\\s+([A-Za-z0-9_.]+)")
        private val FROM_IMPORT_REGEX = Regex("^\\s*from\\s+([A-Za-z0-9_.]+)\\s+import\\s+([A-Za-z0-9_.*, ]+)")
        private val RELATIVE_IMPORT_REGEX = Regex("['\"]((?:\\./|\\.\\./)[^'\"]+)['\"]")
    }
}