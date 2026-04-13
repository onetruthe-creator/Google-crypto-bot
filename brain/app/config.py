import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        self.APP_ENV = os.getenv("APP_ENV", "prod")
        self.API_HOST = os.getenv("API_HOST", "0.0.0.0")
        self.API_PORT = int(os.getenv("API_PORT", "8080"))

        self.DATABASE_PATH = os.getenv("DATABASE_PATH", "./brain.db")

        # Metaclaw webhook authentication
        self.METACLAW_WEBHOOK_SECRET = os.getenv("METACLAW_WEBHOOK_SECRET", "")

        # Slack
        self.SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
        self.SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
        self.SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "")
        self.SLACK_ADMIN_USER_ID = os.getenv("SLACK_ADMIN_USER_ID", "")

        # Risk policy
        self.MAX_NOTIONAL_USD = float(os.getenv("MAX_NOTIONAL_USD", "2000.0"))
        # Signals at or above this threshold always require explicit Slack approval
        self.REQUIRE_APPROVAL_THRESHOLD_USD = float(
            os.getenv("REQUIRE_APPROVAL_THRESHOLD_USD", "100.0")
        )
        # When True, LOW-risk signals below threshold are auto-approved (use with care)
        self.AUTO_APPROVE_LOW_RISK = (
            os.getenv("AUTO_APPROVE_LOW_RISK", "false").lower() == "true"
        )

        # Bearer token for internal management endpoints (/killswitch, /signals, /audit)
        self.BRAIN_API_KEY = os.getenv("BRAIN_API_KEY", "")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
