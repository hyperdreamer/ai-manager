# chat2api and file-bridge Management — Design (revision 2)

**Date:** 2026-10-17
**Status:** Revised after frontier design review
**Supersedes:** revision 1 of this document
**Delivery targets:** two repositories (see §1)

## Revision 2 Summary

Revision 1 was reviewed by a frontier auditor. Three blockers and nine major
findings were raised; every one was independently verified against source before
being accepted. The resulting pivots:

- **Pivot A (blocker §3.1).** `chat2api/start.sh` does **not** pass `server.host`
  or `server.port` to uvicorn, so editing them in revision 1 would have been
  inert. The feature now also fixes the chat2api launcher, which makes the run
  span two repositories.
- **Pivot B (blocker §3.2).** chat2api startup also calls `validate_auth()`, so
  the validator contract now includes it and explicitly classifies
  login/discovery failures as runtime, not configuration, faults.
- **Pivot C (blocker §3.3).** The revision 1 concurrency guarantee was
  overstated. The commit protocol now uses an advisory lock and the guarantee is
  stated honestly as "no lost update observed before commit".
- **Correction.** Revision 1 claimed chat2api's JSON round-trip preserves
  comments. JSON has no comments; revision 1 was wrong, and the fidelity
  contract is now stated semantically.
- Deferred-feature and scope decisions from the user are unchanged: credentials
  editable and masked, detect-and-refuse, in-process plus best-effort service
  validation, grouped layout with a models table and on-demand diff, and
  change-time blast-radius warning.

## Background

`ai-backends` supervises five services. Live `ai-backends status` output:

```
ai-grammar   running  pid=2221916 log=~/.cache/ai-backends/logs/ai-grammar.log
textkit      running  pid=2221917 log=.../textkit.log
yt2txt       running  pid=2221918 log=.../yt2txt.log
chat2api     running  pid=2221919 log=.../chat2api.log
file-bridge  running  pid=2221921 log=.../file-bridge.log
```

ai-manager registers only the first three. `file-bridge` is **explicitly**
excluded in `config/app_registry.py`, the README, and `tests/test_app_registry.py`.
`chat2api` is **not** explicitly excluded anywhere — it was simply never
registered, despite ai-manager shipping a `chat2api_local` provider preset that
points the three LLM apps at `http://127.0.0.1:8000`. Revision 1 overstated this
as a symmetric exclusion; that is corrected here.

The two services differ structurally from the LLM apps:

| | ai-grammar / textkit / yt2txt | chat2api | file-bridge |
| --- | --- | --- | --- |
| Config format | YAML `config.yaml` | JSON `config.json` | YAML `config.yaml` |
| Shape | fixed `ai:` block | `server` + dynamic `models` map | three flat scalars |
| Secrets | one `api_key` | per-model `options.account` / `password` | none |
| Config read | at startup | at startup (lifespan) | at startup, before bind |
| Honors config port | n/a | **no** (defect, fixed by this feature) | **yes** (`main.py:1063`) |
| Own validator | none | weak (`load_config`); `Registry` + `validate_auth` add checks | strict, reject-on-invalid |

## Goals

1. Register `chat2api` and `file-bridge` as first-class managed apps: sidebar
   entry, status, effective port, restart, live logs, dirty tracking.
2. Give each a typed configuration editor for its own file format.
3. Edit chat2api credentials in place with masked fields and reveal toggles,
   preserving every value the user does not touch.
4. Never lose a concurrent hand edit that was observable before commit, and
   never write a configuration that will brick a restart.
5. Warn when a chat2api host/port change would orphan the three LLM apps.
6. Make chat2api's configured host/port actually control its listener, so that
   the editor's fields are truthful.
7. Correct the documentation that misdescribes the registry.

## Non-Goals

- Migrating chat2api credentials to env-var references. Deferred by user
  decision; recorded as follow-up work.
- Live `/v1/models` drift polling. Dropped: chat2api reads config only at
  startup, so post-save drift is expected noise.
- `free-tts` management.
- Changing chat2api provider behaviour, request handling, or model discovery.
  The only chat2api source change is the launcher (see §1).

## Decisions

