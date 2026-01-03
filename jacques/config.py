from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".nev")

_data_dir_env = os.getenv("JACQUES_DATA_DIR")
if _data_dir_env:
    data_dir = Path(_data_dir_env).expanduser()
    if not data_dir.is_absolute():
        data_dir = (BASE_DIR / data_dir).resolve()
else:
    data_dir = Path.home() / ".jacques"
DATA_DIR = data_dir
UPLOADS_DIR = DATA_DIR / "uploads"
IMAGES_DIR = DATA_DIR / "images"
GENERATED_DIR = DATA_DIR / "generated"
EXPORTS_DIR = DATA_DIR / "exports"
RAG_INDEX_DIR = DATA_DIR / "rag_indexes"
DB_PATH = DATA_DIR / "jacques.db"


@dataclass
class Settings:
    litellm_provider: str | None = field(
        default_factory=lambda: os.getenv("LITELLM_PROVIDER")
    )
    litellm_api_key: str | None = field(
        default_factory=lambda: (
            os.getenv("LITELLM_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
        )
    )
    litellm_api_base: str | None = field(
        default_factory=lambda: os.getenv("LITELLM_API_BASE")
    )
    text_model: str = field(
        default_factory=lambda: os.getenv("TEXT_MODEL", "groq/openai/gpt-oss-120b")
    )
    reasoning_model: str = field(
        default_factory=lambda: os.getenv(
            "REASONING_MODEL", "groq/openai/gpt-oss-120b"
        )
    )
    vision_model: str = field(
        default_factory=lambda: os.getenv(
            "VISION_MODEL", "groq/meta-llama/llama-4-maverick-17b-128e-instruct"
        )
    )
    vision_enabled: bool = field(
        default_factory=lambda: os.getenv("VISION_ENABLED", "true").lower() == "true"
    )
    image_provider: str = field(
        default_factory=lambda: os.getenv("IMAGE_PROVIDER", "openai")
    )
    image_api_key: str | None = field(
        default_factory=lambda: os.getenv("IMAGE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    image_model: str = field(
        default_factory=lambda: os.getenv("IMAGE_MODEL", "gpt-image-1")
    )
    web_timeout: int = field(
        default_factory=lambda: int(os.getenv("WEB_TIMEOUT", "10"))
    )
    brave_api_key: str | None = field(
        default_factory=lambda: os.getenv("BRAVE_API_KEY")
    )
    brave_country: str | None = field(
        default_factory=lambda: os.getenv("BRAVE_COUNTRY")
    )
    brave_search_lang: str | None = field(
        default_factory=lambda: os.getenv("BRAVE_SEARCH_LANG")
    )
    rag_top_k: int = field(
        default_factory=lambda: int(os.getenv("RAG_TOP_K", "4"))
    )
    max_history_messages: int = field(
        default_factory=lambda: int(os.getenv("MAX_HISTORY_MESSAGES", "40"))
    )
    max_tool_calls: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOOL_CALLS", "4"))
    )
    llm_streaming: bool = field(
        default_factory=lambda: os.getenv("LLM_STREAMING", "true").lower() == "true"
    )
    app_timezone: str = field(
        default_factory=lambda: os.getenv("APP_TIMEZONE", "Europe/Zurich")
    )
    app_base_url: str = field(
        default_factory=lambda: os.getenv("APP_BASE_URL", "http://127.0.0.1:8050")
    )
    onlyoffice_url: str | None = field(
        default_factory=lambda: os.getenv("ONLYOFFICE_URL")
    )
    onlyoffice_jwt: str | None = field(
        default_factory=lambda: os.getenv("ONLYOFFICE_JWT")
    )


def ensure_dirs() -> None:
    for path in [
        DATA_DIR,
        UPLOADS_DIR,
        IMAGES_DIR,
        GENERATED_DIR,
        EXPORTS_DIR,
        RAG_INDEX_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
