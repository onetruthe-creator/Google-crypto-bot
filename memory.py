#!/usr/bin/env python3
"""
memory.py — SQLite-based agent memory for the crypto trading bot.

Think of this like a notebook the bot always carries around.
It writes down every Slack conversation and every trade so it never forgets.

Database lives at: ~/maxmillion/agent_memory.db

Tables
------
  messages  — every Slack message the bot sends or receives
  trades    — every trade executed through MaxMillion

Quick-start
-----------
  from memory import Memory
  mem = Memory()

  mem.save_message("user", "How is my portfolio?")
  mem.save_message("bot",  "Your balance is $10,042 with +$42 PnL today.")

  history = mem.get_history(limit=20)

  mem.save_trade("BTC/USDT", "buy", qty=0.005, fill_price=65000, pnl_tick=1.23, balance=10001.23)
  trades = mem.get_trades(limit=10)
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── Where the database lives ──────────────────────────────────────────────────
DB_PATH = Path.home() / "maxmillion" / "agent_memory.db"


class Memory:
    """
    Simple notebook for the trading bot.

    Every method opens the database, does its job, and closes it.
    That makes it safe to use from multiple scripts at once.
    """

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        # Make sure the folder exists before we try to create the file
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Open the database and make results come back as dictionaries."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row   # lets us use row["column_name"]
        conn.execute("PRAGMA journal_mode=WAL")  # safer for concurrent writes
        return conn

    def _create_tables(self):
        """
        Build the tables if they don't exist yet.
        Running this on every startup is safe — it only creates when missing.
        """
        with self._connect() as conn:
            conn.executescript("""
                -- Every Slack message the bot sees or sends
                CREATE TABLE IF NOT EXISTS messages (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    role      TEXT    NOT NULL,   -- "user" or "bot"
                    content   TEXT    NOT NULL,
                    channel   TEXT    DEFAULT '',  -- Slack channel or DM id
                    ts        TEXT    NOT NULL     -- ISO-8601 timestamp
                );

                -- Every trade sent to MaxMillion
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT    NOT NULL,   -- e.g. "BTC/USDT"
                    side        TEXT    NOT NULL,   -- "buy" or "sell"
                    qty         REAL    NOT NULL,   -- how many coins
                    fill_price  REAL    NOT NULL,   -- price the order filled at
                    pnl_tick    REAL    DEFAULT 0,  -- profit/loss from this single trade
                    balance     REAL    DEFAULT 0,  -- account balance after the trade
                    extra       TEXT    DEFAULT '{}', -- any extra JSON data (order id, etc.)
                    ts          TEXT    NOT NULL     -- ISO-8601 timestamp
                );
            """)

    @staticmethod
    def _now() -> str:
        """Current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    # ── Message methods ───────────────────────────────────────────────────────

    def save_message(self, role: str, content: str, channel: str = "") -> int:
        """
        Write one message to the notebook.

        Parameters
        ----------
        role    : "user" (person talking) or "bot" (bot's reply)
        content : the actual text
        channel : optional Slack channel/DM ID for context

        Returns the row ID (useful for linking records later).

        Example
        -------
        mem.save_message("user", "What is my balance?")
        mem.save_message("bot",  "Your balance is $10,042.", channel="C0ABC123")
        """
        if role not in ("user", "bot"):
            raise ValueError(f"role must be 'user' or 'bot', got: {role!r}")

        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages (role, content, channel, ts) VALUES (?, ?, ?, ?)",
                (role, content, channel, self._now()),
            )
            return cur.lastrowid

    def get_history(self, limit: int = 20, channel: str = "") -> list[dict]:
        """
        Read the most recent Slack messages, newest last (chat order).

        Parameters
        ----------
        limit   : how many messages to return (default 20)
        channel : if set, only return messages from that Slack channel

        Returns a list of dicts with keys: id, role, content, channel, ts

        Example
        -------
        history = mem.get_history(limit=10)
        for msg in history:
            print(f"[{msg['role']}] {msg['content']}")
        """
        with self._connect() as conn:
            if channel:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT id, role, content, channel, ts
                        FROM messages
                        WHERE channel = ?
                        ORDER BY id DESC
                        LIMIT ?
                    ) ORDER BY id ASC
                    """,
                    (channel, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT id, role, content, channel, ts
                        FROM messages
                        ORDER BY id DESC
                        LIMIT ?
                    ) ORDER BY id ASC
                    """,
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_history_as_chat(self, limit: int = 20, channel: str = "") -> list[dict]:
        """
        Return history in the OpenAI chat format that ZeroClaw / Ollama expects.

        Each item is {"role": "user"|"assistant", "content": "..."}

        Example
        -------
        messages = mem.get_history_as_chat(limit=10)
        # Pass directly to the LLM:
        # {"model": "llama3.2:1b", "messages": messages}
        """
        raw = self.get_history(limit=limit, channel=channel)
        return [
            {
                "role": "assistant" if row["role"] == "bot" else "user",
                "content": row["content"],
            }
            for row in raw
        ]

    # ── Trade methods ─────────────────────────────────────────────────────────

    def save_trade(
        self,
        symbol: str,
        side: str,
        qty: float,
        fill_price: float,
        pnl_tick: float = 0.0,
        balance: float = 0.0,
        extra: dict | None = None,
    ) -> int:
        """
        Write one trade to the notebook.

        Parameters
        ----------
        symbol     : trading pair, e.g. "BTC/USDT"
        side       : "buy" or "sell"
        qty        : how many coins were traded
        fill_price : the price the order was filled at
        pnl_tick   : profit or loss from this trade (can be negative)
        balance    : account balance after this trade
        extra      : any other data you want to save (dict → stored as JSON)

        Returns the row ID.

        Example
        -------
        mem.save_trade(
            symbol="BTC/USDT", side="buy",
            qty=0.005, fill_price=65000.0,
            pnl_tick=1.23, balance=10001.23,
            extra={"order_id": "mock-1234"},
        )
        """
        extra_json = json.dumps(extra or {})
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades
                    (symbol, side, qty, fill_price, pnl_tick, balance, extra, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, side, qty, fill_price, pnl_tick, balance, extra_json, self._now()),
            )
            return cur.lastrowid

    def get_trades(self, limit: int = 10, symbol: str = "") -> list[dict]:
        """
        Read the most recent trades, newest last.

        Parameters
        ----------
        limit  : how many trades to return (default 10)
        symbol : if set, only return trades for that coin pair (e.g. "BTC/USDT")

        Returns a list of dicts. The "extra" field is parsed back from JSON.

        Example
        -------
        trades = mem.get_trades(limit=5)
        for t in trades:
            print(f"{t['side'].upper()} {t['qty']} {t['symbol']} @ ${t['fill_price']:,.2f}")
        """
        with self._connect() as conn:
            if symbol:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT id, symbol, side, qty, fill_price, pnl_tick, balance, extra, ts
                        FROM trades
                        WHERE symbol = ?
                        ORDER BY id DESC
                        LIMIT ?
                    ) ORDER BY id ASC
                    """,
                    (symbol.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT id, symbol, side, qty, fill_price, pnl_tick, balance, extra, ts
                        FROM trades
                        ORDER BY id DESC
                        LIMIT ?
                    ) ORDER BY id ASC
                    """,
                    (limit,),
                ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            try:
                d["extra"] = json.loads(d["extra"])
            except (json.JSONDecodeError, TypeError):
                d["extra"] = {}
            result.append(d)
        return result

    def get_trade_summary(self) -> dict:
        """
        Quick stats across ALL trades ever recorded.

        Returns
        -------
        {
          "total_trades": 42,
          "total_pnl":    123.45,
          "win_count":    28,
          "loss_count":   14,
          "latest_balance": 10123.45,
          "symbols_traded": ["BTC/USDT", "ETH/USDT"]
        }
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)          AS total_trades,
                    SUM(pnl_tick)     AS total_pnl,
                    SUM(CASE WHEN pnl_tick > 0 THEN 1 ELSE 0 END) AS win_count,
                    SUM(CASE WHEN pnl_tick < 0 THEN 1 ELSE 0 END) AS loss_count,
                    MAX(balance)      AS latest_balance
                FROM trades
                """
            ).fetchone()

            symbols = conn.execute(
                "SELECT DISTINCT symbol FROM trades ORDER BY symbol"
            ).fetchall()

        return {
            "total_trades":    row["total_trades"] or 0,
            "total_pnl":       round(row["total_pnl"] or 0.0, 4),
            "win_count":       row["win_count"] or 0,
            "loss_count":      row["loss_count"] or 0,
            "latest_balance":  round(row["latest_balance"] or 0.0, 2),
            "symbols_traded":  [r["symbol"] for r in symbols],
        }


