import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env")


def _csv(name: str, default: str = "") -> list:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


class Settings:
    PROJECT_NAME: str = "DIAL-a-DEAL AI Backend"
    VERSION: str = "2.0.0"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1")

    # ---- AI credentials ----
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
    AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "centralindia")

    # ---- Speech-to-Text (Sarvam Saaras V4) ----
    SARVAM_STT_URL: str = os.getenv("SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text")
    SARVAM_STT_MODEL: str = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
    SARVAM_STT_MODE: str = os.getenv("SARVAM_STT_MODE", "transcribe")

    # ---- Conversational LLM (Groq-hosted, swappable) ----
    GROQ_LLM_MODEL: str = os.getenv("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
    GROQ_LLM_FALLBACK_MODEL: str = os.getenv("GROQ_LLM_FALLBACK_MODEL", "openai/gpt-oss-120b")

    # ---- Database ----
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./dial_a_deal.db")

    # ---- RAG ----
    KNOWLEDGE_BASE_DIR: Path = Path(os.getenv("KNOWLEDGE_BASE_DIR", str(BACKEND_DIR / "knowledge_base")))
    KB_JSONL_FILE: str = os.getenv("KB_JSONL_FILE", "fortivex_ai_rag_knowledge_base.jsonl")
    KB_MARKDOWN_FILE: str = os.getenv("KB_MARKDOWN_FILE", "fortivex_ai_rag_knowledge_base.md")
    CHROMA_DIR: str = os.getenv("CHROMA_DIR", str(BACKEND_DIR / "chroma_db"))
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "fortivex_kb")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "4"))
    RAG_MIN_SIMILARITY: float = float(os.getenv("RAG_MIN_SIMILARITY", "0.30"))

    # ---- Google (OAuth 2.0) ----
    GOOGLE_CLIENT_SECRETS_FILE: str = os.getenv(
        "GOOGLE_CLIENT_SECRETS_FILE", str(BACKEND_DIR / "secrets" / "google_client_secret.json")
    )
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_TOKEN_FILE: str = os.getenv("GOOGLE_TOKEN_FILE", str(BACKEND_DIR / "secrets" / "google_token.json"))
    GOOGLE_SCOPES: list = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    # ---- Scheduling ----
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
    FORTIVEX_CALENDAR_ID: str = os.getenv("FORTIVEX_CALENDAR_ID", "primary")
    # Fortivex team members who are added as attendees on every meeting (comma separated)
    FORTIVEX_TEAM_EMAILS: list = _csv("FORTIVEX_TEAM_EMAILS")
    MEETING_DEFAULT_DURATION_MIN: int = int(os.getenv("MEETING_DEFAULT_DURATION_MIN", "30"))
    # Team working window used only when proposing alternative slots (real busy data still comes from Google)
    MEETING_WORK_START_HOUR: int = int(os.getenv("MEETING_WORK_START_HOUR", "10"))
    MEETING_WORK_END_HOUR: int = int(os.getenv("MEETING_WORK_END_HOUR", "18"))
    MEETING_WORK_DAYS: list = [int(x) for x in _csv("MEETING_WORK_DAYS", "0,1,2,3,4,5")]  # Mon=0 .. Sun=6
    EMAIL_SENDER_NAME: str = os.getenv("EMAIL_SENDER_NAME", "Fortivex AI Team")

    # ---- CORS / server ----
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # ---- Languages ----
    SUPPORTED_LANGUAGES = {
        "en": "en-IN",
        "hi": "hi-IN",
        "ta": "ta-IN",
        "te": "te-IN",
        "ml": "ml-IN",
    }
    LANGUAGE_NAMES = {
        "en-IN": "English",
        "hi-IN": "Hindi",
        "ta-IN": "Tamil",
        "te-IN": "Telugu",
        "ml-IN": "Malayalam",
    }

    # Azure Neural Voice Mapping
    AZURE_VOICES = {
        "en-IN": "en-IN-NeerjaNeural",
        "hi-IN": "hi-IN-SwaraNeural",
        "ta-IN": "ta-IN-PallaviNeural",
        "te-IN": "te-IN-ShrutiNeural",
        "ml-IN": "ml-IN-SobhanaNeural",
    }


settings = Settings()