| # | Question | Decision |
| --- | --- | --- |
| D1 | Scope | Supervision + logs + bespoke editors + full first-class status |
| D2 | chat2api credentials | Masked, editable, reveal toggles |
| D3 | Editor architecture | Declarative per-kind schema + one generic form |
| D4 | Concurrent edits | Detect and **refuse**; advisory lock; honest guarantee |
| D5 | Validation timing | In-process rules always; service validator best-effort |
| D6 | Layout | Single grouped page, models table, diff on demand |
| D7 | Blast radius | Change-time warning + opt-in rewrite of dependent `api_base` |
| D8 | Inert chat2api port | **Fix `chat2api/start.sh`** so config drives the listener |
| D9 | Two-repo delivery | One PM run, two delivery targets, repo-scoped lanes |

## 1. Two delivery targets

| | Target A | Target B |
| --- | --- | --- |
| Repository | `ai-manager` | `chat2api` |
| Path | `/data/home/guest/Development/ai/ai-manager` | `/data/home/guest/Development/ai/chat2api` |
| Branch at pin | `main` @ `b220669` | `main` @ `c40e3c6` |
| Integration worktree | `$PM_WORKTREE_ROOT/integration` | `$PM_WORKTREE_ROOT/integration-chat2api` |
| Integration branch | `pm/chat2api-file-bridge/run-<id>` | same name, distinct repo |
| Remote | `origin` → `hyperdreamer/ai-manager` | `origin` → `hyperdreamer/chat2api` |

Both repositories were clean, on a named branch, tracking `origin/main`, with a
single registered worktree at pin time. Their `main` tips equal their fetched
remote tips, so no reconciliation is required at delivery.

The delivery gate at the end presents **both** targets. Neither is merged
without an explicit per-target decision. A target may be delivered by merge, by
pull request, or left undelivered; the pair is still coherent because Target B's
launcher change is backwards compatible (see §5).

### Target B change: `chat2api/start.sh`

Currently:

```bash
exec python -m uvicorn app.main:app \
    --timeout-graceful-shutdown 5 \
    --log-level info \
    "$@"
```

The comment above it claims host and port come from `config.json`. They do not.

Required behaviour:

1. Resolve the config path exactly as the service does: `$CHAT2API_CONFIG` if
   set, else `config.json` in the script directory.
2. Read `server.host` and `server.port` with the service's own loader so
   defaults and validation are identical — not a second parser that can drift.
3. Pass them as `--host` and `--port`, **before** `"$@"` so an explicit
   user-supplied flag still wins.
4. If the config cannot be read, fail loudly with a non-zero exit rather than
   silently binding a default. The service already refuses to start with a
   broken config; the launcher must not mask that by starting on a stale port.
5. Preserve all existing behaviour: virtualenv activation, the version banner,
   `--timeout-graceful-shutdown 5`, `--log-level info`, extra argument pass-through.

This is backwards compatible: with the default `127.0.0.1:8000` the effective
listener is unchanged, so Target B can be delivered before, after, or with
Target A without breaking the running service.

## 2. Registry boundary

`AppMetadata` gains a `config_kind` discriminator with three known values:
`"llm"`, `"chat2api"`, `"file-bridge"`. Any other value **fails closed** with a
clear error rather than falling back to a default.

`get_managed_apps()` returns all five apps. `free-tts` remains excluded and is
the only app named in the corrected docstrings and README.

Kind dispatch is exhaustive across the config surface, not just reads:

| Operation | `llm` | `chat2api` | `file-bridge` | Unknown kind |
| --- | --- | --- | --- | --- |
| load | `read_app_config` | `structured.load` | `structured.load` | raise |
| render | `write_app_config` | `structured.render` | `structured.render` | raise |
| missing file | auto-create from example (existing behaviour, unchanged) | empty sections + explicit "create from example" action | empty sections + explicit action | raise |
| validation | none (unchanged) | §4 stage 2 + 3 | §4 stage 2 + 3 | raise |
| commit | `write_app_config` | `structured.commit` | `structured.commit` | raise |

Auto-creation from an example is deliberately **retained for `llm` kinds**
(it is existing, tested behaviour) and **not introduced for the new kinds**,
because chat2api picks up `.env` secrets by name and file-bridge refuses to
start without a valid `save_root`; silently materialising a config would hide
that.

This distinction is load-bearing: `tests/test_e2e_integration.py` currently
loops the entire registry through `read_app_config()`. That loop becomes
kind-dispatched, and it must assert kind-specific facts so a silently defaulted
`AppAIConfig` cannot make the test pass.

## 3. Config access layer

New module `src/ai_manager/config/structured_config.py`:

