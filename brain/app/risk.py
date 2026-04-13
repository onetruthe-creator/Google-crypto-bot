"""Risk policy — deterministic checks run before any approval request.

Returns a (risk_score, violations) tuple.
violations → non-empty means the signal is hard-blocked (no Slack prompt).
risk_score → advisory: LOW / MED / HIGH.
"""
from app.config import get_settings

RISK_LOW = "LOW"
RISK_MED = "MED"
RISK_HIGH = "HIGH"

ALLOWED_SIDES = {"BUY", "SELL"}
ALLOWED_SYMBOLS_WHITELIST: set[str] = set()  # empty = allow all; populate to restrict


def assess_risk(signal: dict) -> tuple[str, list[str]]:
    """
    Returns (risk_score, violations).
    Hard violations block execution outright; the caller handles them.
    """
    settings = get_settings()
    violations: list[str] = []
    flags: list[str] = []

    # --- Hard checks (schema / sanity) ---
    side = (signal.get("side") or "").upper()
    if side not in ALLOWED_SIDES:
        violations.append(f"Invalid side '{side}' — must be BUY or SELL")

    qty = float(signal.get("qty") or 0)
    if qty <= 0:
        violations.append("qty must be > 0")

    symbol = (signal.get("symbol") or "").upper()
    if not symbol:
        violations.append("symbol is required")

    if ALLOWED_SYMBOLS_WHITELIST and symbol not in ALLOWED_SYMBOLS_WHITELIST:
        violations.append(f"Symbol '{symbol}' not in whitelist")

    notional = float(signal.get("notional_usd") or 0)

    if notional > settings.MAX_NOTIONAL_USD:
        violations.append(
            f"Notional ${notional:,.2f} exceeds hard cap ${settings.MAX_NOTIONAL_USD:,.2f}"
        )

    if violations:
        return RISK_HIGH, violations

    # --- Advisory checks (no block, affects score) ---
    if notional >= settings.REQUIRE_APPROVAL_THRESHOLD_USD:
        # Always HIGH — will require explicit Slack approval regardless of AUTO_APPROVE_LOW_RISK
        return RISK_HIGH, []

    if notional >= settings.REQUIRE_APPROVAL_THRESHOLD_USD * 0.75:
        flags.append("notional_near_threshold")

    if flags:
        return RISK_MED, []

    return RISK_LOW, []
