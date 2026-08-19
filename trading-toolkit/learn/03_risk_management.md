# Risk Management — The Part That Determines Whether You Survive

This is the section that the "40-day, 14%/day, 100% of account" plan skipped entirely — and it's the most important part of trading. A mediocre strategy with great risk management can be profitable. A great strategy with no risk management will eventually go to zero.

## Core rule: risk a small, fixed % of account per trade

**Never risk more than 1–2% of your account on a single trade** (beginners: start at 0.5–1%).

Position size is *derived* from your risk %, not guessed:

```
Dollar Risk         = Account Balance × Risk %
Stop Distance        = |Entry Price − Stop Price|
Position Size (units)= Dollar Risk ÷ Stop Distance
```

Example: $2,000 account, 1% risk = $20 risk per trade. Entry $50, stop $48 (stop distance $2).
Position size = $20 ÷ $2 = **10 shares/units**, not "however much I can afford."

This is exactly what `tools/position_sizing.py` calculates for you — use it before every single trade, no exceptions.

## Why 100%-of-account sizing is not "aggressive," it's ruinous

If you risk 100% of your account and lose, you're at zero — done, no more trades, no recovery. If you risk 1% and lose, you have 99% left and can take 99 more losing trades in a row before running out. Small, consistent risk is what lets a real edge (which wins less than half the time in many strategies) actually play out over a large sample size.

## Drawdown math you should memorize

| Loss | Return needed to break even |
|---|---|
| -10% | +11.1% |
| -20% | +25% |
| -50% | +100% |
| -80% | +400% |
| -100% | infinite (impossible) |

Losses hurt more than equivalent gains help. This is why capping loss size is more important than maximizing win size.

## Daily / weekly circuit breakers

Set hard limits and follow them mechanically (write them on a sticky note if you have to):

- **Max loss per trade:** 1–2% of account (via position sizing formula above)
- **Max loss per day:** 3–5% of account → hit it, stop trading for the day, no exceptions
- **Max loss per week:** 6–10% of account → stop, review what went wrong before resuming
- **Max drawdown from peak:** 15–20% → cut position size in half until you're profitable again, or pause entirely and revisit your strategy

## Correlation and concentration risk

Don't put "1% risk" on 5 different trades that are all really the same bet (e.g., 5 different tech stocks that all move together, or being long the same currency pair through two different instruments). Group correlated positions and cap total risk on any single theme (e.g., max 3–4% total account risk across all currently-open correlated positions).

## Psychological side of risk (just as real as the math)

- **Revenge trading** — increasing size or breaking rules after a loss to "get it back." Almost always makes things worse. Your daily loss limit exists specifically to stop this.
- **FOMO entries** — chasing a move that already happened without your entry signal actually triggering. If your rule didn't fire, there's no trade.
- **Moving stops further away** — this converts a planned small loss into an unplanned large one. Never do this. If anything, only ever move a stop in your favor (to lock in profit).

## Summary checklist to use before every trade

- [ ] Risk % this trade ≤ 1–2% of current account balance (calculated, not guessed)
- [ ] Stop-loss level decided before entry, and will not be moved against you
- [ ] This trade doesn't push today's total risk past your daily loss limit
- [ ] This isn't a 3rd+ correlated position stacking risk on the same underlying bet
- [ ] You're not trading this because of a loss earlier today (revenge) or FOMO
