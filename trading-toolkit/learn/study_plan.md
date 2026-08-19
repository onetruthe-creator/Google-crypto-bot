# 8-Week Beginner Study Plan

A realistic, organized path from zero to a validated, demo-tested strategy. Do not skip to live trading before Week 8 — the goal of this plan is survival first, growth second.

Check off each item as you complete it. Don't move to the next week until the current week's checklist is done.

## Week 1 — Chart reading fundamentals
- [ ] Read `01_chart_reading.md` fully
- [ ] Practice exercise: read 20 charts cold (trend, support/resistance, where you'd place a stop) before scrolling to see what happened
- [ ] Learn your charting platform's basic tools (drawing trendlines, horizontal lines, adding a moving average)

## Week 2 — Indicators and market structure
- [ ] Add 50 & 200 period moving averages to 10 charts and identify trend using them
- [ ] Practice spotting RSI overbought/oversold + divergence on 10 charts
- [ ] Practice marking support/resistance and trend on the Daily timeframe for 10 different instruments

## Week 3 — Pick ONE strategy archetype
- [ ] Read `02_strategy_basics.md`
- [ ] Choose one archetype (trend-following, breakout, or mean-reversion)
- [ ] Write your full one-page rule set: entry, stop, target, position sizing (use the template below)

## Week 4 — Manual backtesting
- [ ] Scroll through 6–12 months of historical charts (without looking ahead) and manually mark every time your entry rule would have triggered
- [ ] Record each instance in the trade journal template (`tools/trade_journal_template.csv`) as if it were a real trade
- [ ] Calculate your win rate and average R-multiple from at least 30 instances

## Week 5 — Automated/scripted backtest (optional but recommended)
- [ ] Get historical OHLCV data for your instrument (CSV)
- [ ] Run/adapt `tools/backtest.py` for your rule set
- [ ] Compare script results to your manual backtest from Week 4 — they should roughly agree

## Week 6-7 — Demo/paper trading
- [ ] Open a demo account with your broker/platform
- [ ] Trade your exact rule set in real time for 4+ weeks, logging every trade in the journal
- [ ] Use `tools/position_sizing.py` for every single position size, at 1% risk
- [ ] Enforce your daily/weekly loss limits even on demo — build the habit now

## Week 8 — Review and go/no-go decision
- [ ] Review your demo journal: win rate, average R, max drawdown, adherence to rules (did you follow your own plan every time?)
- [ ] If profitable and rules were followed consistently: consider going live with a small account and 0.5–1% risk per trade
- [ ] If not profitable, or rules weren't followed: identify why (strategy issue vs. discipline issue) and repeat Weeks 3–7 with adjustments

## Rule-set template (fill this in during Week 3)

```
Strategy name: ______________________
Instrument(s) / market: ______________________
Timeframe: ______________________

Entry rule (must be objective, no ambiguity):
______________________________________________

Stop-loss rule:
______________________________________________

Target / exit rule:
______________________________________________

Position sizing rule: Risk ___% of account per trade (use tools/position_sizing.py)

Max trades per day: ______
Max daily loss: ___% of account
Max weekly loss: ___% of account
```

## Ongoing, every week for life
- [ ] Log every single trade in the journal, win or lose
- [ ] Weekly review: win rate, average R, biggest mistake, biggest well-executed trade
- [ ] Never change core strategy rules based on 1-3 trades — only after a large enough sample (30+ trades) shows a real pattern
