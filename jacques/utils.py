import base64
import os
import re
from pathlib import Path
from typing import Tuple


def safe_filename(filename: str) -> str:
    name = os.path.basename(filename)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "file"


def decode_upload(contents: str) -> Tuple[bytes, str]:
    header, encoded = contents.split(",", 1)
    data = base64.b64decode(encoded)
    return data, header


def encode_image_to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    mime = "image/png"
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif path.suffix.lower() == ".gif":
        mime = "image/gif"
    return f"data:{mime};base64,{encoded}"
