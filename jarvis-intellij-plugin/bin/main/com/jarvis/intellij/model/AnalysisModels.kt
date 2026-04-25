package com.jarvis.intellij.model

data class AnalyzeRequest(
    val fileName: String,
    val content: String,
    val diff: String? = null,
)

data class AnalyzeResponse(
    val summary: String = "",
    val steps: List<String> = emptyList(),
)
