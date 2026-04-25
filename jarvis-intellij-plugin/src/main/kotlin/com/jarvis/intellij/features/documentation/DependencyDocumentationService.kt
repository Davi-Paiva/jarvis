package com.jarvis.intellij.features.documentation

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.project.Project
import org.w3c.dom.Element
import java.nio.charset.StandardCharsets
import java.nio.file.FileVisitResult
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.nio.file.SimpleFileVisitor
import java.nio.file.attribute.BasicFileAttributes
import java.util.Locale

class DependencyDocumentationService(private val project: Project) {
    private val logger = Logger.getInstance(DependencyDocumentationService::class.java)

    fun collectDependencies(indicator: ProgressIndicator? = null): List<DependencyDocumentationEntry> {
        val basePath = project.basePath ?: return emptyList()
        val root = Paths.get(basePath)
        val manifests = findManifestFiles(root)

        val aggregated = linkedMapOf<String, MutableDependency>()

        manifests.forEachIndexed { index, manifestPath ->
            if (indicator != null) {
                indicator.text = "Scanning project manifests"
                indicator.text2 = root.relativize(manifestPath).toString().replace('\\', '/')
                indicator.fraction = if (manifests.isEmpty()) 1.0 else (index + 1).toDouble() / manifests.size
            }

            val manifestLabel = root.relativize(manifestPath).toString().replace('\\', '/')
            val discovered = parseManifest(manifestPath, manifestLabel)
            discovered.forEach { dependency ->
                val key = "${dependency.ecosystem.name}:${dependency.name.lowercase(Locale.getDefault())}"
                val existing = aggregated[key]
                if (existing == null) {
                    aggregated[key] = MutableDependency(
                        name = dependency.name,
                        version = dependency.version,
                        ecosystem = dependency.ecosystem,
                        manifests = linkedSetOf(dependency.manifestPath),
                    )
                } else {
                    if (existing.version.isNullOrBlank() && !dependency.version.isNullOrBlank()) {
                        existing.version = dependency.version
                    }
                    existing.manifests += dependency.manifestPath
                }
            }
        }

        return aggregated.values
            .map { mutable ->
                DependencyDocumentationEntry(
                    name = mutable.name,
                    version = mutable.version,
                    ecosystem = mutable.ecosystem,
                    documentationUrl = resolveDocumentationUrl(mutable),
                    manifests = mutable.manifests.toSortedSet(),
                )
            }
            .sortedWith(compareBy({ it.ecosystem.displayName }, { it.name.lowercase(Locale.getDefault()) }))
    }

    fun findDocumentationEntryForImport(
        importReference: String,
        dependencies: List<DependencyDocumentationEntry> = collectDependencies(),
    ): DependencyDocumentationEntry? {
        val normalizedImport = normalizeImportReference(importReference)
        if (normalizedImport.isBlank()) {
            return null
        }

        return dependencies
            .asSequence()
            .map { dependency -> dependency to scoreImportMatch(normalizedImport, dependency) }
            .filter { (_, score) -> score >= MIN_IMPORT_MATCH_SCORE }
            .maxWithOrNull(compareBy<Pair<DependencyDocumentationEntry, Int>> { it.second }.thenByDescending { it.first.name.length })
            ?.first
    }

    private fun findManifestFiles(root: Path): List<Path> {
        val manifests = mutableListOf<Path>()

        Files.walkFileTree(
            root,
            object : SimpleFileVisitor<Path>() {
                override fun preVisitDirectory(dir: Path, attrs: BasicFileAttributes): FileVisitResult {
                    val dirName = dir.fileName?.toString()?.lowercase(Locale.getDefault()) ?: return FileVisitResult.CONTINUE
                    return if (dir != root && EXCLUDED_DIRECTORIES.contains(dirName)) {
                        FileVisitResult.SKIP_SUBTREE
                    } else {
                        FileVisitResult.CONTINUE
                    }
                }

                override fun visitFile(file: Path, attrs: BasicFileAttributes): FileVisitResult {
                    if (!attrs.isRegularFile) {
                        return FileVisitResult.CONTINUE
                    }

                    val fileName = file.fileName.toString().lowercase(Locale.getDefault())
                    if (isSupportedManifest(fileName)) {
                        manifests.add(file)
                    }
                    return FileVisitResult.CONTINUE
                }
            },
        )

        return manifests
    }

