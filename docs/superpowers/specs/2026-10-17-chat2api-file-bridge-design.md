# chat2api and file-bridge Management — Design

**Date:** 2026-10-17
**Status:** Approved
**Target:** ai-manager 0.1.2 → 0.2.0

## Background

`ai-backends` already supervises five services: `ai-grammar`, `textkit`,
`yt2txt`, `chat2api`, and `file-bridge`. Live output confirms all five report
`running` with pids and log paths:

```
ai-grammar   running  pid=2221916 log=~/.cache/ai-backends/logs/ai-grammar.log
textkit      running  pid=2221917 log=.../textkit.log
yt2txt       running  pid=2221918 log=.../yt2txt.log
chat2api     running  pid=2221919 log=.../chat2api.log
file-bridge  running  pid=2221921 log=.../file-bridge.log
```

ai-manager, however, registers only the first three. `chat2api` and `file-bridge`
are explicitly excluded in `config/app_registry.py`, in the README, and in
`tests/test_app_registry.py`. The exclusion was a deliberate early decision
("`file-bridge` is a local file bridge", "`free-tts` does not rely on an LLM")
that this feature inverts for the two bridge services.

The inversion is not cosmetic. Both services differ structurally from the three
LLM apps:

| | ai-grammar / textkit / yt2txt | chat2api | file-bridge |
| --- | --- | --- | --- |
| Config format | YAML (`config.yaml`) | JSON (`config.json`) | YAML (`config.yaml`) |
| Shape | fixed `ai:` block | `server` block + dynamic `models` map | three flat scalars |
| Secrets | `api_key` (one field) | per-model `options.account` / `options.password` | none |
| Loads config | at startup | at startup (lifespan) | at startup, before bind |
| Own validator | none | none useful (see below) | strict, reject-on-invalid |

## Goals

1. Register `chat2api` and `file-bridge` as fully first-class managed apps:
   sidebar entry, status dot, port, restart action, live logs, dirty tracking.
2. Give each a typed configuration editor for its own file format, without
   pretending either has an OpenAI `ai:` block.
3. Edit chat2api credentials in place with masked fields and reveal toggles,
   preserving every value the user does not touch.
4. Never lose a concurrent hand edit, and never write a config that will brick
   a restart.
5. Warn at the moment a chat2api host/port change would orphan the three LLM
   apps that point at it.
6. Correct the documentation that currently claims these apps are excluded.

## Non-Goals

- Migrating chat2api secrets to env-var references. Deferred by explicit user
  decision; the editor hides nothing and claims nothing it cannot deliver.
- Live `/v1/models` drift polling. Dropped: chat2api reads config only at
  startup, so post-save "drift" is expected noise.
- `free-tts` management. It has no configuration surface and is not an LLM.
- Any change to chat2api or file-bridge source code. Both are edited only
  through their config files.

## Decisions

Each decision was made explicitly during design and is binding.

| # | Question | Decision |
| --- | --- | --- |
| D1 | Scope | Supervision + logs + bespoke editors + full first-class status |
| D2 | chat2api credentials | Masked, editable fields with reveal toggles |
| D3 | Editor architecture | Declarative field schema rendered by one generic form |
| D4 | Concurrent edits | Detect via content hash and **refuse** the save |
| D5 | Validation timing | In-process rules always; service validator best-effort |
| D6 | Layout | Single grouped page, table for models, diff on demand |
| D7 | Blast radius | Change-time warning plus opt-in rewrite of dependent `api_base` |

## Verified Facts About the Services

These were established by running the real loaders, not by reading docs, and
they directly determine the validation design.

**file-bridge's validator is strict and usable standalone:**

```
save_root: "/nonexistent/xyz"  -> RuntimeError: save_root does not exist
unknown key `bogus_key`        -> RuntimeError: Unknown config key(s): bogus_key
duplicate key `port`           -> RuntimeError: Invalid YAML ... duplicate
port: 70000                    -> RuntimeError: config port must be from 1 to 65535
valid config                   -> VALID
```

**chat2api's `load_config()` accepts almost anything:**

```
port 70000              -> ACCEPTED
unknown top-level key   -> ACCEPTED
unknown server key      -> ACCEPTED
unknown provider kind   -> ACCEPTED
port as string "8000"   -> ACCEPTED (silently coerced to default 8000)
```

Only `Registry(config)` rejects a bad provider kind:

```
Registry(load_config(p)) with provider "nope"
  -> ValueError: Model 'x' references unknown provider 'nope'.
     Known providers: ['browser', 'copilot_webapi', 'echo', 'gemini_webapi']
```

**Consequence:** for chat2api, ai-manager is the only thing that will catch a
bad port, and the service validator only meaningfully covers provider kinds.

