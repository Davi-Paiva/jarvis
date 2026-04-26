package com.jarvis.intellij.model

data class AnalyzeRequest(
    val fileName: String,
    val content: String,
    val diff: String? = null,
)

data class AnalyzeLineExplanation(
    val lineNumber: Int,
    val summary: String = "",
)

data class AnalyzeResponse(
    val summary: String = "",
    val steps: List<String> = emptyList(),
    val lineExplanations: List<AnalyzeLineExplanation> = emptyList(),
)
