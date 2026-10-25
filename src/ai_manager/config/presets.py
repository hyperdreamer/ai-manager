from collections.abc import Sequence
from typing import List
from ai_manager.config.models import ProviderPreset

DEFAULT_PRESETS: List[ProviderPreset] = [
    ProviderPreset(
        id="one_api_local",
        name="Local One-API / New-API (Port 3000)",
        api_base="http://127.0.0.1:3000",
        default_key_env_var="ONEAPI_API_KEY",
        description="Local OpenAI-compatible aggregator gateway",
    ),
    ProviderPreset(
        id="chat2api_local",
        name="Local chat2api Gateway (Port 8000)",
        api_base="http://127.0.0.1:8000",
        default_key_env_var="CHAT2API_TOKEN",
        description="Local web API bridge for Gemini and Copilot",
    ),
    ProviderPreset(
        id="tencent_tokenhub",
        name="Tencent TokenHub Maas",
        api_base="https://tokenhub.tencentmaas.com",
        default_key_env_var="TENCENTTOKENHUB_API_KEY",
        docs_url="https://tokenhub.tencentmaas.com",
        description="DeepSeek, Qwen and Chinese model provider",
    ),
    ProviderPreset(
        id="openai_official",
        name="Official OpenAI API",
        api_base="https://api.openai.com",
        default_key_env_var="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/docs",
        description="Official OpenAI endpoints for GPT and audio transcription",
    ),
    ProviderPreset(
        id="custom",
        name="Custom OpenAI-Compatible Provider",
        api_base="http://127.0.0.1:8080",
        description="User-defined endpoint and API key",
    ),
    ProviderPreset(
        id="anthropic_official",
        name="Official Anthropic API",
        api_base="https://api.anthropic.com",
        default_key_env_var="ANTHROPIC_API_KEY",
        endpoint="/v1/messages",
        docs_url="https://docs.anthropic.com",
        description="Claude models over the Anthropic Messages protocol",
    ),
]


def resolve_preset(
    preset_id: str, *, presets: Sequence[ProviderPreset] | None = None
) -> ProviderPreset | None:
    offered = DEFAULT_PRESETS if presets is None else presets
    return next((preset for preset in offered if preset.id == preset_id), None)
