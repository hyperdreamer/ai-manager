from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


class ServiceRunState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"


class AppAIConfig(BaseModel):
    """Normalized AI configuration for an application."""
    api_base: str = "http://127.0.0.1:3000"
    api_key: str = ""
    # Single model mode:
    model: Optional[str] = None
    # Split model mode (e.g. textkit):
    is_split_model: bool = False
    ocr_model: Optional[str] = None
    text_model: Optional[str] = None

    def get_display_model(self) -> str:
        if self.is_split_model:
            return f"OCR: {self.ocr_model or 'none'} | Text: {self.text_model or 'none'}"
        return self.model or "none"


ConfigKind = Literal["llm", "chat2api", "file-bridge"]


class AppMetadata(BaseModel):
    """Metadata describing a managed target application."""
    id: str
    display_name: str
    relative_path: Path
    config_file_name: str = "config.yaml"
    example_config_file_name: str = "config.example.yaml"
    default_port: int
    supports_split_models: bool = False
    description: str = ""
    config_kind: ConfigKind = "llm"

    @field_validator("config_kind", mode="before")
    @classmethod
    def validate_config_kind(cls, value: object) -> object:
        if type(value) is not str or value not in (
            "llm", "chat2api", "file-bridge"
        ):
            raise ValueError(
                f"Unknown config_kind {value!r}; expected llm, chat2api, or file-bridge."
            )
        return value


class ProviderPreset(BaseModel):
    """Preconfigured AI provider template."""
    id: str
    name: str
    api_base: str
    default_key_env_var: Optional[str] = None
    docs_url: Optional[str] = None
    description: str = ""


class ServiceStatus(BaseModel):
    """Runtime status of a single supervised backend service."""
    service_id: str
    state: ServiceRunState = ServiceRunState.UNKNOWN
    pid: Optional[int] = None
    log_path: Optional[str] = None


class SupervisorStatus(BaseModel):
    """Global supervisor daemon status."""
    is_running: bool = False
    supervisor_pid: Optional[int] = None
    services: Dict[str, ServiceStatus] = Field(default_factory=dict)
    timestamp: str = ""


class ModelFetchRequest(BaseModel):
    """Request payload sent to background model fetcher worker."""
    token: int
    api_base: str
    api_key: str
    app_id: str = Field(strict=True, min_length=1)


class ModelFetchResponse(BaseModel):
    """Result emitted by background model fetcher worker."""
    token: int
    success: bool
    models: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    endpoint_used: Optional[str] = None


class UserSettings(BaseModel):
    """Global user settings persisted in ~/.config/ai-manager/settings.json."""
    theme: ThemeMode = ThemeMode.DARK
    poll_interval_ms: int = 4000
    custom_presets: List[ProviderPreset] = Field(default_factory=list)
    close_to_tray: bool = True
    start_minimized: bool = False
    autostart: bool = False
    first_close_notice_shown: bool = False