Both validators can be invoked against a *candidate* temp file before commit,
using each service's own interpreter, which is what makes D5 work.

## Architecture

### Registry boundary

`AppMetadata` gains a `config_kind` discriminator:

- `"llm"` — `ai-grammar`, `textkit`, `yt2txt`; existing `ai:`-block handling.
- `"chat2api"` — `config.json`; `server` block + `models` routing table.
- `"file-bridge"` — `config.yaml`; `save_root`, `max_text_bytes`, `port`.

`get_managed_apps()` returns all five. `free-tts` remains excluded, and the
docstrings and README are corrected to say so.

`read_app_config()` is only valid for `config_kind == "llm"`. Every existing
caller becomes kind-dispatched. This is load-bearing: `tests/test_e2e_integration.py`
currently loops the entire registry through `read_app_config()`, which would
mis-parse `config.json` as YAML as soon as chat2api is registered.

### Config access layer

New module `src/ai_manager/config/structured_config.py` with a small interface:

```
load(kind, path) -> StructuredDoc
    doc          parsed structure (dict-like, order preserving)
    raw_sha256   sha256 of the exact bytes read
    existed      whether the file existed

render(kind, doc) -> bytes
    JSON for chat2api, ruamel round-trip YAML for file-bridge

commit(kind, path, doc, expected_sha256) -> SaveResult
    re-read, verify sha256, backup, atomic replace
```

- **Round-trip fidelity.** Only addressed key paths are mutated. Untouched keys,
  comments, key order, and quoting survive. file-bridge uses the same ruamel
  engine configuration as `yaml_manager._get_yaml_engine()`.
- **Backups.** `config.json.<utc-ts>.bak` and `config.yaml.<utc-ts>.bak`,
  written *before* the replace. Timestamped rather than a single `.bak` so
  successive saves cannot clobber each other's recovery point.
- **Atomic replace.** Temp file in the same directory, `fsync`, preserve the
  original file mode, `os.replace`, then `fsync` the parent directory. This
  mirrors `yaml_manager.write_app_config`, extended with the directory sync.
- **Refusal (D4).** `commit` re-reads the file and compares sha256 against the
  value captured at load. Mismatch raises `StaleDocumentError` and writes
  nothing. Force overwrite is a separate explicit call that re-loads and
  re-applies the draft; it is the only path past the check.

### Validation pipeline

Save runs these stages in order and stops at the first failure:

1. **Control-character rejection.** Refuse any value containing `\n`, `\r`, or
   NUL before any file work.
2. **In-process rules** (pydantic models per kind):
   - chat2api: `host` non-empty and parseable; `port` in 1–65535; each model
     name non-empty and unique; `provider` in the known set; `auth_token_env`
     either absent or a non-empty env-var-shaped name.
   - file-bridge: `port` in 1–65535; `max_text_bytes` a non-negative integer;
     `save_root` non-empty, existing, and a writable directory.
3. **Service validator, best effort.** Rendered candidate written to a temp
   file outside the configured path, then:
   - file-bridge: `python -c "import main; c=main.load_config(p); main._probe_save_root(c.save_root)"`
   - chat2api: `python -c "from app.config import load_config; from app.registry import Registry; Registry(load_config(p))"`

   Executed with the app's own `.venv/bin/python`, 10 s timeout, cwd set to the
   app directory. If the interpreter or module is unavailable the stage is
   skipped and the UI shows **"validated by ai-manager only — service validator
   unavailable"**. A genuine validator rejection blocks the save and shows the
   exact stderr.
4. **Commit** with the sha256 check from D4.

Stage 2 exists because chat2api's stage 3 cannot catch a bad port.

### Blast radius (D7)

Before committing a changed chat2api `server.host` or `server.port`, build the
old and new base URLs and compare each against `ai.api_base` in the three LLM
configs. On any match, present a pre-save dialog listing the affected apps with
a checkbox each:

> 3 apps point at `http://127.0.0.1:8000`. Update them to
> `http://127.0.0.1:8100` too?

Accepting rewrites only `ai.api_base`, through the existing
`write_app_config`. Declining saves chat2api's file alone. The dialog appears
before any write and is skipped entirely when host and port are unchanged.

### UI

`AppDetailView` remains the view for `config_kind == "llm"`. A new
`StructuredConfigView` serves the other two kinds. Both expose the same view
interface used by `MainWindow` — `load_config`, `get_current_draft`,
`update_service_status`, `set_dirty`, `log_view` — so `MainWindow` routes by
kind rather than special-casing app IDs.

Layout for both new apps (approved mockup option 4):

