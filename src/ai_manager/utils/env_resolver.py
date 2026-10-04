import os
from typing import Tuple


def is_env_var_reference(value: str) -> bool:
    """Returns True if the value refers to an environment variable ($VAR_NAME)."""
    if not value:
        return False
    val = value.strip()
    return val.startswith("$") and len(val) > 1 and val[1:].isidentifier()


def resolve_api_key(value: str) -> str:
    """Resolves an API key, looking up environment variables if prefixed with $."""
    if not value:
        return ""
    val = value.strip()
    if is_env_var_reference(val):
        var_name = val[1:]
        return os.environ.get(var_name, "")
    return val


def get_env_var_status(value: str) -> Tuple[bool, str]:
    """Returns (is_set, diagnostic_message) for a key value."""
    if not value:
        return False, "Empty API Key"
    val = value.strip()
    if is_env_var_reference(val):
        var_name = val[1:]
        if var_name in os.environ:
            val_len = len(os.environ[var_name])
            return True, f"✓ ${var_name} resolved (length: {val_len})"
        return False, f"⚠️ ${var_name} is unset in environment"
    return True, f"Plaintext key (length: {len(val)})"
