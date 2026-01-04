import base64
import os
import re
from typing import Tuple


def safe_filename(filename: str) -> str:
    name = os.path.basename(filename)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "file"


def decode_upload(contents: str) -> Tuple[bytes, str]:
    header, encoded = contents.split(",", 1)
    data = base64.b64decode(encoded)
    return data, header

