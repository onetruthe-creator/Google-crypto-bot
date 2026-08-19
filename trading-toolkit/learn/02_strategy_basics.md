# Strategy Basics — Building a Real, Repeatable Plan

A "strategy" is not a feeling or a hot tip. It's a written rule set with four parts. If you can't write all four down in one sentence each, you don't have a strategy yet — you're gambling.

## The 4 required parts of any strategy

1. **Entry rule** — the exact, objective condition that triggers a trade.
   *Bad:* "it looks like it's about to go up."
   *Good:* "Price closes above the 50-day MA after touching it from above for the first time in 10+ days, on above-average volume."

2. **Stop-loss rule** — the exact price/condition that proves you're wrong, decided *before* entry.
   *Good:* "Stop placed 1 tick below the most recent swing low."

3. **Target/exit rule** — where you take profit, or the rule for trailing/scaling out.
   *Good:* "Target = 2x the distance from entry to stop (2R). Move stop to breakeven after price moves 1R in favor."

4. **Position size rule** — how much you risk, calculated from account size and stop distance (see the risk-management guide and the calculator tool). Never "however much feels right."

## Three beginner-friendly strategy archetypes

**A. Trend-following (moving average crossover / pullback)**
- Trade only in the direction of the higher-timeframe trend.
- Entry: price pulls back to a moving average (e.g., 20 EMA) in an established trend, then shows a reversal candle back in trend direction.
- Stop: below the pullback low (uptrend) / above the pullback high (downtrend).
- Target: prior swing high/low, or a fixed R-multiple.
- Pros: works well in trending markets, simple rules. Cons: whipsaws in choppy/range markets.

**B. Breakout**
- Entry: price closes beyond a well-tested support/resistance level or consolidation range, ideally on rising volume.
- Stop: back inside the broken range (i.e., the breakout failed).
- Target: measured move (height of the prior range projected from the breakout point), or next major level.
- Pros: catches big moves early. Cons: frequent false breakouts ("fakeouts") — needs volume/momentum confirmation.

**C. Mean-reversion / support-resistance bounce**
- Entry: price reaches a well-established support (or resistance) in a range-bound market and shows a rejection signal (pin bar, RSI oversold + bullish divergence, etc.).
- Stop: just beyond the support/resistance level.
- Target: opposite side of the range.
- Pros: good in sideways markets. Cons: dangerous in trending markets (you'll keep "buying the dip" into a real breakdown).

**Beginner recommendation:** pick ONE archetype, master it on demo/backtest across 50+ historical setups before trading it live. Don't mix strategies until the first one is profitable and well understood.

## Risk:Reward and win rate — the math that actually matters

Your long-run result ≈ `(Win rate × Average Win) − (Loss rate × Average Loss)`

You do **not** need a high win rate to be profitable if your reward:risk ratio is good:

| Win rate | Min R:R to break even (before costs) |
|---|---|
| 70% | 0.43:1 |
| 50% | 1:1 |
| 40% | 1.5:1 |
| 30% | 2.33:1 |

Most solid trend/breakout strategies run 35–50% win rate with 1.5–3R average winners. That is completely normal and profitable — don't expect to be right most of the time.

## Before going live: the validation checklist

- [ ] Strategy rules are written down in one page, no ambiguity
- [ ] Backtested on 50+ historical instances (use `tools/backtest.py` as a starting point)
- [ ] Forward-tested on a demo/paper account for at least 4–6 weeks of real-time signals
- [ ] You know your strategy's approximate win rate and average R from the above testing
- [ ] You have a written max daily loss and max drawdown rule (see risk-management guide)
- [ ] You have a trade journal ready (see `tools/trade_journal_template.csv`) and commit to logging every trade

## Common beginner mistakes to avoid

- Changing the strategy after every losing trade ("strategy hopping")
- Moving your stop-loss further away because you "believe" the price will come back
- Increasing position size after a losing streak to "win it back" (revenge trading)
- Trading multiple unrelated strategies at once with no clear rules for either
- Skipping the demo/backtest phase because it feels slow — this phase is what prevents blowing up real capital
