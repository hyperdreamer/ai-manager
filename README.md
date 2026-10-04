# ai-manager

Desktop administration GUI built with **PyQt6** for managing AI provider configurations, discovering models dynamically via `/v1/models` endpoints, and controlling local service supervision for backend applications (`ai-grammar`, `textkit`, `yt2txt`).

## Features

- ⚡ **Master-Detail Layout**: View all managed backends in a sleek left sidebar with real-time status dots (Running, Stopped, Restarting) and port indicators.
- 🔄 **Dynamic Model Discovery**: Fetch available models on-demand from any OpenAI-compatible provider (`/v1/models` and `/models`) with background non-blocking execution and race-condition prevention.
- 📝 **Round-Trip YAML Preservation**: Safely updates `config.yaml` using `ruamel.yaml`, preserving original inline comments, formatting, and commented-out model blocks with atomic temp-file replacement and automatic `.bak` backups.
- ⚙️ **Split Model Support**: Intelligently manages single unified models as well as split OCR/Text model configurations (e.g. for `textkit`).
- 🚀 **`ai-backends` Supervisor Control**: Seamless integration with the supervisor daemon to check status and trigger one-click restarts (`ai-backends restart <app>`).
- 🌓 **Light and Dark Themes**: Switch themes dynamically at runtime with settings persisted to `~/.config/ai-manager/settings.json`.
- 💾 **Dirty State Protection**: Tracks in-memory unsaved drafts per application, shows asterisk (`*`) indicators on sidebar tabs, and prompts before discarding changes on window close.

## Applications Managed

- `ai-grammar` (port 8766)
- `textkit` (port 8765)
- `yt2txt` (port 8666)

*(Excluded: `free-tts` which does not rely on an LLM, and `file-bridge` which is a local file bridge).*

## Quick Start

Launch the application using the included startup wrapper:

```bash
./start.sh
```

Or install in your virtual environment:

```bash
pip install -e .
ai-manager
```

## Running Tests

Run the complete test suite:

```bash
PYTHONPATH=src pytest tests/
```