```
load(kind, path) -> StructuredDoc
    kind            "chat2api" | "file-bridge"
    doc             parsed structure (order preserving)
    raw_sha256      sha256 of the exact bytes read
    existed         bool
    resolved_path   real path used for the candidate-adjacency rule (§4)

render(kind, doc) -> bytes
commit(kind, path, doc, expected_sha256) -> SaveResult
```

### Fidelity contract

Stated semantically, because byte-level preservation is not achievable for both
formats:

- **JSON (chat2api):** JSON has no comments. The service's example file carries a
  `_comments` **data** object, which is preserved like any other key. The
  contract is: every key not addressed by the edit is preserved with identical
  value, at its original position in key order; formatting is normalised to
  2-space indent with a trailing newline, matching the existing files. Untouched
  keys are compared by parsed equality, not by bytes, in tests.
- **YAML (file-bridge):** ruamel round-trip using the same engine configuration
  as `yaml_manager._get_yaml_engine()`. Comments, quoting of touched scalars'
  untouched neighbours, and key order are preserved. Anchors and aliases are
  preserved as written; the editor does not resolve or expand them, and any
  document containing an anchor/alias **is rendered read-only** with an
  explanatory note, because rewriting an aliased node could silently change a
  second location.
- Non-dict roots: chat2api's loader converts a non-object root to `{}`. The
  editor must **not** silently do that. A non-object root is a load error shown
  to the user, and save is disabled until the file is fixed externally.
- `models` that is not a dict, or a model entry without `options`, is likewise a
  load error, not a silent coercion.

### Concurrency (D4) — honest guarantee

Revision 1 promised that a concurrent hand edit could never be lost. That is not
achievable with check-then-replace. The real protocol:

1. Acquire an **advisory `flock`** on the config file for the whole
   verify-backup-replace window. This coordinates with other ai-manager
   instances and with any tool that cooperates; it cannot stop an editor that
   ignores locks.
2. Re-read, compare sha256 to the value captured at load. Mismatch →
   `StaleDocumentError`, nothing written.
3. Write backup, `fsync`, atomically replace, `fsync` parent directory.
4. Release the lock.

**Guarantee:** no update observed before the hash check is lost, and the window
is narrowed to the interval between the check and the `os.replace`. **Not**
guaranteed: protection against a writer that performs no locking and writes
inside that interval. This limitation is documented in the specification rather
than papered over.

### Multi-file writes (D7)

The blast-radius update touches four files. Ordering:

1. Load and hash-verify **all** candidates first (chat2api plus each selected
   dependent). Any mismatch aborts everything before a single write.
2. Create all backups.
3. Replace chat2api's file, then each dependent in turn.
4. On a failure mid-sequence, restore already-replaced files from their backups
   and report exactly which files were written and which were restored.

Dependents are written through `write_app_config`, which gains an optional
`expected_sha256` argument so the same refusal rule applies to them. Without
that argument its current behaviour is unchanged for existing callers.

### Symlinks and read-only files

- A config path that is a symlink is **rejected at load** with an explicit
  message, because `os.replace` would replace the link itself rather than its
  target and silently de-link the configuration. Detection uses `lstat()`.
- A config that is not writable is reported as such; the editor renders
  read-only with save disabled. It is never replaced "successfully" by virtue of
  a writable parent directory.
- Mode bits are preserved on replace; tests assert with `lstat()`.

## 4. Validation pipeline

Ordered, fail-fast:

1. **Control-character rejection.** Applied to every *scalar value being
   written*, not to every string in the document: reject `\n`, `\r`, `\0` in
   host, model names, option values, `auth_token_env`, and `save_root`
   components. Existing untouched values are never inspected, so a
   pre-existing oddity cannot block an unrelated save. Unicode is permitted
   everywhere, including paths.
