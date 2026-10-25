from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, TypeAlias
from urllib.parse import urlsplit
if TYPE_CHECKING:
    from ai_manager.config.models import AppAIConfig, ConfigSnapshot

EndpointValue: TypeAlias = Literal[
    "/v1/chat/completions", "/v1/responses", "/v1/messages"
]
LEGACY: Final[None] = None


@dataclass(frozen=True)
class Protocol:
    value: EndpointValue
    label: str
    auth_hint: str


PROTOCOLS: Final[tuple[Protocol, ...]] = (
    Protocol("/v1/chat/completions", "OpenAI Chat Completions", "Authorization: Bearer"),
    Protocol("/v1/responses", "OpenAI Responses", "Authorization: Bearer"),
    Protocol("/v1/messages", "Anthropic Messages", "x-api-key + anthropic-version: 2023-06-01"),
)
ENDPOINT_VALUES: Final[frozenset[str]] = frozenset(p.value for p in PROTOCOLS)


def is_valid_endpoint(value: object) -> bool:
    return isinstance(value, str) and value in ENDPOINT_VALUES


def compose_request_url(app_id: str, api_base: str, endpoint: str | None) -> str:
    raw = api_base.strip()
    if endpoint is not None:
        return raw.rstrip("/") + endpoint
    if app_id == "ai-grammar":
        base = raw if raw.rstrip("/").endswith("/v1") else raw.rstrip("/") + "/v1"
        return base + "/chat/completions"
    return raw.rstrip("/") + "/v1/chat/completions"


def base_conflicts_with_endpoint(api_base: str, endpoint: str | None) -> bool:
    if endpoint is None:
        return False
    try:
        path = urlsplit(api_base.strip()).path
    except ValueError:
        return False
    return path.rstrip("/").endswith("/v1")


def effective_api_base(app_id: str, draft: AppAIConfig, snapshot: ConfigSnapshot) -> str:
    if snapshot.api_base_present or draft.api_base != snapshot.config.api_base:
        return draft.api_base
    if app_id == "ai-grammar" and draft.endpoint is None:
        return "https://api.openai.com/v1"
    return "https://api.openai.com"
