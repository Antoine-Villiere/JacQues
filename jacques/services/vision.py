from __future__ import annotations

import base64
from pathlib import Path

from PIL import Image

from ..config import Settings
from .llm import LLMClient


def describe_image(path: Path, settings: Settings) -> str:
    if not settings.vision_enabled:
        return _basic_description(path, "Vision is disabled.")

    llm = LLMClient(settings)
    if not llm.available():
        return _basic_description(path, "LLM not configured for vision.")

    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = _guess_mime(path)
    messages = [
        {"role": "system", "content": "You are a vision assistant."},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Describe this image clearly and concisely.",
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                },
            ],
        },
    ]
    try:
        response = llm.chat(messages, model=settings.vision_model, stream=False)
    except Exception as exc:
        return _basic_description(path, f"Vision error: {exc}")
    content = response.get("content")
    if content:
        return str(content)
    return _basic_description(path, "No vision response received.")


def _basic_description(path: Path, note: str) -> str:
    with Image.open(path) as image:
        return (
            f"Image size {image.size[0]}x{image.size[1]}, "
            f"mode {image.mode}. {note}"
        )


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"
