from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Literal

from ai_manager.config.models import AppMetadata
from ai_manager.config.protocols import ENDPOINT_VALUES
from ai_manager.services.app_interpreter import resolve_app_interpreter
from ai_manager.services.launcher_gate import redact_diagnostics


_SECRET_DIAGNOSTIC_KEYS: Final[tuple[str, ...]] = (
    "password",
    "account",
    "access_token",
    "api_key",
    "token",
    "secure_1psid",
    "secure_1psidts",
)
_UNQUOTED_SECRET_PAIR: Final[re.Pattern[str]] = re.compile(
    r"(?P<key>(?<!\w)(?:" + "|".join(_SECRET_DIAGNOSTIC_KEYS)
    + r")(?!\w)\s*[:=]\s*)(?P<value>[^\s,'\";]+)",
    re.IGNORECASE,
)


def _redact_probe_detail(text: str) -> str:
    # The shared scrubber handles quoted pairs; normalize bare assignments first.
    normalized = _UNQUOTED_SECRET_PAIR.sub(
        lambda match: f"{match.group('key')}'{match.group('value')}'", text
    )
    return redact_diagnostics(normalized)


class ProtocolSupportStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class ProtocolSupport:
    status: ProtocolSupportStatus
    accepted: frozenset[str] = frozenset()
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProtocolSupportStatus):
            raise ValueError("Protocol support status is invalid.")
        if not isinstance(self.accepted, frozenset):
            raise ValueError("Accepted protocols must be a frozenset.")
        if not self.accepted.issubset(ENDPOINT_VALUES):
            raise ValueError("Accepted protocols must be supported endpoint values.")
        if self.status is ProtocolSupportStatus.SUPPORTED:
            valid = self.accepted == ENDPOINT_VALUES
        elif self.status is ProtocolSupportStatus.PARTIAL:
            valid = 1 <= len(self.accepted) <= 2
        else:
            valid = not self.accepted
        if not valid:
            raise ValueError("Protocol support status does not match accepted protocols.")
        if not isinstance(self.detail, str):
            raise ValueError("Protocol support detail must be text.")
        object.__setattr__(self, "detail", _redact_probe_detail(self.detail))


GRAMMAR_PROGRAM: Final[str] = r'''
import json
import sys
nonce = sys.argv[1]
values = ("/v1/chat/completions", "/v1/responses", "/v1/messages")
try:
    import config
    resolve = config._resolve_endpoint
    if not callable(resolve):
        raise AttributeError("config._resolve_endpoint is not callable")
except (ImportError, AttributeError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
accepted, rejected = [], []
for value in values:
    try:
        resolve({"endpoint": value})
    except RuntimeError:
        rejected.append(value)
    else:
        accepted.append(value)
print("PROBE_RESULT:" + nonce + ":" + json.dumps({"accepted": accepted, "rejected": rejected}))
raise SystemExit(0)
'''


TEXTKIT_PROGRAM: Final[str] = r'''
import json
import sys
nonce = sys.argv[1]
values = ("/v1/chat/completions", "/v1/responses", "/v1/messages")
try:
    import main
    supported = main.SUPPORTED_ENDPOINTS
    model = main.AIConfig
    validate = model.model_validate
    if not isinstance(supported, (tuple, list, set, frozenset)):
        raise AttributeError("main.SUPPORTED_ENDPOINTS is not a collection of strings")
    if not all(isinstance(value, str) for value in supported) or not callable(validate):
        raise AttributeError("textkit endpoint validation interface is unavailable")
except (ImportError, AttributeError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
base = {"api_base": "https://api.openai.com", "api_key": "probe", "model": "probe"}
accepted, rejected = [], []
for value in values:
    try:
        if value not in supported:
            raise ValueError("not in SUPPORTED_ENDPOINTS")
        validate({**base, "endpoint": value})
    except Exception:
        rejected.append(value)
    else:
        accepted.append(value)
print("PROBE_RESULT:" + nonce + ":" + json.dumps({"accepted": accepted, "rejected": rejected}))
raise SystemExit(0)
'''


_PROGRAMS: Final[dict[str, str]] = {
    "ai-grammar": GRAMMAR_PROGRAM,
    "textkit": TEXTKIT_PROGRAM,
}


def _unknown(reason: str, stdout: str = "", stderr: str = "") -> ProtocolSupport:
    parts = [reason]
    if stdout:
        parts.extend(("stdout:", stdout))
    if stderr:
        parts.extend(("stderr:", stderr))
    return ProtocolSupport(
        ProtocolSupportStatus.UNVERIFIABLE,
        frozenset(),
        _redact_probe_detail("\n".join(parts)),
    )


