"""Ollama REST API client for vision model inference."""

import base64
import json
import logging
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

PROMPT_DESCRIBE_SCREEN = (
    "Describe what is shown on this computer screen for a visually impaired user. "
    "Mention the application being used, visible UI elements, text content, and "
    "the general layout. Be thorough but concise."
)


def check_server(server_url: str, timeout: float = 5.0) -> bool:
    """Return True if the Ollama server is reachable."""
    try:
        r = requests.get(server_url, timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def list_models(server_url: str, timeout: float = 10.0) -> list[str]:
    """Return names of all models installed on the Ollama server."""
    try:
        r = requests.get(f"{server_url}/api/tags", timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return [m["name"] for m in data.get("models", [])]
    except requests.RequestException as e:
        logger.warning("Failed to list Ollama models: %s", e)
        return []


def generate_with_image(
    server_url: str,
    model: str,
    prompt: str,
    image_bytes: bytes,
    timeout: float = 120.0,
) -> Optional[str]:
    """Send an image + prompt to an Ollama vision model and return the text response.

    Args:
        server_url: Ollama server base URL.
        model: Model name (e.g. "llava").
        prompt: Text prompt to send with the image.
        image_bytes: Raw PNG bytes of the screenshot.
        timeout: Request timeout in seconds.

    Returns:
        The model's text response, or None on failure.
    """
    b64_image = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64_image],
            }
        ],
        "stream": False,
    }
    try:
        r = requests.post(
            f"{server_url}/api/chat",
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.error(
                "Ollama model '%s' not found. Pull it with: ollama pull %s", model, model
            )
        else:
            logger.error("Ollama generate failed: %s", e)
        return None
    except requests.RequestException as e:
        logger.error("Ollama generate failed: %s", e)
        return None


def pull_model(
    server_url: str,
    model_name: str,
    progress_callback: Optional[Callable[[float], None]] = None,
    timeout: float = 600.0,
) -> bool:
    """Pull (download) a model from the Ollama library.

    Streams progress and calls *progress_callback(percent)* for each update.
    Returns True on success.
    """
    payload = {"name": model_name, "stream": True}
    try:
        r = requests.post(
            f"{server_url}/api/pull",
            json=payload,
            stream=True,
            timeout=timeout,
        )
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            status = data.get("status", "")
            total = data.get("total", 0)
            completed = data.get("completed", 0)
            if total and progress_callback:
                progress_callback(completed / total * 100.0)
            if status == "success":
                if progress_callback:
                    progress_callback(100.0)
                return True
            if "error" in data:
                logger.error("Ollama pull error: %s", data["error"])
                return False
        return True
    except requests.RequestException as e:
        logger.error("Ollama pull failed: %s", e)
        return False


def delete_model(server_url: str, model_name: str, timeout: float = 30.0) -> bool:
    """Delete a model from the Ollama server."""
    try:
        r = requests.delete(
            f"{server_url}/api/delete",
            json={"name": model_name},
            timeout=timeout,
        )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Ollama delete failed: %s", e)
        return False