    private fun isSupportedManifest(fileName: String): Boolean {
        return fileName in SUPPORTED_MANIFEST_FILES ||
            (fileName.startsWith("requirements") && fileName.endsWith(".txt"))
    }

    private fun parseManifest(path: Path, manifestLabel: String): List<RawDependency> {
        val fileName = path.fileName.toString().lowercase(Locale.getDefault())
        return try {
            when {
                fileName == "package.json" -> parsePackageJson(path, manifestLabel)
                fileName == "cargo.toml" -> parseCargoToml(path, manifestLabel)
                fileName == "pom.xml" -> parsePomXml(path, manifestLabel)
                fileName == "build.gradle" || fileName == "build.gradle.kts" -> parseGradle(path, manifestLabel)
                fileName == "pyproject.toml" -> parsePyProjectToml(path, manifestLabel)
                fileName.startsWith("requirements") && fileName.endsWith(".txt") -> parseRequirements(path, manifestLabel)
                else -> emptyList()
            }
        } catch (exception: Exception) {
            logger.warn("Failed to parse dependencies from $manifestLabel", exception)
            emptyList()
        }
    }

    private fun parsePackageJson(path: Path, manifestLabel: String): List<RawDependency> {
        val jsonContent = Files.readString(path)
        val root = JsonParser.parseString(jsonContent).asJsonObject

        val dependencies = mutableListOf<RawDependency>()
        NPM_DEPENDENCY_SECTIONS.forEach { section ->
            val sectionValue = root.get(section) ?: return@forEach
            if (!sectionValue.isJsonObject) {
                return@forEach
            }
            val sectionObject = sectionValue.asJsonObject
            sectionObject.entrySet().forEach { entry ->
                dependencies += RawDependency(
                    name = entry.key,
                    version = entry.value.takeIf { it.isJsonPrimitive }?.asString,
                    ecosystem = DependencyEcosystem.NPM,
                    manifestPath = manifestLabel,
                )
            }
        }

        return dependencies
    }

    private fun parseRequirements(path: Path, manifestLabel: String): List<RawDependency> {
        return Files.readAllLines(path).mapNotNull { rawLine ->
            val line = rawLine.substringBefore('#').trim()
            if (line.isBlank() || line.startsWith("-")) {
                return@mapNotNull null
            }

            val markerStripped = line.substringBefore(';').trim()
            val nameMatch = PYTHON_REQUIREMENT_NAME.find(markerStripped) ?: return@mapNotNull null
            val name = nameMatch.groupValues[1]
            val version = markerStripped.removePrefix(name).trim().ifBlank { null }

            RawDependency(
                name = name,
                version = version,
                ecosystem = DependencyEcosystem.PYPI,
                manifestPath = manifestLabel,
            )
        }
    }