def _parse_partition(stdout: str, nonce: str) -> frozenset[str]:
    prefix = f"PROBE_RESULT:{nonce}:"
    lines = stdout.splitlines()
    matching = [(index, line) for index, line in enumerate(lines) if line.startswith(prefix)]
    nonempty = [index for index, line in enumerate(lines) if line.strip()]
    if len(matching) != 1 or not nonempty or matching[0][0] != nonempty[-1]:
        raise ValueError("missing, duplicate, or non-final protocol sentinel")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate protocol result key")
            result[key] = value
        return result

    payload = json.loads(
        matching[0][1][len(prefix):], object_pairs_hook=reject_duplicate_keys
    )
    if not isinstance(payload, dict) or set(payload) != {"accepted", "rejected"}:
        raise ValueError("protocol result must contain exactly accepted and rejected")
    accepted = payload["accepted"]
    rejected = payload["rejected"]
    if type(accepted) is not list or type(rejected) is not list:
        raise ValueError("protocol partition members must be lists")
    if any(not isinstance(value, str) for value in (*accepted, *rejected)):
        raise ValueError("protocol partition entries must be strings")
    accepted_set = set(accepted)
    rejected_set = set(rejected)
    if len(accepted_set) != len(accepted) or len(rejected_set) != len(rejected):
        raise ValueError("protocol partition entries must be unique")
    if not accepted_set.issubset(ENDPOINT_VALUES) or not rejected_set.issubset(ENDPOINT_VALUES):
        raise ValueError("protocol partition contains an unknown endpoint")
    if accepted_set & rejected_set:
        raise ValueError("accepted and rejected endpoints overlap")
    if accepted_set | rejected_set != ENDPOINT_VALUES:
        raise ValueError("protocol partition is incomplete")
    return frozenset(accepted_set)