2. **In-process rules** (pydantic per kind), mirrored from the services' real
   constraints rather than from prose:
   - chat2api: `host` non-empty; `port` must be an `int` (bools and numeric
     strings rejected) in 1–65535; model names non-empty and unique; `provider`
     in `{echo, gemini_webapi, copilot_webapi, browser}`; `auth_token_env`
     either absent, `null` (explicitly valid — disables auth), or an
     env-var-shaped non-empty name.
   - file-bridge: `port` must be an `int` in 1–65535; `max_text_bytes` must be
     an `int` with `0 <= n <= 100 MiB` (the service's `MAX_MAX_TEXT_BYTES`);
     `save_root` non-empty, expanding to an existing writable directory that is
     **not** inside the file-bridge application directory (the service's
     `_probe_save_root` rule).
3. **Service validator, best effort.** The candidate file is written **into the
   same directory as the target config** (a hidden sibling), because
   file-bridge resolves a relative `save_root` against the config file's parent
   — a candidate in `/tmp` would validate a different directory. Commands run
   with the app's `.venv/bin/python`, cwd set to the app directory, 10 s
   timeout:
   - file-bridge: `import main; c = main.load_config(p); main._probe_save_root(c.save_root)`
   - chat2api: `load_config(p)`; `Registry(cfg)`; `cfg.validate_auth()`

   The chat2api stage is explicitly scoped: it validates **configuration**, not
   runtime. `validate_auth()` fails when the named env var is unset, which is a
   genuine config fault and blocks the save. `startup_login()` and
   `ensure_discovered()` are **not** invoked: they perform network and browser
   work whose failure does not indicate a bad config, and invoking them would
   make an offline save fail for the wrong reason. This distinction is stated in
   the UI text and the specification.
4. **Commit** per §3.

If the app's interpreter or module is unavailable, stage 3 is skipped and the UI
shows *"validated by ai-manager only — service validator unavailable"*. That
degraded path means goal 4 is best-effort, not absolute, and the specification
says so.

## 5. chat2api provider options contract

`models[*].options` is a free-form mapping in the service. The editor must
handle it without inventing precision:

- **Known option keys** are declared per provider kind from the providers'
  actual reads: `gemini_webapi` (`account`, `password`, `gemini_model`,
  `secure_1psid_env`), `copilot_webapi` (`account`, `password`,
  `access_token`, `access_token_env`, `copilot_mode`, `interactive_login`,
  `browser_profile_dir`, `timezone`, `chat_timeout`), `browser` (`headless`,
  `account`, `password`, `user_data_dir`, `timeout`, `upstream_model`,
  `hydration_timeout_ms`, `response_appear_timeout`), `echo` (`prefix`).
- **Unknown keys are preserved verbatim** and shown in a collapsed "raw
  options" area, never dropped. The service tolerates them.
- **Absent versus empty `options`** is preserved: an entry with no `options` key
  stays without one unless the user edits it.
- **Provider switch** keeps the option map intact and marks now-unknown keys as
  raw; nothing is deleted implicitly. The UI flags that the previous provider's
  options may be meaningless to the new one.
- **Secrets** (`account`, `password`, `access_token`) render masked with
  per-field reveal, and follow the unchanged-flag rule: unchanged secrets are
  written from the loaded document, never from widget text.

## 6. UI

`AppDetailView` keeps serving `config_kind == "llm"`. A new
`StructuredConfigView` serves the two new kinds. Both satisfy an explicit
protocol, because the existing view does **not** already satisfy the informal one
revision 1 described:

```
class ConfigView(Protocol):
    log_view -> LogViewWidget
    def load_config(self, doc) -> None
    def current_draft(self) -> Any
    def update_service_status(self, status: ServiceStatus) -> None
    def on_model_fetch_response(self, response: ModelFetchResponse) -> None
```

`AppDetailView` emits `AppAIConfig` and has no `set_dirty` (MainWindow computes
dirtiness itself), so the protocol carries `current_draft` rather than a
`set_dirty` call, and dirty computation stays in `MainWindow` for both view
types. Model fetching is LLM-only: on a structured view the fetch action is
absent, and `on_model_fetch_response` is a no-op that cannot be reached because
no request is issued. Fetch responses are additionally routed by the request's
originating app id, which is added to `ModelFetchRequest`, replacing the current
"whichever app is selected" routing.

Layout (approved mockup option 4, chat2api variant shown):

```
title + description                 [● running pid=1234] [Restart Service]
[Configuration] [Logs]
  Editing  .../chat2api/config.json        validated by chat2api · ai-manager
  ── Server ─────────────────────────────────────────────────────────
  Host [        ]   Port [    ]   Auth token env var [               ]
  ── Models ─────────────────────────────────────────────────────────
  NAME              PROVIDER          OPTIONS            SECRETS
  gemini            gemini_webapi     account, password  •••••• [Reveal] [Remove]
  browser-gemini    browser           headless           none            [Remove]
  [+ Add model]
  ─────────────────────────────────────────────────────────────────
  ● Unsaved changes      [Review Changes] [Save Config Only] [Save and Restart]
```

The mockup is **chat2api-specific**. `file-bridge` renders exactly three config
fields — `save_root` (text field plus directory picker), `max_text_bytes`
(integer field annotated *0 = no limit*), `port` (integer field) — under a single
`Save Location & Server` group, with no host, auth, or models controls.

Sidebar: the port shown is the **effective configured port**, not
`AppMetadata.default_port`. `AppSidebar` gains a configured-port update path,
populated on load and updated after a successful save; the metadata default
remains the initial value while a config is unloaded or unreadable.

## 7. Blast radius (D7)

Before committing a changed chat2api `server.host` or `server.port`, compare the
old and new base URLs against `ai.api_base` in the three LLM configs. On a match,
show a pre-save dialog listing affected apps with a per-app checkbox. Accepting
rewrites only `ai.api_base` through `write_app_config` with hash checking.
Declining saves chat2api alone. Host/port unchanged → dialog is not shown.

This now describes real behaviour, because Target B makes the port effective.

**Auth contract fix.** ai-manager's `chat2api_local` preset declares
`CHAT2API_API_KEY`, while chat2api's default is `CHAT2API_TOKEN` and the live
`.env` defines `CHAT2API_TOKEN` only. The preset is wrong and is corrected to
`CHAT2API_TOKEN`. The design additionally warns when a dependent app's
`ai.api_key` names an env var different from chat2api's `auth_token_env`,
because that combination yields 401s that look like a server fault.

## 8. Errors and failure modes

| Condition | Behavior |
| --- | --- |
| File changed on disk before commit | Save blocked; Reload / Show diff / Force overwrite |
| In-process rule fails | Save blocked; field marked invalid; inline message |
| Service validator rejects | Save blocked; exact stderr in expandable panel |
| Service validator unavailable | Save allowed with visible degraded notice |
| Config missing (new kinds) | Empty sections + explicit create-from-example action |
| Config missing (llm kinds) | Unchanged: auto-create from example |
| Non-dict root / non-dict `models` | Load error; save disabled |
| Anchors/aliases present in YAML | Read-only render with explanation |
| Config path is a symlink | Load rejected with explanation |
| Config not writable | Read-only render; save disabled |
| Backup write fails | Save aborted before replace |
| Multi-file blast radius partially fails | Restore replaced files from backups; report exactly what happened |
| Restart fails after save | File stays saved; failure surfaced; no rollback |

## 9. Testing Strategy

New and changed tests, enumerated (reviewer finding 12):

| File | Change |
| --- | --- |
| `tests/test_app_registry.py` | five apps, kinds correct, `free-tts` absent; replaces the current "exactly three" assertion |
| `tests/test_e2e_integration.py` | kind-dispatched loading; assert chat2api/file-bridge facts so a defaulted config cannot pass |
| `tests/test_main_window.py` | constructs with five apps; view routing by kind |
| `tests/test_mnemonic.py` | fixture app set extended, or asserted against the five-app registry |
| `tests/conftest.py` | fixtures for chat2api/file-bridge configs |
| `tests/test_structured_config.py` (new) | load/render/commit, fidelity, refusal, backups, modes, symlink |
| `tests/test_structured_validation.py` (new) | per-kind rules incl. int-type strictness, 100 MiB bound, application-dir exclusion, `auth_token_env: null` |
| `tests/test_blast_radius.py` (new) | detection, opt-in rewrite, decline path, partial-failure restore |
| `tests/test_structured_view.py` (new) | offscreen UI: table add/remove/expand, secret unchanged-flag, Review Changes |
| `tests/test_supervisor.py` | file-bridge status/restart fixture |
| `tests/test_chat2api_launcher.py` (new, Target B) | launcher resolves host/port from config, honors `CHAT2API_CONFIG`, passes user args last, fails loudly on unreadable config |

Target B tests run in the chat2api repository against its own harness
(`pytest`, `asyncio_mode = "auto"`).

Live checks stay manual and are documented as optional probes: real service
validators against the live venvs, and a post-restart assertion that
`chat2api` binds the configured port (Target B).

## 10. Out of Scope

Env-var credential migration; live model drift polling; `free-tts`; chat2api
provider, registry, request, or discovery behaviour; any change to file-bridge
source.
