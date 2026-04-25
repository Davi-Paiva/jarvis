package com.jarvis.intellij.features.documentation

enum class DependencyEcosystem(val displayName: String) {
    NPM("npm"),
    PYPI("PyPI"),
    CARGO("Cargo"),
    MAVEN("Maven"),
    GRADLE("Gradle"),
}

data class DependencyDocumentationEntry(
    val name: String,
    val version: String?,
    val ecosystem: DependencyEcosystem,
    val documentationUrl: String,
    val manifests: Set<String>,
) {
    fun searchableText(): String = buildString {
        append(name.lowercase())
        append(' ')
        append(ecosystem.displayName.lowercase())
        version?.takeIf { it.isNotBlank() }?.let {
            append(' ')
            append(it.lowercase())
        }
        manifests.forEach { manifest ->
            append(' ')
            append(manifest.lowercase())
        }
    }
}
