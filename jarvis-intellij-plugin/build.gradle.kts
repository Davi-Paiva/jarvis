import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

plugins {
    kotlin("jvm") version "1.9.24"
    id("org.jetbrains.intellij") version "1.17.4"
}

group = "com.jarvis.intellij"
version = "0.1.0"

repositories {
    mavenCentral()
}

dependencies {
    implementation("com.google.code.gson:gson:2.11.0")
}

intellij {
    version.set("2024.1")
    type.set("IC")
    plugins.set(emptyList())
}

tasks {
    withType<KotlinCompile>().configureEach {
        kotlinOptions {
            jvmTarget = "17"
            freeCompilerArgs = freeCompilerArgs + "-Xjvm-default=all"
        }
    }

    patchPluginXml {
        sinceBuild.set("241")
        untilBuild.set("241.*")
    }

    runIde {
        autoReloadPlugins.set(true)
    }
}

kotlin {
    jvmToolchain(17)
}
