# chat2api and file-bridge Management — Design (revision 4)

**Date:** 2026-10-17
**Status:** Revised after two rounds of frontier design review
**Supersedes:** revision 3 (committed as `548cc7f`)
**Delivery targets:** two repositories (see §1)

> **Provenance note.** An unapproved intermediate commit (`374dc1f`) briefly
> encoded a read-only chat2api port decision that the user had explicitly
> rejected in favour of fixing the launcher. That commit was removed from this
> branch by rebase before review round 2. This revision supersedes the approved
> revision-2 content, not that commit.

## Revision 4 Summary

Review round 3 returned **0 blockers, 2 majors, 2 minors**. Round-3 corrections:

- **R3-M1 (probe auth).** The launcher probe fixture must set
  `server.auth_token_env: null`. Verified end-to-end during design: with null and
  an `echo` provider, chat2api binds and serves `/v1/models` in ~2 s offline.
  Without it the probe would fail on `validate_auth()` for reasons unrelated to
  the launcher. Child exit detection and guaranteed reap added.
- **R3-M2 (staging purity).** `write_app_config` mutates, so it cannot stage a
  dependent update. A pure `render_app_config` is required, and the dispatch
  table is corrected. Staging-failure must leave every target byte-identical.
- **R3-m1 (validation wording).** The auth-variable asymmetry is now stated:
  checked whenever the validator runs, not part of the unconditional guarantee.
- **R3-m2 (test inventory).** file-bridge **does** have a pytest harness
  (revision 3 wrongly denied it); `test_model_fetcher.py` added as affected.
- Ambiguity 3 resolved: the launcher binds one interpreter variable used for both
  the config read and the final `exec`; ai-manager re-derives the search and
  verifies with an import probe, so no code is shared across repositories.

## Revision 3 Summary

Review round 2 raised three new blockers and seven majors against revision 2.
All were verified against source. The material corrections:

- **B1 — delivery order.** Revision 2 claimed either repository could ship
  first. False: if Target A ships first, the editor can save a non-default port
  and rewrite dependents while the old launcher still binds 8000. Target B is
  now a hard prerequisite and the two form one atomic delivery unit.
- **B2 — acceptance proof.** The launcher fix is now proven by a subprocess
  test that starts the real launcher and probes the configured socket, plus an
  explicit statement of the double-config-read race.
- **B3 — Goal 4 overreach.** "Never write a config that will brick a restart"
  is unachievable and contradicted the degraded validator path. The goal is
  weakened to best-effort configuration validation, and the restart-risk
  boundary is stated explicitly.
- **M1** one shared interpreter/path contract for launcher and validator;
  **M2** `ConfigView` replaced by a concrete adapter boundary with signals;
  **M3** provider options contradiction removed (absent `options` is valid);
  **M4** D7 rebuilt as a real multi-file transaction; **M5** "Force overwrite"
  removed as a Save path; **M6** test inventory completed; **M7** safeguards
  from revision 1 restored (collision-proof backups, route-shape rules,
  validator-orchestration tests, mutation-address model).

## Revision 2 Summary (retained for context)

Revision 1 was reviewed by a frontier auditor. Three blockers and nine major
findings were raised. The resulting pivots were:

- **Pivot A.** `chat2api/start.sh` does **not** pass `server.host` or
  `server.port` to uvicorn, so editing them in revision 1 would have been
  inert. The feature now also fixes the chat2api launcher, making the run span
  two repositories.
- **Pivot B.** chat2api startup also calls `validate_auth()`, so the validator
  contract includes it and classifies login/discovery failures as runtime, not
  configuration, faults.
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
   validate configurations as thoroughly as the available validators allow
   before writing them. (Note: this is **best-effort configuration
   validation**, not a proof that a restart will succeed — see §4.4.)
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
without an explicit per-target decision.

**Target B is a hard prerequisite for Target A (blocker B1).** Revision 2
claimed the pair was coherent in either order. That was false. Before Target B's
launcher fix is installed, a user could use the new Target A editor to save a
non-default chat2api port and accept the blast-radius rewrite of dependent
`api_base` values — which would point three applications at an endpoint where
nothing listens, because the old launcher still binds 8000.

Therefore:

- The two targets form **one atomic delivery unit**. Target A is not delivered
  unless Target B is delivered in the same delivery step.