    private fun parsePyProjectToml(path: Path, manifestLabel: String): List<RawDependency> {
        val lines = Files.readAllLines(path)
        val dependencies = mutableListOf<RawDependency>()

        var currentSection = ""
        var inProjectDependenciesArray = false
        val projectDependenciesBuffer = StringBuilder()

        lines.forEach { rawLine ->
            val lineWithoutComment = rawLine.substringBefore('#').trim()
            if (lineWithoutComment.isBlank()) {
                return@forEach
            }

            if (lineWithoutComment.startsWith("[") && lineWithoutComment.endsWith("]")) {
                currentSection = lineWithoutComment.removePrefix("[").removeSuffix("]")
                inProjectDependenciesArray = false
                return@forEach
            }

            if (currentSection == "project" && lineWithoutComment.startsWith("dependencies")) {
                val tail = lineWithoutComment.substringAfter('=', "").trim()
                if (tail.isNotBlank()) {
                    projectDependenciesBuffer.append(tail).append(' ')
                }
                inProjectDependenciesArray = true
            } else if (inProjectDependenciesArray) {
                projectDependenciesBuffer.append(lineWithoutComment).append(' ')
            }

            if (inProjectDependenciesArray && lineWithoutComment.contains("]")) {
                inProjectDependenciesArray = false
                extractQuotedRequirements(projectDependenciesBuffer.toString()).forEach { requirement ->
                    val parsed = parsePythonRequirement(requirement) ?: return@forEach
                    dependencies += RawDependency(
                        name = parsed.first,
                        version = parsed.second,
                        ecosystem = DependencyEcosystem.PYPI,
                        manifestPath = manifestLabel,
                    )
                }
                projectDependenciesBuffer.clear()
            }

            if (currentSection == "tool.poetry.dependencies") {
                val key = lineWithoutComment.substringBefore('=').trim()
                if (key.isBlank() || key == "python") {
                    return@forEach
                }
                val version = lineWithoutComment.substringAfter('=', "").trim().trim('"', '\'')
                dependencies += RawDependency(
                    name = key,
                    version = version.ifBlank { null },
                    ecosystem = DependencyEcosystem.PYPI,
                    manifestPath = manifestLabel,
                )
            }

            if (currentSection.startsWith("project.optional-dependencies")) {
                extractQuotedRequirements(lineWithoutComment).forEach { requirement ->
                    val parsed = parsePythonRequirement(requirement) ?: return@forEach
                    dependencies += RawDependency(
                        name = parsed.first,
                        version = parsed.second,
                        ecosystem = DependencyEcosystem.PYPI,
                        manifestPath = manifestLabel,
                    )
                }
            }
        }

        return dependencies
    }

    private fun parsePythonRequirement(rawRequirement: String): Pair<String, String?>? {
        val requirement = rawRequirement.substringBefore(';').trim()
        val nameMatch = PYTHON_REQUIREMENT_NAME.find(requirement) ?: return null
        val name = nameMatch.groupValues[1]
        val version = requirement.removePrefix(name).trim().ifBlank { null }
        return name to version
    }

    private fun parseCargoToml(path: Path, manifestLabel: String): List<RawDependency> {
        val dependencies = mutableListOf<RawDependency>()
        var inDependencySection = false

        Files.readAllLines(path).forEach { rawLine ->
            val line = rawLine.substringBefore('#').trim()
            if (line.isBlank()) {
                return@forEach
            }

            if (line.startsWith("[") && line.endsWith("]")) {
                val sectionName = line.removePrefix("[").removeSuffix("]").lowercase(Locale.getDefault())
                inDependencySection = sectionName == "dependencies" ||
                    sectionName == "dev-dependencies" ||
                    sectionName == "build-dependencies" ||
                    sectionName.endsWith(".dependencies") ||
                    sectionName.endsWith(".dev-dependencies") ||
                    sectionName.endsWith(".build-dependencies")
                return@forEach
            }

            if (!inDependencySection || !line.contains('=')) {
                return@forEach
            }

            val name = line.substringBefore('=').trim().trim('"', '\'')
            if (name.isBlank()) {
                return@forEach
            }

            val value = line.substringAfter('=').trim()
            dependencies += RawDependency(
                name = name,
                version = extractCargoVersion(value),
                ecosystem = DependencyEcosystem.CARGO,
                manifestPath = manifestLabel,
            )
        }

        return dependencies
    }

    private fun extractCargoVersion(rawValue: String): String? {
        if (rawValue.startsWith('"')) {
            return rawValue.removePrefix("\"").substringBefore('"').trim().ifBlank { null }
        }

        val match = CARGO_INLINE_VERSION.find(rawValue)
        return match?.groupValues?.getOrNull(1)?.trim()?.ifBlank { null }
    }

