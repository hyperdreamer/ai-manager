from __future__ import annotations
import copy
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ai_manager.config.config_errors import (
    ConfigValidationError,
    UnknownConfigKindError,
)
from ai_manager.config.structured_models import FieldIssue, Mutation, StructuredKind


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


Port = Annotated[StrictInt, Field(ge=1, le=65535)]
TextLimit = Annotated[StrictInt, Field(ge=0, le=104_857_600)]
ProviderName = Literal["echo", "gemini_webapi", "copilot_webapi", "browser"]
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

HOST_LOOPBACK_MESSAGE = (
    "Host must be a loopback address (127.0.0.1, localhost, or ::1). "
    "Binding a wildcard or external interface is not supported for this local service."
)
CONTROL_MESSAGE = (
    "This value must not contain newline, carriage return, or NUL characters."
)


class Chat2ApiServerSchema(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    host: StrictStr = Field(default="127.0.0.1", min_length=1)
    port: Port = 8000
    auth_token_env: StrictStr | None = "CHAT2API_TOKEN"

    @field_validator("host")
    @classmethod
    def validate_loopback_host(cls, value: str) -> str:
        """R-HOST-LOOPBACK: exact loopback spelling, no stripping."""
        if value in ("127.0.0.1", "::1"):
            return value
        if value.lower() == "localhost":
            return value
        raise ValueError(HOST_LOOPBACK_MESSAGE)

    @field_validator("auth_token_env")
    @classmethod
    def validate_auth_name(cls, value: str | None) -> str | None:
        if value is not None and ENV_NAME_RE.fullmatch(value) is None:
            raise ValueError(
                "Auth token environment variable must be null or a valid "
                "environment variable name."
            )
        return value


class Chat2ApiRouteSchema(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    provider: ProviderName
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options", mode="before")
    @classmethod
    def validate_options_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("Model options must be a mapping when present.")
        return value


class Chat2ApiSchema(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    # Validate a raw mapping default through the same shape guard as explicit input.
    server: Chat2ApiServerSchema = Field(default_factory=dict)
    models: dict[str, Chat2ApiRouteSchema] = Field(default_factory=dict)

    @field_validator("server", mode="before")
    @classmethod
    def validate_server_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("Server must be a mapping when present.")
        return value

    @field_validator("models", mode="before")
    @classmethod
    def validate_models_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("Models must be a mapping.")
        for name, route in value.items():
            if type(name) is not str or name == "":
                raise ValueError("Model names must be non-empty strings.")
            if not isinstance(route, dict):
                raise ValueError(f"Model {name!r} must be a mapping.")
        return value


class FileBridgeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)
    save_root: StrictStr = "~"
    max_text_bytes: TextLimit = 1_048_576
    port: Port = 8964

    @field_validator("save_root")
    @classmethod
    def validate_root_text(cls, value: str) -> str:
        if not value or value.isspace():
            raise ValueError("Save root must not be empty or whitespace-only.")
        return value

    @model_validator(mode="after")
    def validate_root_directory(self, info: ValidationInfo) -> FileBridgeSchema:
        context = info.context or {}
        if "config_path" not in context or "app_dir" not in context:
            raise ValueError("File-bridge validation requires config_path and app_dir.")
        try:
            config_path = Path(context["config_path"])
            app_dir = Path(context["app_dir"]).resolve()
            root = Path(self.save_root).expanduser()
            if not root.is_absolute():
                root = config_path.parent / root
            root = root.resolve()
            if root == app_dir or app_dir in root.parents:
                raise ValueError("Save root must not be inside the application directory.")
            root_stat = root.stat()
            if not stat.S_ISDIR(root_stat.st_mode):
                raise ValueError("Save root is not a directory.")
            if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
                raise ValueError("Save root must be readable and writable.")
            with os.scandir(root) as entries:
                next(entries, None)
            with tempfile.TemporaryFile(dir=root):
                pass
        except FileNotFoundError as exc:
            raise ValueError("Save root does not exist.") from exc
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Save root cannot be used: {exc}") from exc
        return self


def validate_written_scalars(mutations: tuple[Mutation, ...]) -> None:
    """Stage 1: reject control characters only in values this save writes."""
    issues: list[FieldIssue] = []

    def string(value: object, address: tuple[str, ...]) -> None:
        if isinstance(value, str) and any(c in value for c in ("\n", "\r", "\0")):
            issues.append(FieldIssue(address, CONTROL_MESSAGE))

    def visit(value: object, address: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                string(key, address + (str(key),))
                visit(child, address + (str(key),))
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, address + (str(index),))
        else:
            string(value, address)

    for mutation in mutations:
        if mutation.operation == "set":
            # A newly written key is a written scalar too, even when its value is a mapping.
            string(mutation.address[-1], mutation.address)
            visit(mutation.value, mutation.address)
    if issues:
        raise ConfigValidationError(tuple(issues))


def _plain(value: object) -> Any:
    """Deep-copy the candidate into plain Python containers, never aliasing it."""
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return copy.deepcopy(value)


def _issue(kind: StructuredKind, error: Mapping[str, Any]) -> FieldIssue:
    address = tuple(str(key) for key in error["loc"])
    raw = str(error["msg"])
    message = raw.removeprefix("Value error, ")
    key = address[-1] if address else "save_root"
    if key == "host" and error["type"] != "value_error":
        message = "Host must be a non-empty string."
    elif key == "port":
        message = "Port must be an integer from 1 to 65535."
    elif key == "auth_token_env":
        message = (
            "Auth token environment variable must be null or a valid "
            "environment variable name."
        )
    elif key == "provider":
        message = "Provider must be echo, gemini_webapi, copilot_webapi, or browser."
    elif key == "max_text_bytes":
        message = "Maximum text bytes must be an integer from 0 to 104857600."
    elif kind == "file-bridge" and error["type"] == "extra_forbidden":
        message = f"Unknown file-bridge configuration key: {key}"
    elif key == "save_root" and error["type"] != "value_error":
        message = "Save root must not be empty or whitespace-only."
    if kind == "file-bridge" and not address:
        address = ("save_root",)
    return FieldIssue(address, message)


def validate_in_process(
    kind: StructuredKind,
    candidate: Mapping[str, Any],
    *,
    config_path: Path,
    app_dir: Path,
) -> None:
    """Stage 2: validate a candidate tree without mutating or replacing it."""
    if kind not in ("chat2api", "file-bridge"):
        raise UnknownConfigKindError(kind)
    try:
        plain = _plain(candidate)
        if kind == "chat2api":
            Chat2ApiSchema.model_validate(plain)
        else:
            FileBridgeSchema.model_validate(
                plain, context={"config_path": config_path, "app_dir": app_dir}
            )
    except ValidationError as exc:
        raise ConfigValidationError(
            tuple(_issue(kind, error) for error in exc.errors(include_input=False))
        ) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        address = ("save_root",) if kind == "file-bridge" else ()
        raise ConfigValidationError((FieldIssue(address, str(exc)),)) from exc
