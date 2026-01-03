from __future__ import annotations

import base64
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import Settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional
    OpenAI = None


def generate_image(prompt: str, output_path: Path, settings: Settings) -> Path:
    if settings.image_provider == "openai" and OpenAI and settings.image_api_key:
        client = OpenAI(api_key=settings.image_api_key)
        response = client.images.generate(
            model=settings.image_model,
            prompt=prompt,
            size="1024x1024",
        )
        image_b64 = response.data[0].b64_json
        output_path.write_bytes(base64.b64decode(image_b64))
        return output_path

    return _placeholder_image(prompt, output_path)


def _placeholder_image(prompt: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (768, 768), color=(18, 24, 32))
    draw = ImageDraw.Draw(image)
    text = "Image generation not configured\n" + prompt
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        font = None
    draw.multiline_text((32, 32), text, fill=(245, 230, 200), font=font, spacing=6)
    image.save(output_path)
    return output_path