- Independently of delivery mechanics, the editor is gated on runtime evidence:
  chat2api's `host`/`port` fields and the blast-radius rewrite remain
  **read-only** until the launcher is confirmed to honor configuration. The
  check is behavioural, not version-based: ask the launcher for the listener it
  would use via `--print-listener` (amended per pivot question 15; the original
  socket-bind formulation is superseded because it could not be isolated in
  process). It binds nothing and is safe while the real service is live. The gate
  result is cached per session and surfaced inline as
  *"launcher honors config — host/port editable"* or
  *"launcher does not honor config — install Target B first"*.
- With the default `127.0.0.1:8000`, Target B is a no-op at runtime, so it is
  safe to install first, and installing it alone changes nothing observable.

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
   set, else `config.json` **relative to the script directory**, because the
   script has already `cd`-ed there.
2. Read `server.host` and `server.port` with the service's own loader so
   defaults and validation are identical — not a second parser that can drift.
   Verified working: `load_config()` resolves `config.json` after `cd`.
3. Pass them as `--host` and `--port` **before** `"$@"`. Verified: uvicorn's
   click parser takes the last occurrence of a flag, so a user-supplied flag
   still wins.
4. If the config cannot be read, exit non-zero **before** starting uvicorn.
   Verified: `load_config()` on a missing path raises `FileNotFoundError`, and
   `set -e` propagates it. The launcher must not silently bind a default port
   when the config is broken, because that would mask the real fault.
5. Preserve all existing behaviour: virtualenv activation, the version banner,
   `--timeout-graceful-shutdown 5`, `--log-level info`, argument pass-through.

**Interpreter contract (major M1).** The launcher has three interpreter
branches: `.venv/bin/activate`, `venv/bin/activate`, then ambient `python`. The
validator must use the **same resolution**, and both must end in the **same
interpreter that ultimately runs uvicorn**.

Because chat2api's only permitted change is `start.sh`, the helper cannot live in
chat2api's Python source. The mechanism is:

- `start.sh` selects its interpreter once into a shell variable and then uses
  that same variable for both the config read and the final `exec`, so the
  process that reads the config and the process that serves requests are
  guaranteed to be the same interpreter. Concretely: resolve to `PY=...`, run
  `"$PY" -c '<config read>'` to obtain host/port, then
  `exec "$PY" -m uvicorn ...`.
- ai-manager does **not** share code with chat2api. It re-derives the interpreter
  by applying the same three-step search against the app directory, then
  verifies the result behaves as a chat2api interpreter by running a one-line
  import probe (`import app, fastapi`). If the probe fails, the interpreter is
  treated as unavailable (degraded notice); if it succeeds, it is used for stage
  3. This keeps the two repositories independent while making the validator's
  interpreter the same *kind* of interpreter the launcher will pick, and the
  probe distinguishes "wrong interpreter" from "module missing".
- The plan adds a test asserting that for a fixture app directory containing
  only `venv/`, both the launcher path and ai-manager's resolution pick
  `venv/bin/python`; and that with no virtualenv present, both pick the ambient
  `python`.

**Known remaining race (blocker B2, second part).** The launcher reads the
config to build uvicorn arguments, and then `app.main`'s lifespan loads the
config **again**. A config edit between those two reads can leave the listener
bound to one host/port while the service configuration reports another. This is
inherent to the current architecture and is **documented, not fixed**: the
window is milliseconds at process start, the config is read-only for the user
at that moment, and fixing it would require changing chat2api's startup
contract, which is out of scope. The specification records it as a known
limitation.

**Acceptance (blocker B2).** Argument-construction tests are insufficient. The
test must:

1. Write a temporary config with an ephemeral free port, an `echo` provider, and
   **`server.auth_token_env: null`**. Authentication must be explicitly
   disabled: `ServerConfig` defaults `auth_token_env` to `CHAT2API_TOKEN`, and
   the lifespan calls `validate_auth()` before provider startup, so a probe
   omitting this field would fail for a reason unrelated to the launcher. This
   exact fixture was verified end-to-end during design: with `auth_token_env:
   null`, the echo config binds and serves `/v1/models` in ~2 s with no network
   access and no credentials.
