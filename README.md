# ai-manager

Desktop administration GUI built with **PyQt6** for managing AI provider configurations, discovering models dynamically via `/v1/models` endpoints, and controlling local service supervision for backend applications (`ai-grammar`, `textkit`, `yt2txt`, `chat2api`, `file-bridge`).

## Features

- ⚡ **Master-Detail Layout**: View all managed backends in a sleek left sidebar with real-time status dots (Running, Stopped, Restarting) and port indicators.
- 🔄 **Dynamic Model Discovery**: Fetch available models on-demand from any OpenAI-compatible provider (`/v1/models` and `/models`) with background non-blocking execution and race-condition prevention.
- 📝 **Round-Trip YAML Preservation**: Safely updates `config.yaml` using `ruamel.yaml`, preserving original inline comments, formatting, and commented-out model blocks with atomic temp-file replacement and automatic `.bak` backups.
- ⚙️ **Split Model Support**: Intelligently manages single unified models as well as split OCR/Text model configurations (e.g. for `textkit`).
- 🚀 **`ai-backends` Supervisor Control**: Seamless integration with the supervisor daemon to check status and trigger one-click restarts (`ai-backends restart <app>`).
- 🌓 **Light and Dark Themes**: Switch themes dynamically at runtime with settings persisted to `~/.config/ai-manager/settings.json`.
- 💾 **Dirty State Protection**: Tracks in-memory unsaved drafts per application, shows asterisk (`*`) indicators on sidebar tabs, and prompts before discarding changes on window close.

## Applications Managed

| Application | Port | Configuration |
| --- | --- | --- |
| `ai-grammar` | 8766 | YAML (`config.yaml`) |
| `textkit` | 8765 | YAML (`config.yaml`) |
| `yt2txt` | 8666 | YAML (`config.yaml`) |
| `chat2api` | 8000 | JSON (`config.json`) |
| `file-bridge` | 8964 | YAML (`config.yaml`) |

*(Excluded: only `free-tts`, which does not rely on an LLM.)*

### Structured configuration

chat2api exposes Server and Models; file-bridge exposes Save Location & Server. Create from Example starts an unsaved draft when a structured config is missing. Review Changes shows the local saved-to-draft diff. Save Config Only validates and writes; Save and Restart requests a supervisor restart only after the save commits. A restart failure keeps the saved configuration and is reported separately.

Install the chat2api launcher update with or before this ai-manager version. Each manager session checks the launcher with a temporary echo-only config and disabled auth. Until that check passes, chat2api host/port and dependent URL updates stay disabled. Models/options/auth, status, logs and restart remain available. The probe is cleaned up and never changes the real config.

When chat2api host/port changes, only explicitly checked matching LLM apps receive a new ai.api_base. Their API keys, models and other data are preserved. Dirty drafts in those apps stay visible after the saved baseline changes. The chat2api_local preset now uses $CHAT2API_TOKEN; existing keys are never migrated automatically.

chat2api host accepts only 127.0.0.1, localhost or ::1. The editor edits app_dir/config.json; it does not discover an externally set CHAT2API_CONFIG. CLI listener overrides may differ from the configured port shown by the manager. file-bridge stays on IPv4 loopback; 0 maximum text bytes means no configured limit while its transport cap still applies. A save root must already exist outside the file-bridge application directory.

Validation always checks the manager schema. When the target interpreter/imports are unavailable, the inline result says "validated by ai-manager only — service validator unavailable". Validation does not establish restart success, free ports, provider credentials, login or discovery.

Structured saves refuse stale files and keep timestamped exclusive backups and existing mode bits (new files use 0600). Sidecar locks coordinate participating writers. Unlocked editors/readers can still race or observe a partial multi-file replacement. Recovery covers handled failures; there is no crash-recovery journal or multi-file crash atomicity. The launcher reads config once for listener flags and again during startup, so an intervening edit can disagree with the listener. Symlinks, non-writable files, and YAML anchors/aliases cannot be edited here.

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
