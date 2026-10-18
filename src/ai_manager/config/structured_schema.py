from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    control: Literal["text", "integer", "nullable-text", "directory"]
    minimum: int | None = None
    maximum: int | None = None
    annotation: str = ""


@dataclass(frozen=True)
class OptionSpec:
    key: str
    control: Literal["text", "integer", "boolean", "secret"]


SERVER_FIELDS = (
    FieldSpec("host", "Host", "text"),
    FieldSpec("port", "Port", "integer", 1, 65535),
    FieldSpec("auth_token_env", "Auth token env var", "nullable-text"),
)
FILE_BRIDGE_FIELDS = (
    FieldSpec("save_root", "Save root", "directory"),
    FieldSpec("max_text_bytes", "Maximum text bytes", "integer", 0, 104_857_600, "0 = no limit"),
    FieldSpec("port", "Port", "integer", 1, 65535),
)
COMMON_LOGIN_OPTIONS = (
    OptionSpec("account", "secret"), OptionSpec("password", "secret"),
    OptionSpec("interactive_login", "boolean"), OptionSpec("browser_profile_dir", "text"),
)
PROVIDER_OPTIONS = {
    "echo": (OptionSpec("prefix", "text"),),
    "gemini_webapi": COMMON_LOGIN_OPTIONS + (
        OptionSpec("secure_1psid_env", "text"), OptionSpec("secure_1psidts_env", "text"),
        OptionSpec("timeout", "integer"), OptionSpec("gemini_model", "text"),
    ),
    "copilot_webapi": COMMON_LOGIN_OPTIONS + (
        OptionSpec("access_token", "secret"), OptionSpec("access_token_env", "text"),
        OptionSpec("timezone", "text"), OptionSpec("chat_timeout", "integer"), OptionSpec("copilot_mode", "text"),
    ),
    "browser": (
        OptionSpec("account", "secret"), OptionSpec("password", "secret"), OptionSpec("headless", "boolean"),
        OptionSpec("user_data_dir", "text"), OptionSpec("timeout", "integer"),
        OptionSpec("response_appear_timeout", "integer"), OptionSpec("gemini_model", "text"),
    ),
}
SECRET_OPTION_KEYS = frozenset({"account", "password", "access_token"})