def _captured_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_uncached_probe(
    meta: AppMetadata, interpreter: Path, app_dir: Path
) -> ProtocolSupport:
    program = _PROGRAMS.get(meta.id)
    if program is None:
        return _unknown(f"No protocol probe is defined for {meta.id}.")

    nonce = secrets.token_hex(16)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        child = subprocess.Popen(
            [str(interpreter), "-B", "-c", program, nonce],
            cwd=app_dir.resolve(),
            shell=False,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return _unknown(f"Could not run protocol capability check: {exc}")

    try:
        stdout, stderr = child.communicate(timeout=5.0)
    except subprocess.TimeoutExpired as exc:
        stdout = _captured_text(exc.stdout)
        stderr = _captured_text(exc.stderr)
        cleanup_error: Exception | None = None
        try:
            child.kill()
        except Exception as kill_exc:
            cleanup_error = kill_exc
        try:
            stdout, stderr = child.communicate()
        except Exception as reap_exc:
            cleanup_error = cleanup_error or reap_exc
        if cleanup_error is not None:
            stderr = "\n".join(part for part in (stderr, f"cleanup: {cleanup_error}") if part)
        return _unknown(
            "Protocol capability check timed out after 5 seconds.",
            _captured_text(stdout),
            _captured_text(stderr),
        )
    except Exception as exc:
        stdout = ""
        stderr = ""
        try:
            child.kill()
        except Exception as kill_exc:
            stderr = f"cleanup: {kill_exc}"
        try:
            captured_stdout, captured_stderr = child.communicate()
            stdout = _captured_text(captured_stdout)
            captured_stderr = _captured_text(captured_stderr)
            stderr = "\n".join(part for part in (stderr, captured_stderr) if part)
        except Exception as reap_exc:
            stderr = "\n".join(part for part in (stderr, f"cleanup: {reap_exc}") if part)
        return _unknown(
            f"Could not run protocol capability check: {exc}", stdout, stderr
        )

    stdout = _captured_text(stdout)
    stderr = _captured_text(stderr)
    if child.returncode != 0:
        return _unknown(
            f"Protocol capability check exited {child.returncode}.", stdout, stderr
        )
    try:
        accepted = _parse_partition(stdout, nonce)
    except (ValueError, TypeError):
        return _unknown(
            "Protocol capability check did not report a valid result.", stdout, stderr
        )

    if accepted == ENDPOINT_VALUES:
        status = ProtocolSupportStatus.SUPPORTED
    elif accepted:
        status = ProtocolSupportStatus.PARTIAL
    else:
        status = ProtocolSupportStatus.UNSUPPORTED
    return ProtocolSupport(status, accepted, _redact_probe_detail(stderr.strip()))


Fingerprint = tuple[Literal["full"], bytes] | tuple[Literal["coarse"], int, int, int]
_CacheKey = tuple[str, str, int, Fingerprint]
_EXCLUDED_DIRECTORIES: Final[frozenset[str]] = frozenset({"__pycache__", ".venv", "venv"})
SUPERSEDED: Final[str] = (
    "Protocol capability check was superseded; retry after the restart or update."
)
_lock = threading.Lock()
_cache: dict[_CacheKey, ProtocolSupport] = {}
_generations: dict[str, int] = {}


def source_fingerprint(app_dir: Path) -> Fingerprint:
    """Hash only Python sources; overflow metadata is never cache authority."""
    files: list[tuple[str, Path]] = []
    newest_file_mtime_ns: int | None = None

    def raise_scan_error(error: OSError) -> None:
        raise error

    for directory, subdirectories, filenames in os.walk(
        app_dir, followlinks=False, onerror=raise_scan_error
    ):
        root = Path(directory)
        try:
            marker = (root / "pyvenv.cfg").stat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISREG(marker.st_mode):
                subdirectories.clear()
                continue

        included_directories = []
        for name in subdirectories:
            entry = (root / name).lstat()
            if name not in _EXCLUDED_DIRECTORIES and stat.S_ISDIR(entry.st_mode):
                included_directories.append(name)
        subdirectories[:] = included_directories

        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = root / name
            entry = path.lstat()
            if stat.S_ISLNK(entry.st_mode):
                entry = path.stat()
            if stat.S_ISREG(entry.st_mode):
                files.append((path.relative_to(app_dir).as_posix(), path))
                newest_file_mtime_ns = (
                    entry.st_mtime_ns if newest_file_mtime_ns is None
                    else max(newest_file_mtime_ns, entry.st_mtime_ns)
                )

    if len(files) > 200:
        assert newest_file_mtime_ns is not None
        return ("coarse", len(files), newest_file_mtime_ns, app_dir.stat().st_mtime_ns)
    hasher = hashlib.sha256()
    for relative, path in sorted(files, key=lambda entry: entry[0]):
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        hasher.update(b"\n")
    return ("full", hasher.digest())


def protocol_support_generation(app_id: str) -> int:
    with _lock:
        return _generations.get(app_id, 0)


def invalidate_protocol_support(app_id: str) -> None:
    with _lock:
        _generations[app_id] = _generations.get(app_id, 0) + 1
        for key in tuple(_cache):
            if key[0] == app_id:
                del _cache[key]


def _probe_identity(meta: AppMetadata) -> tuple[Path, Path, _CacheKey]:
    interpreter = resolve_app_interpreter(meta.relative_path)
    app_dir = meta.relative_path.resolve()
    key = (
        meta.id,
        str(interpreter),
        interpreter.stat().st_mtime_ns,
        source_fingerprint(app_dir),
    )
    return interpreter, app_dir, key


def probe_protocol_support(
    meta: AppMetadata, *, use_cache: bool = True
) -> ProtocolSupport:
    generation = protocol_support_generation(meta.id)
    return _probe_protocol_support_at_generation(
        meta, generation=generation, use_cache=use_cache
    )


def _probe_protocol_support_at_generation(
    meta: AppMetadata, *, generation: int, use_cache: bool = True
) -> ProtocolSupport:
    if not meta.supports_protocol_selection:
        return ProtocolSupport(
            ProtocolSupportStatus.UNSUPPORTED,
            detail="Protocol selection is not available for this application.",
        )
    if meta.id not in _PROGRAMS:
        return _unknown(f"No protocol probe is defined for {meta.id}.")
    with _lock:
        if generation != _generations.get(meta.id, 0):
            return _unknown(SUPERSEDED)
    try:
        interpreter, app_dir, key = _probe_identity(meta)
    except Exception as exc:
        return _unknown(f"Protocol capability check could not be prepared: {exc}")

    cacheable = use_cache and key[3][0] == "full"
    with _lock:
        if generation != _generations.get(meta.id, 0):
            return _unknown(SUPERSEDED)
        if cacheable:
            cached = _cache.get(key)
            if cached is not None:
                return cached

    try:
        result = _run_uncached_probe(meta, interpreter, app_dir)
    except Exception as exc:
        result = _unknown(f"Protocol capability check failed: {exc}")
    try:
        _, _, current_key = _probe_identity(meta)
    except Exception as exc:
        return _unknown(f"Protocol capability check could not be prepared: {exc}")
    if current_key != key:
        return _unknown(SUPERSEDED)
    with _lock:
        if generation != _generations.get(meta.id, 0):
            return _unknown(SUPERSEDED)
        if cacheable:
            _cache[key] = result
        return result
