from __future__ import annotations
import logging
import time
from .bitunix_client import BitunixClient, BitunixError
from .config import Config
from .detector import parse_candle, find_resistance_levels, detect_breakout, detect_retest, detect_rejection
from .gates import check_gates, setup_still_valid
from .notifier import send_alert, send_withdrawal
from .state import Phase, StateManager, SymbolState

logger = logging.getLogger(__name__)


def _process_symbol(
    symbol: str,
    client: BitunixClient,
    cfg: Config,
    state_mgr: StateManager,
) -> None:
    det = cfg["detector"]
    gates_cfg = cfg["gates"]
    notif = cfg["notifier"]

    try:
        raw_klines = client.get_klines(symbol, interval=det["kline_interval"], limit=det["kline_limit"])
    except BitunixError as exc:
        logger.warning("klines fetch failed for %s: %s", symbol, exc)
        return

    candles = [parse_candle(r) for r in raw_klines]
    if len(candles) < det["swing_lookback"] * 2 + 5:
        logger.debug("%s: not enough candles (%d)", symbol, len(candles))
        return

    state = state_mgr.get(symbol)
    now_ts = int(time.time() * 1000)

    # --- Check setup validity for in-progress setups ---
    if state.phase not in (Phase.NONE, Phase.CONFIRMED, Phase.WITHDRAWN):
        if not setup_still_valid(candles, state):
            if not state.withdrawal_sent:
                send_withdrawal(symbol, state, notif["output_file"], notif["webhook_url"])
                state.withdrawal_sent = True
                state.phase = Phase.WITHDRAWN
                state_mgr.set(state)
                logger.info("%s: withdrawal sent (setup invalidated)", symbol)
            state_mgr.reset(symbol)
            return

    # --- Already confirmed or withdrawn, skip ---
    if state.phase in (Phase.CONFIRMED, Phase.WITHDRAWN):
        return

    resistance_levels = find_resistance_levels(candles[:-3], det["swing_lookback"])

    # --- Phase: NONE → detect breakout ---
    if state.phase == Phase.NONE:
        for level in sorted(resistance_levels, reverse=True):
            if detect_breakout(candles, level, det["breakout_volume_multiplier"]):
                state.phase = Phase.BREAKOUT
                state.level = level
                state.breakout_ts = now_ts
                state.alert_sent = False
                state.withdrawal_sent = False
                state_mgr.set(state)
                logger.info("%s: breakout above %.4f", symbol, level)
                break
        return

    # --- Phase: BREAKOUT → detect retest ---
    if state.phase == Phase.BREAKOUT:
        if detect_retest(candles, state.level, det["retest_tolerance_pct"]):
            state.phase = Phase.RETEST
            state.retest_ts = now_ts
            state_mgr.set(state)
            logger.info("%s: retest of level %.4f", symbol, state.level)
        return

    # --- Phase: RETEST → detect rejection ---
    if state.phase == Phase.RETEST:
        if detect_rejection(candles, state.level, det["rejection_min_move_pct"]):
            state.phase = Phase.REJECTION
            state.rejection_ts = now_ts
            state_mgr.set(state)
            logger.info("%s: rejection from level %.4f", symbol, state.level)
        return

    # --- Phase: REJECTION → check gates (first pass) ---
    if state.phase == Phase.REJECTION:
        gate_result = check_gates(
            candles, state,
            rsi_period=gates_cfg["rsi_period"],
            rsi_max=gates_cfg["rsi_max"],
            min_volume_usdt=gates_cfg["min_volume_usdt"],
        )
        if gate_result.passed:
            state.phase = Phase.PENDING
            state.pending_ts = now_ts
            state_mgr.set(state)
            logger.info("%s: gates passed (first), awaiting confirmation", symbol)
        else:
            logger.debug("%s: gates not passed: %s", symbol, gate_result.reasons)
        return

    # --- Phase: PENDING → check gates (second consecutive pass) ---
    if state.phase == Phase.PENDING:
        gate_result = check_gates(
            candles, state,
            rsi_period=gates_cfg["rsi_period"],
            rsi_max=gates_cfg["rsi_max"],
            min_volume_usdt=gates_cfg["min_volume_usdt"],
        )
        if gate_result.passed:
            send_alert(symbol, state, notif["output_file"], notif["webhook_url"])
            state.phase = Phase.CONFIRMED
            state.alert_sent = True
            state_mgr.set(state)
            logger.info("%s: CONFIRMED_ANALYSIS sent (AUTHORIZATION: NONE)", symbol)
        else:
            # Gates failed on second pass — revert to REJECTION phase
            state.phase = Phase.REJECTION
            state.pending_ts = None
            state_mgr.set(state)
            logger.info("%s: gates failed second pass, reverting to rejection", symbol)


def run_monitor(cfg: Config, client: BitunixClient, state_mgr: StateManager, symbols: list[str]) -> None:
    for symbol in symbols:
        try:
            _process_symbol(symbol, client, cfg, state_mgr)
        except Exception as exc:
            logger.error("error processing %s: %s", symbol, exc, exc_info=True)
    state_mgr.save()