    private fun parsePomXml(path: Path, manifestLabel: String): List<RawDependency> {
        val factory = javax.xml.parsers.DocumentBuilderFactory.newInstance()
        val builder = factory.newDocumentBuilder()
        val document = builder.parse(path.toFile())
        val dependencyNodes = document.getElementsByTagName("dependency")

        val dependencies = mutableListOf<RawDependency>()
        for (index in 0 until dependencyNodes.length) {
            val node = dependencyNodes.item(index) as? Element ?: continue
            val groupId = childElementText(node, "groupId") ?: continue
            val artifactId = childElementText(node, "artifactId") ?: continue
            val version = childElementText(node, "version")

            dependencies += RawDependency(
                name = "$groupId:$artifactId",
                version = version,
                ecosystem = DependencyEcosystem.MAVEN,
                manifestPath = manifestLabel,
            )
        }

        return dependencies
    }

    private fun parseGradle(path: Path, manifestLabel: String): List<RawDependency> {
        val dependencies = mutableListOf<RawDependency>()

        Files.readAllLines(path).forEach { rawLine ->
            val line = rawLine.substringBefore("//").trim()
            GRADLE_COORDINATE_REGEX.findAll(line).forEach { match ->
                val group = match.groupValues[1]
                val artifact = match.groupValues[2]
                val version = match.groupValues.getOrNull(3)?.ifBlank { null }

                dependencies += RawDependency(
                    name = "$group:$artifact",
                    version = version,
                    ecosystem = DependencyEcosystem.GRADLE,
                    manifestPath = manifestLabel,
                )
            }
        }

        return dependencies
    }

    private fun childElementText(parent: Element, tagName: String): String? {
        val children = parent.getElementsByTagName(tagName)
        if (children.length == 0) {
            return null
        }
        val text = children.item(0)?.textContent?.trim().orEmpty()
        return text.ifBlank { null }
    }

    private fun resolveDocumentationUrl(dependency: MutableDependency): String {
        return when (dependency.ecosystem) {
            DependencyEcosystem.NPM -> "https://www.npmjs.com/package/${urlEncode(dependency.name)}"
            DependencyEcosystem.PYPI -> "https://pypi.org/project/${urlEncode(dependency.name)}/"
            DependencyEcosystem.CARGO -> "https://docs.rs/${urlEncode(dependency.name)}"
            DependencyEcosystem.MAVEN,
            DependencyEcosystem.GRADLE,
            -> {
                val (group, artifact) = splitCoordinate(dependency.name)
                if (group == null || artifact == null) {
                    "https://search.maven.org/search?q=${urlEncode(dependency.name)}"
                } else {
                    "https://search.maven.org/artifact/${urlEncode(group)}/${urlEncode(artifact)}"
                }
            }
        }
    }

    private fun splitCoordinate(name: String): Pair<String?, String?> {
        val parts = name.split(':')
        return if (parts.size >= 2) {
            parts[0] to parts[1]
        } else {
            null to null
        }
    }

    private fun scoreImportMatch(importReference: String, dependency: DependencyDocumentationEntry): Int {
        val dependencyName = dependency.name.lowercase(Locale.getDefault())
        return when (dependency.ecosystem) {
            DependencyEcosystem.NPM,
            DependencyEcosystem.PYPI,
            DependencyEcosystem.CARGO,
            -> scorePackageLikeMatch(importReference, dependencyName)

            DependencyEcosystem.MAVEN,
            DependencyEcosystem.GRADLE,
            -> scoreCoordinateMatch(importReference, dependencyName)
        }
    }

    private fun scorePackageLikeMatch(importReference: String, dependencyName: String): Int {
        val primaryModule = primaryImportModule(importReference)
        return when {
            dependencyName == importReference -> 150
            dependencyName == primaryModule -> 145
            importReference.startsWith("$dependencyName/") -> 140
            importReference.startsWith("$dependencyName.") -> 140
            importReference.startsWith("$dependencyName::") -> 140
            else -> 0
        }
    }

