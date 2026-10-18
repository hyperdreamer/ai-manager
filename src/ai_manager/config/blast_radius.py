from __future__ import annotations
import hashlib
import io
import re
from collections.abc import Mapping
from urllib.parse import urlsplit
from ruamel.yaml.tokens import AliasToken, AnchorToken
from ai_manager.config.config_errors import ConfigLoadError
from ai_manager.config.models import AppAIConfig, AppMetadata
from ai_manager.config.structured_config import _candidate, _snapshot
from ai_manager.config.structured_models import DependentMatch, StructuredDoc
from ai_manager.config.structured_schema import Chat2ApiServerSchema
from ai_manager.config.yaml_manager import _config_from_document, _get_yaml_engine
from ai_manager.utils.env_resolver import is_env_var_reference

URL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/?#]+)(.*)$", re.DOTALL)
DEPENDENT_IDS = ("ai-grammar", "textkit", "yt2txt")


def normalize_loopback_url(url: str) -> str | None:
    """R-HOST-CLASS: rewrite only the loopback host spelling to 127.0.0.1."""
    match = URL_RE.fullmatch(url)
    if match is None:
        return None
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        return None
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        return None
    scheme, authority, rest = match.groups()
    userinfo, marker, host_port = authority.rpartition("@")
    prefix = userinfo + marker if marker else ""
    if not marker:
        host_port = authority
    if host_port.startswith("["):
        end = host_port.find("]")
        if end == -1 or host_port[1:end] != "::1":
            return None
        suffix = host_port[end + 1:]
    else:
        host, separator, port = host_port.partition(":")
        if host.lower() not in ("127.0.0.1", "localhost"):
            return None
        suffix = separator + port
    if suffix and re.fullmatch(r":[0-9]+", suffix) is None:
        return None
    return scheme + prefix + "127.0.0.1" + suffix + rest


def urls_match(a: str, b: str) -> bool:
    """Strip at most ONE terminal slash per side, normalize host only, compare exactly."""
    left = normalize_loopback_url(a[:-1] if a.endswith("/") else a)
    right = normalize_loopback_url(b[:-1] if b.endswith("/") else b)
    return left is not None and right is not None and left == right


def endpoint(doc: StructuredDoc) -> tuple[str, int, str]:
    server = Chat2ApiServerSchema.model_validate(_candidate(doc).get("server", {}))
    host = f"[{server.host}]" if server.host == "::1" else server.host
    return server.host, server.port, f"http://{host}:{server.port}"


def auth_mismatch_warning(dependent: AppAIConfig, auth_token_env: str | None) -> str | None:
    if auth_token_env is None or not is_env_var_reference(dependent.api_key):
        return None
    dependent_env = dependent.api_key.strip()[1:]
    if dependent_env == auth_token_env:
        return None
    return f"{{app_id}} uses ${dependent_env}, but chat2api auth_token_env is {auth_token_env!r}; requests may fail with HTTP 401."


def find_affected_dependents(apps: Mapping[str, AppMetadata], before: StructuredDoc, after: StructuredDoc) -> tuple[DependentMatch, ...]:
    old_host, old_port, old_url = endpoint(before)
    new_host, new_port, new_url = endpoint(after)
    if (old_host, old_port) == (new_host, new_port):
        return ()
    auth = Chat2ApiServerSchema.model_validate(_candidate(after).get("server", {})).auth_token_env
    matches = []
    for app_id in DEPENDENT_IDS:
        meta = apps.get(app_id)
        if meta is None or meta.config_kind != "llm":
            continue
        path = meta.relative_path / meta.config_file_name
        try:
            canonical, raw, mode, reasons = _snapshot(path)
            if raw is None:
                raise ValueError("Configuration file is missing.")
            if reasons:
                raise ValueError("Configuration is not writable; editing is disabled.")
            text = raw.decode("utf-8")
            if any(isinstance(token, (AnchorToken, AliasToken)) for token in _get_yaml_engine().scan(io.StringIO(text))):
                raise ValueError("YAML anchors or aliases are present; editing is disabled to preserve linked values.")
            engine = _get_yaml_engine()
            engine.allow_duplicate_keys = False
            tree = engine.load(text)
            if not isinstance(tree, dict) or not isinstance(tree.get("ai"), dict) or not isinstance(tree["ai"].get("api_base"), str):
                raise ValueError("Expected a mapping with a string ai.api_base.")
            old_base = tree["ai"]["api_base"]
            if urls_match(old_base, old_url):
                saved = _config_from_document(tree)
                warning = auth_mismatch_warning(saved, auth)
                matches.append(DependentMatch(meta, canonical, tree, raw, hashlib.sha256(raw).digest(), saved, old_base, new_url, warning.format(app_id=app_id) if warning else None))
        except Exception as exc:
            # The entire operation is inspection: never treat an unreadable file as a nonmatch.
            message = f"Cannot inspect dependent configuration {path}: {exc}"
            error = ConfigLoadError(path, str(exc))
            error.args = (message,)
            raise error from exc
    return tuple(matches)
