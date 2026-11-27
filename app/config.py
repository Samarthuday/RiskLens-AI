import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class Settings:
    database_path: Path = Path(os.getenv("RISKLENS_DATABASE_URL", "sqlite:///./data/risklens.sqlite3").removeprefix("sqlite:///"))
    model_path: Path = Path(os.getenv("RISKLENS_MODEL_PATH", str(ROOT / "artifacts/risk_model.joblib")))
    model_sha256: str | None = os.getenv("RISKLENS_MODEL_SHA256") or None
    demo_seed: int = int(os.getenv("RISKLENS_DEMO_SEED", "41"))
    rate_limit_per_minute: int = int(os.getenv("RISKLENS_RATE_LIMIT_PER_MINUTE", "120"))
    llm_base_url: str | None = os.getenv("RISKLENS_LLM_BASE_URL") or None
    llm_api_key: str | None = os.getenv("RISKLENS_LLM_API_KEY") or None
    llm_model: str | None = os.getenv("RISKLENS_LLM_MODEL") or None
    allow_synthetic_llm: bool = os.getenv("RISKLENS_ALLOW_SYNTHETIC_LLM", "false").lower() == "true"
    session_isolation: bool = os.getenv("RISKLENS_SESSION_ISOLATION", "true").lower() == "true"
    session_secret: str = os.getenv("RISKLENS_SESSION_SECRET", "") or secrets.token_urlsafe(48)
    session_cookie_secure: bool = os.getenv("RISKLENS_SESSION_COOKIE_SECURE", "false").lower() == "true"
    max_demo_sessions: int = max(1, int(os.getenv("RISKLENS_MAX_DEMO_SESSIONS", "500")))
    razorpay_mode: str = os.getenv("RISKLENS_RAZORPAY_MODE", "disabled").lower()
    razorpay_test_webhook_secret: str | None = os.getenv("RISKLENS_RAZORPAY_TEST_WEBHOOK_SECRET") or None
    razorpay_test_read_token: str | None = os.getenv("RISKLENS_RAZORPAY_TEST_READ_TOKEN") or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