2. Invoke the real `start.sh` with `CHAT2API_CONFIG` pointing at it.
3. Poll the configured loopback socket until it accepts a connection, or time
   out. The probe **also** detects premature child exit: if the process exits
   non-zero before binding, the test fails with the child's captured stderr
   rather than waiting out the timeout.
4. Assert the configured port is bound and, where feasible, that the old
   default is **not**.
5. Assert a user-supplied later `--port` wins over the config value.
6. Assert a missing or invalid config exits non-zero without binding anything.
7. **Always** terminate and reap the child on every outcome, including timeout
   and assertion failure, so a leaked server cannot poison later runs.

This is a required automated test, not an optional manual probe. It runs in
**Target B's own suite**, where binding a real socket is safe and supervised.

> **Amendment (user decision, pivot question 15).** Revision 4 made the GUI's
> runtime gate use this same socket-readiness rule. Adversarial review proved that
> cannot be isolated in-process: the launcher needs its `app/` tree, and any
> symlink to it exposes the real `config.json` and `.env` to the child, including
> non-Python children with no audit hook; a `bytes` path also bypasses a `str`
> deny-list. The GUI gate therefore uses the launcher's `--print-listener`
> capability instead — stateless, binding nothing, and safe to run while the real
> service is live. The live-socket proof above remains here, in Target B's tests,
> and is what makes the capability trustworthy. See spec §7.3.

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
| render | `write_app_config` (**mutation; not used for staged edits**) | `structured.render` | `structured.render` | raise |
| render for transaction | `render_app_config` (new pure function, §3) | `structured.render` | `structured.render` | raise |
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
formats.

**Mutation-address model (restored per major M7).** A save is a list of
addresses, each a key path such as `server.port` or
`models.<name>.options.headless`. The renderer applies only those addresses to
the loaded document and serialises. Every key **not named by an address** is
written with the value it had on load. Two consequences, made explicit because
revision 2 was ambiguous:

- "Original position" means **relative order among untouched keys is
  preserved**. Deleting an addressed key shifts the absolute ordinals of later
  keys; that is permitted and expected.
- Tests compare untouched subtrees by parsed equality **and** assert their
  relative order, never by byte ranges.

- **JSON (chat2api):** JSON has no comments. The service's example file carries a
  `_comments` **data** object, preserved like any other key. Formatting is
  normalised to 2-space indent with a trailing newline, matching the existing
  files.
- **YAML (file-bridge):** ruamel round-trip using the same engine configuration
  as `yaml_manager._get_yaml_engine()`. Comments, quoting, and key order are
  preserved. Anchors and aliases are preserved as written; the editor does not
  resolve them, and a document containing an anchor/alias is rendered
  **read-only** with an explanation, because rewriting an aliased node could
  silently change a second location.
- **Route shape.** `models` must be a dict; a non-dict `models` is a load error.
  Each model entry must be a dict or a load error; a **missing `options` key is
  valid and preserved** (the shipped example omits it on four entries), while a
  present `options` that is not a dict is a load error. See §5.
- Non-dict roots: chat2api's loader coerces a non-object root to `{}`. The
  editor must **not**. A non-object root is a load error with save disabled.

### Backups (restored per major M7)

Backup names are collision-proof and created exclusively:

```
<name>.<YYYYmmddTHHMMSSffffffZ>.<pid>-<hex6>.bak
```

Creation uses `O_CREAT | O_EXCL`, so two saves in the same instant cannot
silently clobber a recovery point; a collision retries with a new nonce. The
backup is written and `fsync`ed **before** the replace. Backup failure aborts
the save.

### Concurrency (D4) — honest guarantee

Revision 1 promised that a concurrent hand edit could never be lost. That is not
achievable with check-then-replace. The real protocol:

1. Take an advisory `flock` on a **sidecar lock file**, `<config>.lock`, not on
   the config itself. A lock on the config would not survive `os.replace`,
   because replacement swaps the inode and the locked descriptor would then
   refer to an unlinked file whose pathname is owned by a different inode.
2. Re-read, compare sha256 to the value captured at load. Mismatch →
   `StaleDocumentError`, nothing written.
3. Write backup, `fsync`, atomically replace, `fsync` parent directory.
4. Release the lock.

**Guarantee:** no update observed before the hash check is lost, and the window
is narrowed to the interval between the check and the `os.replace`. **Not**
guaranteed: protection against a writer that performs no locking and writes
inside that interval. This limitation is documented rather than papered over.