# ── Module-level singleton (optional convenience) ─────────────────────────────
# Other files can just do:
#   from memory import mem
#   mem.save_message("user", "hello")
mem = Memory()


# ── Quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Database: {DB_PATH}")
    m = Memory()

    # Write a test conversation
    m.save_message("user", "What is my balance?")
    m.save_message("bot",  "Your balance is $10,000 with $0 PnL so far today.")

    # Write a test trade
    m.save_trade(
        symbol="BTC/USDT", side="buy",
        qty=0.005, fill_price=65000.0,
        pnl_tick=1.23, balance=10001.23,
        extra={"order_id": "mock-self-test"},
    )

    print("\n--- Last 5 messages ---")
    for msg in m.get_history(limit=5):
        print(f"  [{msg['role']:4s}] {msg['content']}")

    print("\n--- Last 5 trades ---")
    for t in m.get_trades(limit=5):
        sign = "+" if t["pnl_tick"] >= 0 else ""
        print(f"  {t['side'].upper():4s} {t['qty']} {t['symbol']} "
              f"@ ${t['fill_price']:,.2f}  PnL: {sign}{t['pnl_tick']}")

    print("\n--- Trade summary ---")
    s = m.get_trade_summary()
    for k, v in s.items():
        print(f"  {k}: {v}")

    print("\nSelf-test passed.")
