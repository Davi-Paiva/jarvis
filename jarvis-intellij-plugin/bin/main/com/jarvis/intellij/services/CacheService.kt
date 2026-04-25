package com.jarvis.intellij.services

import com.google.gson.Gson
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.jarvis.intellij.model.CachedDiagram
import java.io.File
import java.io.IOException

class CacheService {
    private val logger = Logger.getInstance(CacheService::class.java)
    private val gson = Gson()

    fun load(project: Project): CachedDiagram? {
        val cacheFile = cacheFile(project)
        if (!cacheFile.exists()) {
            return null
        }

        return try {
            cacheFile.reader(Charsets.UTF_8).use { reader ->
                gson.fromJson(reader, CachedDiagram::class.java)
            }
        } catch (exception: Exception) {
            logger.warn("Failed to read cached diagram for ${project.name}", exception)
            null
        }
    }

    fun save(project: Project, cachedDiagram: CachedDiagram) {
        val cacheFile = cacheFile(project)
        try {
            cacheFile.parentFile?.mkdirs()
            cacheFile.writeText(gson.toJson(cachedDiagram), Charsets.UTF_8)
        } catch (exception: IOException) {
            logger.warn("Failed to write diagram cache for ${project.name}", exception)
        }
    }

    private fun cacheFile(project: Project): File {
        val cacheDir = File(System.getProperty("java.io.tmpdir"), "jarvis-assistant-diagrams")
        return File(cacheDir, "${project.locationHash}.json")
    }
}