from typing import List, Optional
import httpx
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from ai_manager.config.models import ModelFetchRequest, ModelFetchResponse
from ai_manager.utils.env_resolver import resolve_api_key


def _normalize_models_payload(data) -> List[str]:
    """Normalizes models list from various API payload structures."""
    model_set = set()

    if isinstance(data, dict):
        # OpenAI style: {"data": [{"id": "gpt-4"}, ...]}
        if "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                if isinstance(item, dict) and "id" in item:
                    model_set.add(str(item["id"]))
                elif isinstance(item, str):
                    model_set.add(item)
        # Ollama style: {"models": [{"name": "llama3"}, ...]}
        elif "models" in data and isinstance(data["models"], list):
            for item in data["models"]:
                if isinstance(item, dict) and "name" in item:
                    model_set.add(str(item["name"]))
                elif isinstance(item, str):
                    model_set.add(item)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "id" in item:
                model_set.add(str(item["id"]))
            elif isinstance(item, str):
                model_set.add(item)

    return sorted(list(model_set), key=lambda s: s.lower())


def fetch_models_sync(request: ModelFetchRequest) -> ModelFetchResponse:
    """Synchronously queries /v1/models with fallback to /models."""
    resolved_key = resolve_api_key(request.api_key)
    base_url = request.api_base.rstrip("/")
    if not base_url:
        return ModelFetchResponse(
            token=request.token,
            success=False,
            error_message="API Base URL cannot be empty.",
        )

    headers = {
        "Accept": "application/json",
        "User-Agent": "ai-manager/0.1.0",
    }
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    timeout = httpx.Timeout(10.0, connect=5.0)

    # First attempt: /v1/models
    endpoints_to_try = [f"{base_url}/v1/models", f"{base_url}/models"]
    last_error: Optional[str] = None

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for url in endpoints_to_try:
            try:
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        models = _normalize_models_payload(data)
                        return ModelFetchResponse(
                            token=request.token,
                            success=True,
                            models=models,
                            endpoint_used=url,
                        )
                    except Exception as json_err:
                        last_error = f"Invalid JSON received from {url}: {json_err}"
                elif response.status_code == 404:
                    # Try next fallback endpoint
                    last_error = f"HTTP 404 Not Found at {url}"
                    continue
                elif response.status_code == 401:
                    return ModelFetchResponse(
                        token=request.token,
                        success=False,
                        error_message=f"HTTP 401 Unauthorized: Invalid or missing API key at {url}",
                    )
                else:
                    last_error = f"HTTP {response.status_code} ({response.reason_phrase}) from {url}"
            except httpx.ConnectError:
                last_error = f"Connection refused connecting to {url}"
            except httpx.TimeoutException:
                last_error = f"Request timed out connecting to {url}"
            except Exception as e:
                last_error = f"Network error connecting to {url}: {str(e)}"

    return ModelFetchResponse(
        token=request.token,
        success=False,
        error_message=last_error or "Failed to fetch models from provider.",
    )


class ModelFetchSignals(QObject):
    finished = pyqtSignal(ModelFetchResponse)


class ModelFetchWorker(QRunnable):
    """QRunnable background task executing fetch_models_sync."""

    def __init__(self, request: ModelFetchRequest):
        super().__init__()
        self.request = request
        self.signals = ModelFetchSignals()

    def run(self):
        resp = fetch_models_sync(self.request)
        self.signals.finished.emit(resp)
