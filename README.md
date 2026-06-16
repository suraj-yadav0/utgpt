# UTGPT

An offline AI chat application built specifically for Ubuntu Touch, allowing users to run lightweight Large Language Models (LLMs) directly on their mobile device.

## Features

- Local Model Manager: Download and manage lightweight GGUF models (such as Qwen2.5, TinyLlama, and SmolLM2) directly in the application.
- Dual Model Selector: Seamlessly switch active models from either the main Chat screen header or the Settings page.
- Interactive Inference Control: Stop active text generation at any time to conserve CPU cycles, battery, and tokens.
- Rich Text Responses: Renders response output using Markdown formatting for code blocks, headers, and lists.
- Copy to Clipboard: Copy assistant messages instantly with visual confirmation feedback.
- Animated Thinking State: Displays a dynamic thinking indicator while waiting for the model to prepare the first token.
- Local Execution: Run chats entirely offline, keeping conversations private.

## Architecture

The application is structured into three primary layers:

1. **Frontend (QML & Lomiri Components)**:
   - Implements the user interface, incorporating native Ubuntu Touch design tokens and system icons.
   - Manages frontend states like inference progress, model selection, and navigation.

2. **Backend Bridge (PyOtherSide)**:
   - Acts as a bidirectional bridge between the QML frontend and the Python backend runtime.
   - Pushes token updates and model download statuses to QML asynchronously.

3. **Inference & Management Backend (Python)**:
   - Downloads and maintains the inference engine (`llama-cli`) and downloaded GGUF models.
   - Executes model inference by spawning `llama-cli` as a subprocess.
   - Runs blocking operations (such as inference stdout polling and network downloads) inside dedicated background threads to prevent UI freezes.
   - Implements a thread-safe registry of active subprocesses, enabling instant termination upon user request.

## How It Works

1. **Initialization**: On startup, the application verifies the existence of the local `llama-cli` binary. If not found, it downloads a compatible release in the background.
2. **Model Download**: GGUF models are fetched directly from Hugging Face repositories over HTTPS and saved to the application's local sandbox storage.
3. **Chat Inference**:
   - Submitting a query appends user input to the chat list and triggers a call to the Python backend.
   - The backend spins up a background thread and executes `llama-cli` with the prompt.
   - The thread reads characters from the subprocess stdout pipe in real time, emitting tokens back to the QML model.
   - If the user taps "Stop", a concurrent request is processed, terminating the registered subprocess immediately and preserving the response generated up to that point.

## Credits

- App icon designed by [Rikas Dzihab](https://www.flaticon.com/authors/rikas-dzihab) from Flaticon.

## License

Copyright (C) 2026 Suraj Yadav

Licensed under the MIT License. See the LICENSE file for details.
