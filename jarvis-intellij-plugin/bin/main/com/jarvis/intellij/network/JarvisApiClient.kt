package com.jarvis.intellij.network

import com.google.gson.Gson
import com.google.gson.JsonSyntaxException
import com.intellij.openapi.diagnostic.Logger
import com.jarvis.intellij.model.AnalyzeRequest
import com.jarvis.intellij.model.AnalyzeResponse
import java.io.IOException
import java.net.ConnectException
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.net.http.HttpTimeoutException
import java.nio.charset.StandardCharsets
import java.time.Duration

class JarvisApiClient(private val baseUrl: String = resolveBaseUrl()) {
    private val logger = Logger.getInstance(JarvisApiClient::class.java)
    private val gson = Gson()
    private val httpClient = HttpClient.newBuilder()
        .version(HttpClient.Version.HTTP_1_1)
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun analyzeFile(fileName: String, content: String, diff: String?): AnalyzeResponse {
        val endpoint = "$baseUrl/analyze"
        val requestBody = gson.toJson(
            AnalyzeRequest(
                fileName = fileName,
                content = content,
                diff = diff?.takeIf { it.isNotBlank() },
            ),
        )
        val request = HttpRequest.newBuilder()
            .uri(URI.create(endpoint))
            .header("Accept", "application/json")
            .header("Content-Type", "application/json; charset=UTF-8")
            .timeout(Duration.ofSeconds(30))
            .POST(HttpRequest.BodyPublishers.ofString(requestBody, StandardCharsets.UTF_8))
            .build()

        logger.info(
            "Calling Jarvis backend for $fileName at $endpoint (${content.length} chars, ${diff?.length ?: 0} diff chars)",
        )

        return try {
            val response = httpClient.send(request, HttpResponse.BodyHandlers.ofString())
            if (response.statusCode() !in 200..299) {
                val responseBody = response.body().trim()
                logger.warn(
                    "Jarvis backend returned HTTP ${response.statusCode()} for $fileName at $endpoint: ${summarize(responseBody)}",
                )
                throw JarvisApiException(buildErrorMessage(response.statusCode(), responseBody))
            }

            gson.fromJson(response.body(), AnalyzeResponse::class.java)
                ?: throw JarvisApiException("Jarvis backend returned an empty response.")
        } catch (exception: ConnectException) {
            throw JarvisApiException("Jarvis backend is unavailable at $baseUrl.", exception)
        } catch (exception: HttpTimeoutException) {
            throw JarvisApiException("Jarvis backend timed out while analyzing $fileName.", exception)
        } catch (exception: JsonSyntaxException) {
            throw JarvisApiException("Jarvis backend returned invalid JSON.", exception)
        } catch (exception: InterruptedException) {
            Thread.currentThread().interrupt()
            throw JarvisApiException("Jarvis request was interrupted.", exception)
        } catch (exception: IOException) {
            throw JarvisApiException(
                "Jarvis backend request failed: ${exception.message ?: "unknown error"}.",
                exception,
            )
        }
    }

    private fun buildErrorMessage(statusCode: Int, responseBody: String): String {
        val detail = summarize(responseBody)
        return if (detail.isBlank()) {
            "Jarvis backend returned HTTP $statusCode."
        } else {
            "Jarvis backend returned HTTP $statusCode: $detail"
        }
    }

    private fun summarize(responseBody: String, maxLength: Int = 300): String {
        if (responseBody.isBlank()) {
            return ""
        }

        val normalized = responseBody.replace('\n', ' ').replace("\r", " ").trim()
        return if (normalized.length <= maxLength) {
            normalized
        } else {
            normalized.take(maxLength) + "..."
        }
    }

    companion object {
        const val DEFAULT_BASE_URL = "http://localhost:8010"

        fun resolveBaseUrl(): String {
            val configuredUrl = System.getenv("JARVIS_BACKEND_URL")
                ?.trim()
                ?.takeIf { it.isNotEmpty() }
                ?: DEFAULT_BASE_URL

            return configuredUrl.removeSuffix("/")
        }
    }
}

class JarvisApiException(message: String, cause: Throwable? = null) : Exception(message, cause)