```
app title + description            [● running pid=1234] [Restart Service]
[Configuration] [Logs]
  Editing  /path/to/config.json          validated by chat2api
  ── Server ──────────────────────────────────────────────────────
  Host [        ]   Port [    ]   Auth token env var [            ]
  ── Models ──────────────────────────────────────────────────────
  NAME              PROVIDER          OPTIONS           SECRETS
  gemini            gemini_webapi     account, password •••••• [Reveal]  [Remove]
  ▸ m365-copilot    copilot_webapi    account, password •••••• [Reveal]  [Remove]
  browser-gemini    browser           headless          none              [Remove]
  [+ Add model]
  ────────────────────────────────────────────────────────────────
  ● Unsaved changes        [Review Changes] [Save Config Only] [Save and Restart]
```

- **chat2api models** render as a table with inline row expansion. The expanded
  row holds the provider dropdown (restricted to known kinds), typed option
  fields derived from the selected provider, and masked secret fields with a
  per-field Reveal toggle.
- **Secret preservation (D2).** A masked field tracks an `unchanged` flag
  separate from its displayed text. Fields marked unchanged are written back
  from the loaded document, never from the widget. A masked field can therefore
  never be accidentally committed as literal bullet characters.
- **Review Changes (D6)** opens a modal showing the exact rendered bytes with
  line-level `+`/`-` highlighting. It is the on-demand form of the preview that
  option C would have kept permanently visible.
- **file-bridge** renders three fields plus a `save_root` directory picker. The
  `max_text_bytes: 0` case is annotated inline as *"no limit"*, because the
  current config uses `0` and that is easy to misread as "reject everything".
- Both views show the live-log tab by embedding the existing `LogViewWidget`,
  unchanged.

### Error handling

| Condition | Behavior |
| --- | --- |
| File changed on disk since load | Save blocked; Reload / Show diff / Force overwrite |
| In-process rule fails | Save blocked; field marked invalid; inline message |
| Service validator rejects | Save blocked; exact stderr in expandable panel |
| Service validator unavailable | Save allowed with visible degraded notice |
| Config file missing | Empty sections plus "create from example?" action; never auto-created |
| Backup write fails | Save aborted before replace |
| Restart fails after successful save | File remains saved; failure surfaced; no rollback |
| Render produces invalid output | Abort before commit; treat as internal error |

## Testing Strategy

- **Unit — schema rules.** Port bounds (0, 65535, 65536, non-integer), empty
  host, duplicate model names, unknown provider kind, non-existent `save_root`,
  non-writable `save_root`, negative `max_text_bytes`.
- **Unit — serialization.** Round-trip a config with comments, unusual key order
  and quoting, assert untouched regions are byte-identical after `render`.
- **Unit — secrets.** Load a doc, mark a secret field unchanged, mutate another
  field, render, assert the secret bytes are preserved exactly and that no
  bullet characters appear.
- **Unit — refusal.** Change the file between `load` and `commit`, assert
  `StaleDocumentError` and that the file on disk is unchanged.
- **Unit — backups and modes.** Assert a timestamped backup exists with the
  original content, and that the replaced file keeps the original mode.
- **Unit — validator orchestration.** Stub `.venv/bin/python` with a script that
  exits 0, exits 1 with stderr, or is absent; assert the three outcomes and the
  degraded notice.
- **Unit — blast radius.** Fixture workspace with three LLM configs pointing at
  `:8000`; assert detection, opt-in rewrite touches only `ai.api_base`, and
  declining leaves the three files byte-identical.
- **UI (offscreen).** Both views construct, dirty tracking works, table
  add/remove/expand behave, Review Changes shows the expected content, and the
  Logs tab still binds.
- **Registry.** Five apps registered with correct kinds, `free-tts` absent,
  and the e2e integration test no longer feeds `config.json` to
  `read_app_config`.

Real service validators are exercised manually against the live venvs and are
documented in the specification as optional probes, not as required CI steps.

## Security Notes

The chat2api config currently stores account credentials inline in `options`,
despite its own README claiming secrets are referenced by env-var name. Under
D2 the editor makes these editable in the GUI. The mitigations are: masked
fields by default, explicit per-field reveal, exact preservation of untouched
values, atomic replace with backup, and refusal on concurrent modification.
Migrating these values to env-var references remains the correct long-term fix
and is explicitly deferred.

For file-bridge, `save_root` is a filesystem capability: the editor can point
the service at any writable directory. The in-process rule only requires that
the directory exists and is writable; it does not attempt to judge whether the
chosen location is sensible.

## Documentation Changes

- `README.md`: remove the "*(Excluded: … file-bridge …)*" note, list all five
  services, and describe the two new configuration surfaces.
- `config/app_registry.py`: correct the docstring to name only `free-tts`.
- `docs/superpowers/specs/2026-10-04-ai-manager-design.md` and
  `-audit-report.md` are historical records; they are not rewritten, but the
  new specification supersedes their exclusion statement.
