import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigurationError(Exception):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    project_root: Path
    clinic_timezone: ZoneInfo
    gemini_model: str
    elevenlabs_stt_model: str
    elevenlabs_tts_model: str
    google_api_key: str | None
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None

    @property
    def seed_path(self) -> Path:
        return self.project_root / "backend" / "data" / "seed.json"

    @property
    def state_path(self) -> Path:
        return self.project_root / "backend" / "data" / "state.json"


def load_settings(require_voice_credentials: bool = False) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    timezone_name = os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata").strip()
    try:
        clinic_timezone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ConfigurationError(
            "CLINIC_TIMEZONE must name a valid IANA timezone, for example Asia/Kolkata."
        ) from exc

    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip() or None
    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "").strip() or None
    elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or None
    if require_voice_credentials:
        missing = [
            variable
            for variable, value in (
                ("GOOGLE_API_KEY", google_api_key),
                ("ELEVENLABS_API_KEY", elevenlabs_api_key),
                ("ELEVENLABS_VOICE_ID", elevenlabs_voice_id),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Missing required voice configuration: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill in the values."
            )

    return Settings(
        project_root=PROJECT_ROOT,
        clinic_timezone=clinic_timezone,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        elevenlabs_stt_model=os.getenv(
            "ELEVENLABS_STT_MODEL", "scribe_v2_realtime"
        ).strip(),
        elevenlabs_tts_model=os.getenv(
            "ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5"
        ).strip(),
        google_api_key=google_api_key,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
    )