    private fun scoreCoordinateMatch(importReference: String, dependencyName: String): Int {
        if (dependencyName == importReference) {
            return 150
        }

        val segments = importReferenceSegments(importReference)
        val (group, artifact) = splitCoordinate(dependencyName)
        var score = 0

        group
            ?.lowercase(Locale.getDefault())
            ?.let { normalizedGroup ->
                if (
                    importReference == normalizedGroup ||
                    importReference.startsWith("$normalizedGroup.") ||
                    importReference.startsWith("$normalizedGroup::") ||
                    importReference.startsWith("$normalizedGroup/")
                ) {
                    score = maxOf(score, 145)
                }
            }

        artifact
            ?.lowercase(Locale.getDefault())
            ?.let { normalizedArtifact ->
                if (
                    importReference == normalizedArtifact ||
                    importReference.startsWith("$normalizedArtifact.") ||
                    importReference.startsWith("$normalizedArtifact::") ||
                    importReference.startsWith("$normalizedArtifact/")
                ) {
                    score = maxOf(score, 130)
                }
                if (normalizedArtifact.length >= MIN_ARTIFACT_SEGMENT_LENGTH && normalizedArtifact in segments) {
                    score = maxOf(score, 120)
                }
            }

        return score
    }

    private fun primaryImportModule(importReference: String): String {
        return when {
            importReference.startsWith("@") -> {
                val segments = importReference.split('/')
                if (segments.size >= 2) {
                    "${segments[0]}/${segments[1]}"
                } else {
                    importReference
                }
            }

            '/' in importReference -> importReference.substringBefore('/')
            "::" in importReference -> importReference.substringBefore("::")
            '.' in importReference -> importReference.substringBefore('.')
            else -> importReference
        }
    }

    private fun importReferenceSegments(importReference: String): Set<String> {
        return importReference
            .replace("::", ".")
            .replace('/', '.')
            .split('.')
            .map(String::trim)
            .filter { it.isNotBlank() }
            .toSet()
    }

    private fun normalizeImportReference(importReference: String): String {
        return importReference
            .trim()
            .removeSurrounding("\"")
            .removeSurrounding("'")
            .removeSuffix(";")
            .removeSuffix(".*")
            .substringBefore(" as ")
            .trim()
            .lowercase(Locale.getDefault())
    }

    private fun extractQuotedRequirements(raw: String): List<String> {
        return QUOTED_TEXT_REGEX.findAll(raw)
            .mapNotNull { match ->
                val first = match.groupValues.getOrNull(1).orEmpty()
                val second = match.groupValues.getOrNull(2).orEmpty()
                when {
                    first.isNotBlank() -> first
                    second.isNotBlank() -> second
                    else -> null
                }
            }
            .toList()
    }

    private fun urlEncode(value: String): String = java.net.URLEncoder.encode(value, StandardCharsets.UTF_8)

    private data class RawDependency(
        val name: String,
        val version: String?,
        val ecosystem: DependencyEcosystem,
        val manifestPath: String,
    )

    private data class MutableDependency(
        val name: String,
        var version: String?,
        val ecosystem: DependencyEcosystem,
        val manifests: MutableSet<String>,
    )

    companion object {
        private val SUPPORTED_MANIFEST_FILES = setOf(
            "package.json",
            "cargo.toml",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "pyproject.toml",
        )

        private val EXCLUDED_DIRECTORIES = setOf(
            ".git",
            ".idea",
            ".gradle",
            "node_modules",
            ".venv",
            "venv",
            "dist",
            "build",
            "target",
            "out",
        )

        private val NPM_DEPENDENCY_SECTIONS = listOf(
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies",
        )

        private val PYTHON_REQUIREMENT_NAME = Regex("^([A-Za-z0-9_.-]+)")
        private val CARGO_INLINE_VERSION = Regex("version\\s*=\\s*\"([^\"]+)\"")
        private val QUOTED_TEXT_REGEX = Regex("\"([^\"]+)\"|'([^']+)'")
        private val GRADLE_COORDINATE_REGEX = Regex("['\"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)(?::([^'\"]+))?['\"]")
        private const val MIN_IMPORT_MATCH_SCORE = 120
        private const val MIN_ARTIFACT_SEGMENT_LENGTH = 4
    }
}
