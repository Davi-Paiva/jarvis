# Jarvis IntelliJ Plugin

Minimal IntelliJ Platform plugin scaffold for reviewing and understanding code with Jarvis.

## What is included

- Kotlin-based IntelliJ plugin project
- Tool Window named `Jarvis Assistant` on the right side of the IDE
- `Analyze Project` button to collect project files
- File list panel
- Async HTTP integration with `POST http://localhost:3000/analyze`
- Response rendering with summary and step-by-step explanations
- `Next Step` button to iterate through explanation steps
- Placeholder packages for future describe, diagram, documentation, and execution-explainer features

## Run locally

1. Open this folder as a Gradle project in IntelliJ IDEA.
2. Start the Jarvis backend on `http://localhost:8000`.
3. Run the Gradle `runIde` task.
4. In the sandbox IDE, open any project and use the `Jarvis Assistant` tool window.

## Project structure

- `src/main/kotlin/com/jarvis/intellij/toolwindow`: tool window registration
- `src/main/kotlin/com/jarvis/intellij/ui`: Swing UI
- `src/main/kotlin/com/jarvis/intellij/services`: file access and orchestration
- `src/main/kotlin/com/jarvis/intellij/network`: backend HTTP client
- `src/main/kotlin/com/jarvis/intellij/features`: placeholder packages for future features
- `src/main/resources/META-INF/plugin.xml`: plugin registration