**No Force Overwrite on the Save path (major M5).** Revision 2's error table
offered "Force overwrite" as a save action while D4 promised refusal, which is
a contradiction. That control is **removed from the Save path entirely**. When a
hash mismatch is detected the save is refused, and the user's options are
Reload (discard draft), Show diff (inspect the on-disk change), or Cancel. A
user who genuinely wants to overwrite a file they changed outside the GUI reopens
the document (reload) and saves again, which is a normal save against the new
baseline. There is no code path that writes past a detected stale hash.

### Multi-file transaction (D7, rebuilt per major M4)

A blast-radius save writes `1 + n` files where `n` is the number of checked
dependents, `0 <= n <= 3`.

**Pure rendering is mandatory (round-3 major).** `write_app_config` mutates: it
creates a backup and calls `os.replace` immediately, and it assigns API key and
model fields. It therefore **cannot** be used to stage a dependent update —
doing so would write files during staging and would change more than
`ai.api_base`. A new pure function is required:

```
render_app_config(meta, doc, mutate) -> bytes
```

It loads the YAML round-trip document, applies only the supplied mutation (for
D7, exactly `ai.api_base`), and returns rendered bytes **without touching the
filesystem**. `write_app_config` reuses the same internal rendering step so the
two cannot drift; its existing observable behaviour for current callers is
unchanged.

The transaction is:

```
Transaction
  .prepare(paths: list[Path], expected: dict[Path, bytes])  # locks + hash verify
  .backups()                                               # exclusive-create all
  .stage(rendered: dict[Path, bytes])                      # temp files only
  .replace_all()
  .rollback(report: TransactionReport)
```

1. **prepare.** Sort paths lexicographically (deterministic lock order, no
   deadlock). Take every `<config>.lock` flock, then re-read and hash-verify every
   file under those locks. Any mismatch → release all locks, raise, write
   nothing.
2. **backups.** Create all backups exclusively. Any failure → release locks,
   write nothing (no target has been touched).
3. **stage.** Every file is rendered by the pure renderer, validated, written to
   a temp file and `fsync`ed. **No target is replaced.** A test asserts that on
   staging failure every target is byte-identical to its pre-transaction state.
4. **replace_all.** Replace targets in the sorted order recorded in step 1.
5. **Failure during replace_all.** Restore already-replaced targets from their
   backups, in reverse order, then release locks. If a **restore** also fails,
   record it in `TransactionReport.restore_failures` and surface it prominently;
   the report names every path with final state `new`, `restored`, or
   `unknown`. There is no silent partial state.
6. **Success.** Release locks, update the sidebar effective ports, clear dirty
   flags, report `TransactionReport` with per-file outcomes.

Zero dependents (`n == 0`) is still a transaction of one file, using the same
code path.

**UI reconciliation after a dependent rewrite.** A dependent app may hold
unsaved edits in its own view. Rewriting its `ai.api_base` on disk must not
silently clear those edits. The rule: the transaction updates the on-disk file
and the dependent view's *saved baseline*; the view's draft is left untouched,
so it remains marked dirty and the user's unrelated edits survive. If the
dependent's draft is not dirty, the view reloads and reflects the new
`api_base`. A test covers both branches.

### Symlinks and read-only files

- A config path that is a symlink is **rejected at load** with an explicit
  message, because `os.replace` would replace the link itself rather than its
  target and silently de-link the configuration. Detection uses `lstat()`.
- A config that is not writable is reported as such; the editor renders
  read-only with save disabled. It is never replaced "successfully" by virtue of
  a writable parent directory.
- Mode bits are preserved on replace; tests assert with `lstat()`.

## 4. Validation pipeline

### 4.4 Validation scope (blocker B3)

Revision 2's Goal 4 promised the system would never write a configuration that
bricks a restart. That is unachievable and contradicted the accepted degraded
path. The contract is now stated precisely:

**What validation guarantees:** the file parses under ai-manager's own schema
rules; and, **when the service validator actually runs**, that it additionally
parses under the service's own loader and passes the service's configuration
checks (including chat2api's `validate_auth()`, which blocks when the named auth
environment variable is unset).

**What validation does not guarantee:** that a restart succeeds. It does not
check whether the configured port is already in use, whether the service's
dependencies are installed, whether provider credentials are present or valid,
whether login or discovery will succeed at runtime, or whether the environment
at restart time matches the environment at save time. A save can succeed and a
restart can still fail.

Note the asymmetry: authentication-variable availability **is** checked whenever
the validator runs, because a missing auth var is a configuration fault that the
service itself rejects at startup. Provider credentials and runtime outcomes are
outside the guarantee in all cases.

The UI reflects this by labelling the two outcomes distinctly: *"configuration
valid"* versus *"service restart succeeded"*. The restart outcome is reported by
the supervisor action, never inferred from a successful save.

### Pipeline

Ordered, fail-fast:

1. **Control-character rejection.** Applied to every *scalar value being
   written*, not to every string in the document: reject `\n`, `\r`, `\0` in
   host, model names, option values, `auth_token_env`, and `save_root`
   components. Existing untouched values are never inspected, so a
   pre-existing oddity cannot block an unrelated save. Unicode is permitted
   everywhere, including paths.
2. **In-process rules** (pydantic per kind), mirrored from the services' real
   constraints:
   - chat2api: `host` non-empty; `port` must be an `int` (**bools and numeric
     strings rejected**, and a numeric string is coerced by the *service* to
     that integer, not to the default) in 1–65535; model names non-empty and
     unique; `provider` in `{echo, gemini_webapi, copilot_webapi, browser}`;
     `auth_token_env` either absent, `null` (explicitly valid — disables auth),
     or an env-var-shaped non-empty name.
   - file-bridge: `port` must be an `int` in 1–65535; `max_text_bytes` must be
     an `int` with `0 <= n <= 100 MiB` (the service's `MAX_MAX_TEXT_BYTES`);
     `save_root` non-empty, expanding to an existing writable directory that is
     **not** inside the file-bridge application directory (the service's
     `_probe_save_root` rule).
3. **Service validator, best effort.** The candidate file is written **into the
   same directory as the target config** (a hidden sibling), because
   file-bridge resolves a relative `save_root` against the config file's parent
   — a candidate in `/tmp` would validate a different directory. The
   interpreter is chosen by the shared helper from §1 (major M1), **not**
   hardcoded to `.venv`. Commands run with cwd set to the app directory, 10 s
   timeout:
   - file-bridge: `import main; c = main.load_config(p); main._probe_save_root(c.save_root)`
   - chat2api: `load_config(p)`; `Registry(cfg)`; `cfg.validate_auth()`

   The chat2api stage validates **configuration**, not runtime.
   `validate_auth()` fails when the named env var is unset, which is a genuine
   config fault and blocks the save. `startup_login()` and
   `ensure_discovered()` are **not** invoked: they perform network and browser
   work whose failure does not indicate a bad config, and invoking them would
   make an offline save fail for the wrong reason.
4. **Commit** per §3.

If the interpreter or module is unavailable, stage 3 is skipped and the UI shows
*"validated by ai-manager only — service validator unavailable"*. Per §4.4 this
means configuration validity is asserted by ai-manager's own rules only; it is
not a claim about restart success.

## 5. chat2api provider options contract

`models[*].options` is a free-form mapping in the service. The editor must handle
it without inventing precision.

**Absent is valid.** A model entry with **no** `options` key is valid, is
preserved without one, and is the shape used by four entries in the service's
shipped `config.example.json`. Revision 2 contradicted itself on this point
(major M3); the rule is: `options` absent → valid, preserved absent; `options`
present but not a mapping → load error; `models` not a mapping → load error;
model entry not a mapping → load error.

- **Known option keys** are a **convenience inventory**, not a closed schema.
  They come from the providers' actual reads and are rendered as typed fields;
  anything else is preserved and editable as raw text. The inventory
  intentionally admits incompleteness: `browser` in particular reads selector
  and URL overrides that are configuration-specific, and `startup_login` reads
  `secure_1psidts_env`, `timeout`, `interactive_login`, and
  `browser_profile_dir`.
- **Unknown keys** are preserved verbatim and shown in a collapsed "raw
  options" area, never dropped. The service tolerates them.
- **Provider switch** keeps the option map intact and re-classifies now-unknown
  keys as raw; nothing is deleted implicitly. The UI flags that the previous
  provider's options may be meaningless to the new one.
- **Secrets** (`account`, `password`, `access_token`) render masked with
  per-field reveal and follow the unchanged-flag rule: unchanged secrets are
  written from the loaded document, never from widget text.

## 6. UI

`AppDetailView` keeps serving `config_kind == "llm"`. A new
`StructuredConfigView` serves the two new kinds.

**Adapter boundary (major M2).** Revision 2's `ConfigView` protocol was not
implementable: it renamed `get_current_draft`, omitted every signal `MainWindow`
connects, and ignored `ModelFetchRequest` response identity. The concrete
boundary is:

- `StructuredConfigView` is a `QWidget` subclass, sibling to `AppDetailView`,
  not a wrapper.
- It exposes the **same four signals** `MainWindow` already connects:
  `save_requested(str app_id, object draft, bool should_restart)`,
  `restart_requested(str app_id)`, `config_changed(str app_id, object draft)`,
  and `fetch_models_requested(ModelFetchRequest)` (never emitted).
- It exposes `get_current_draft()` — the **same name** as `AppDetailView`, so no
  method renaming is required and `MainWindow` calls it uniformly.
- `MainWindow` stores drafts as `Any` keyed by app id instead of
  `Dict[str, AppAIConfig]`; dirty comparison is per-kind (`AppAIConfig.__eq__`
  for LLM views, rendered-bytes comparison for structured views).
- Dirty state stays computed in `MainWindow` for both view types; neither view
  gets a `set_dirty` requirement.
- `ModelFetchRequest` gains an `app_id` field, and the response is routed back
  to that originating view rather than to whichever app is currently selected.
  A test switches selection while a fetch is in flight and asserts the
  originating view receives the response.

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
rewrites only `ai.api_base`. Declining saves chat2api alone. Host/port unchanged
→ dialog is not shown. The whole operation is one transaction per §3.

This describes real behaviour only when the launcher gate from §1 is satisfied;
otherwise the fields are read-only and this section cannot trigger.

**Auth contract fix.** ai-manager's `chat2api_local` preset declares
`CHAT2API_API_KEY`, while chat2api's default is `CHAT2API_TOKEN` and the live
`.env` defines `CHAT2API_TOKEN` only. The preset is wrong and is corrected to
`CHAT2API_TOKEN`. The design additionally warns when a dependent app's
`ai.api_key` names an env var different from chat2api's `auth_token_env`,
because that combination yields 401s that look like a server fault.

## 8. Errors and failure modes

| Condition | Behavior |
| --- | --- |
| File changed on disk before commit | Save refused; Reload / Show diff / Cancel (§3, no force path) |
| In-process rule fails | Save blocked; field marked invalid; inline message |
| Service validator rejects | Save blocked; credential-safe stderr (input values redacted, location and message preserved) in expandable panel |
| Service validator unavailable | Save allowed with visible degraded notice |
| Config missing (new kinds) | Empty sections + explicit create-from-example action |
| Config missing (llm kinds) | Unchanged: auto-create from example |
| Non-dict root / non-dict `models` / non-dict entry | Load error; save disabled |
| `options` absent | Valid; preserved absent |
| `options` present but not a mapping | Load error; save disabled |
| Anchors/aliases present in YAML | Read-only render with explanation |
| Config path is a symlink | Load rejected with explanation |
| Config not writable | Read-only render; save disabled |
| Backup write fails | Transaction aborts before any replace |
| Multi-file transaction partially fails | Restore from backups; `TransactionReport` names final state per file |
| Restore itself fails | Reported explicitly as `unknown`; never silently partial |
| Restart fails after save | File stays saved; failure surfaced; no rollback |
| Launcher does not honor config | chat2api host/port read-only with install-Target-B-first note |

## 9. Testing Strategy

### Complete inventory of affected existing tests (major M6)

Verified by grep against the current suite. Every file below touches one of
`get_managed_apps`, `AppAIConfig`, `read_app_config`, `write_app_config`, or
`AppDetailView` and must be reviewed:

| Existing test | Why it is affected |
| --- | --- |
| `tests/test_app_registry.py` | asserts `set(apps) == {ai-grammar, textkit, yt2txt}` and `"file-bridge" not in apps` |
| `tests/test_e2e_integration.py` | loops the whole registry through `read_app_config()` — would mis-parse `config.json` |
| `tests/test_app_views.py` | builds `AppDetailView` from `get_managed_apps()` (2 call sites, lines 12 and 40); must skip non-`llm` kinds or exercise the structured view |
| `tests/test_mnemonic.py` | iterates `get_managed_apps()` at line 254 |
| `tests/test_models.py` | asserts `AppAIConfig` equality semantics; must pin the per-kind dirty-comparison contract |
| `tests/test_yaml_manager.py` | exercises `read_app_config`/`write_app_config`; must confirm the new optional `expected_sha256` does not change existing behaviour |
| `tests/test_main_window.py` | assumes three views and `AppDetailView` typing |
| `tests/test_main_window_tray.py` | constructs `MainWindow`, therefore indirectly three views |
| `tests/test_model_fetcher.py` | constructs `ModelFetchRequest` at three sites (lines 23, 51, 65) without `app_id`; affected by the new request-identity field |
| `tests/conftest.py` | needs chat2api/file-bridge fixtures and a five-app workspace fixture |

### New tests

| File | Coverage |
| --- | --- |
| `tests/test_structured_config.py` | load/render/commit; mutation-address fidelity; JSON key-order preservation; YAML comment preservation; anchors/aliases → read-only; symlink rejection via `lstat`; read-only file; collision-proof backup with `O_EXCL`; mode preservation |
| `tests/test_structured_validation.py` | per-kind rules: int-type strictness (bools, `"8000"`), port bounds, `max_text_bytes` bounds incl. 100 MiB, `save_root` existence/writability/application-dir exclusion, `auth_token_env: null`, absent `options`, non-mapping `options`/`entry`/`models` |
| `tests/test_validator_orchestration.py` | stage-3 outcomes: exit 0, exit 1 with stderr, interpreter absent → degraded notice; interpreter selection across `.venv` / `venv` / ambient `PATH`; candidate file adjacency |
| `tests/test_transaction.py` | multi-file `prepare`/`backups`/`replace_all`/`rollback`; 0, 1, 3-dependent cases; all-or-nothing on hash mismatch; restore-failure reported as `unknown`; deterministic lock ordering |
| `tests/test_blast_radius.py` | detection, opt-in rewrite, decline path, scope restricted to `ai.api_base`, per-app checkbox subset |
| `tests/test_structured_view.py` | offscreen: table add/remove/expand, secret unchanged-flag, Review Changes content, read-only render states, effective-port display |
| `tests/test_sidebar_port.py` | sidebar shows effective configured port on load and after save; falls back to default when unreadable |
| `tests/test_preset_auth.py` | `chat2api_local` preset declares `CHAT2API_TOKEN`; mismatch warning fires for a dependent naming a different env var |
| `tests/test_launcher_gate.py` | chat2api host/port are read-only when the launcher probe fails, editable when it passes |
| `tests/test_fetch_routing.py` | switching sidebar selection while a fetch is in flight delivers the response to the originating view |
| `tests/test_supervisor.py` (extend) | file-bridge status line parsing and restart fixture |
| chat2api `tests/test_launcher.py` (Target B) | **real** launcher subprocess on a temporary config with an ephemeral port; asserts the configured socket binds, the old default does not, a later user `--port` wins, `CHAT2API_CONFIG` relative and absolute both work, and a missing/invalid config exits non-zero without binding |

### Harness availability

ai-manager's declared stack (`pytest`, `pytest-qt`, offscreen QPA via
`conftest.py`, `respx`) covers every ai-manager test above.

chat2api's declared stack (`pytest`, `pytest-asyncio`, `asyncio_mode=auto`) covers
its launcher test, which uses `subprocess` plus socket polling and needs no new
dependencies.

file-bridge **does** have a pytest harness (`pytest==9.1.1` in
`requirements-dev.txt`, `tests/test_main.py`, `tests/conftest.py`); revision 3
wrongly claimed otherwise. It is still **not** a delivery target: its existing
tests are not modified and no new file-bridge test dependency is added. Its
configuration validator is exercised through ai-manager's
`test_validator_orchestration.py` using (a) a fake interpreter for deterministic
`exit` codes and (b) an optional real-venv probe.

No test above depends on optional manual probing; the post-restart listener
assertion is automated in Target B.

## 10. Out of Scope

Env-var credential migration; live model drift polling; `free-tts`; chat2api
provider, registry, request, or discovery behaviour; any change to file-bridge
source.
