#!/usr/bin/env python3
"""
Morning Futures Trading Report Generator
Pulls pre-market data, earnings, economic calendar, and generates AI analysis.
Includes trade setup section for ES, YM, and custom watchlist tickers.
"""

import os
import json
import re
import smtplib
import requests
import yfinance as yf
from datetime import datetime, timedelta
import pytz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

# ── CONFIG ─────────────────────────────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]
TO_EMAIL       = os.environ["TO_EMAIL"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
DASHBOARD_URL  = os.environ.get("DASHBOARD_URL", "")

# ── WATCHLIST ──────────────────────────────────────────────────────────────────
# Add any tickers here to include them in the setup section
# Format: {"ticker": "SYMBOL", "name": "Display Name", "type": "stock/futures/etf"}
WATCHLIST = [
    # Default: ES and YM always included via futures data
    # Add your tickers below — examples:
    # {"ticker": "NVDA", "name": "NVIDIA",        "type": "stock"},
    # {"ticker": "AAPL", "name": "Apple",          "type": "stock"},
    # {"ticker": "SPY",  "name": "SPY ETF",        "type": "etf"},
]

ET = pytz.timezone("America/New_York")
TODAY = datetime.now(ET).strftime("%A, %B %d, %Y")
TODAY_SHORT = datetime.now(ET).strftime("%Y-%m-%d")

# ── FUTURES TICKERS ────────────────────────────────────────────────────────────
FUTURES = {
    "ES": {"ticker": "ES=F",   "name": "S&P 500 (ES)",  "index": "^GSPC"},
    "YM": {"ticker": "YM=F",   "name": "Dow (YM)",      "index": "^DJI"},
    "NQ": {"ticker": "NQ=F",   "name": "Nasdaq (NQ)",   "index": "^IXIC"},
    "RTY": {"ticker": "RTY=F", "name": "Russell (RTY)", "index": "^RUT"},
    "VIX": {"ticker": "^VIX",  "name": "VIX",           "index": None},
    "CL":  {"ticker": "CL=F",  "name": "Crude Oil",     "index": None},
    "GC":  {"ticker": "GC=F",  "name": "Gold",          "index": None},
    "ZB":  {"ticker": "ZB=F",  "name": "30Y T-Bond",    "index": None},
}

# ── DATA PULLS ─────────────────────────────────────────────────────────────────

def get_futures_data():
    """Pull pre-market futures prices and calculate changes."""
    data = {}
    for key, info in FUTURES.items():
        try:
            t = yf.Ticker(info["ticker"])
            hist = t.history(period="2d", interval="1m")
            if hist.empty:
                hist = t.history(period="5d")
            if not hist.empty:
                current = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[0])
                daily = t.history(period="5d", interval="1d")
                if len(daily) >= 2:
                    prev_close = float(daily["Close"].iloc[-2])
                change = current - prev_close
                pct = (change / prev_close) * 100
                data[key] = {
                    "name": info["name"],
                    "ticker": info["ticker"],
                    "price": current,
                    "change": change,
                    "pct": pct,
                    "direction": "▲" if change >= 0 else "▼",
                    "color": "#00d4a0" if change >= 0 else "#ff4d6d",
                    "prev_close": prev_close,
                }
        except Exception as e:
            data[key] = {"name": info["name"], "ticker": info["ticker"],
                          "price": 0, "change": 0, "pct": 0,
                          "direction": "—", "color": "#888", "prev_close": 0, "error": str(e)}
    return data


def get_key_levels(ticker_symbol, current_price, prev_close):
    """
    Pull OHLC data and calculate key levels:
    - Previous day high/low
    - Overnight (Globex) high/low
    - Prior week high/low
    - Round number proximity
    - Approx VWAP (prior session)
    """
    levels = {}
    try:
        t = yf.Ticker(ticker_symbol)

        # Previous day OHLC
        daily = t.history(period="10d", interval="1d")
        if len(daily) >= 2:
            levels["pdh"] = float(daily["High"].iloc[-2])
            levels["pdl"] = float(daily["Low"].iloc[-2])
            levels["pd_close"] = float(daily["Close"].iloc[-2])

        # Prior week high/low (last 5 trading days)
        if len(daily) >= 6:
            week_slice = daily.iloc[-6:-1]
            levels["pwh"] = float(week_slice["High"].max())
            levels["pwl"] = float(week_slice["Low"].min())

        # Overnight/Globex range (last 24h intraday)
        intra = t.history(period="2d", interval="5m")
        if not intra.empty:
            levels["overnight_high"] = float(intra["High"].max())
            levels["overnight_low"] = float(intra["Low"].min())

        # Nearest round numbers above and below
        if current_price > 0:
            magnitude = 100 if current_price > 1000 else 50 if current_price > 500 else 10
            levels["round_above"] = (int(current_price / magnitude) + 1) * magnitude
            levels["round_below"] = int(current_price / magnitude) * magnitude

        levels["current"] = current_price
        levels["prev_close"] = prev_close

    except Exception as e:
        levels["error"] = str(e)

    return levels


def get_watchlist_data():
    """Pull pre-market data for watchlist tickers."""
    data = []
    for item in WATCHLIST:
        try:
            t = yf.Ticker(item["ticker"])
            daily = t.history(period="5d", interval="1d")
            if len(daily) >= 2:
                current = float(daily["Close"].iloc[-1])
                prev = float(daily["Close"].iloc[-2])
                pct = ((current - prev) / prev) * 100
                data.append({
                    "ticker": item["ticker"],
                    "name": item["name"],
                    "type": item["type"],
                    "price": current,
                    "pct": pct,
                    "prev_close": prev,
                    "color": "#00d4a0" if pct >= 0 else "#ff4d6d",
                })
        except Exception:
            pass
    return data


def get_earnings_today():
    """Pull today's earnings from Nasdaq calendar."""
    earnings = []
    try:
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={TODAY_SHORT}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            rows = r.json().get("data", {}).get("rows", []) or []
            for row in rows[:20]:
                earnings.append({
                    "symbol": row.get("symbol", ""),
                    "name": row.get("name", ""),
                    "time": row.get("time", ""),
                    "eps_est": row.get("epsForecast", "—"),
                    "eps_actual": row.get("eps", "—"),
                    "rev_est": row.get("revenueForecast", "—"),
                    "surprise": row.get("surprise", "—"),
                })
    except Exception as e:
        earnings.append({"symbol": "ERROR", "name": str(e), "time": "",
                          "eps_est": "", "eps_actual": "", "rev_est": "", "surprise": ""})
    return earnings


def get_economic_calendar():
    """Pull today's economic events."""
    events = []
    try:
        url = "https://www.alphavantage.co/query?function=ECONOMIC_CALENDAR&apikey=demo"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for event in data.get("data", []):
                if event.get("date", "").startswith(TODAY_SHORT):
                    impact = event.get("impact", "Low")
                    events.append({
                        "time": event.get("time", ""),
                        "event": event.get("event", ""),
                        "actual": event.get("actual", "—"),
                        "forecast": event.get("forecast", "—"),
                        "previous": event.get("previous", "—"),
                        "impact": impact,
                        "impact_color": {"High": "#ff4d6d", "Medium": "#ffd166", "Low": "#00d4a0"}.get(impact, "#888"),
                    })
    except Exception:
        pass

    if not events:
        events = [{"time": "8:30 AM ET", "event": "Check BLS.gov for today's scheduled releases",
                   "actual": "—", "forecast": "—", "previous": "—",
                   "impact": "—", "impact_color": "#888"}]
    return events


def get_sector_snapshot():
    """Pull pre-market performance for major sector ETFs."""
    sectors = {
        "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
        "XLI": "Industrials", "XLV": "Healthcare", "XLY": "Cons. Disc.",
        "XLP": "Cons. Staples", "XLU": "Utilities", "XLB": "Materials",
        "XLRE": "Real Estate",
    }
    data = []
    for ticker, name in sectors.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            if len(hist) >= 2:
                cur = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                pct = ((cur - prev) / prev) * 100
                data.append({"ticker": ticker, "name": name, "pct": pct,
                              "color": "#00d4a0" if pct >= 0 else "#ff4d6d"})
        except Exception:
            pass
    return sorted(data, key=lambda x: x["pct"], reverse=True)


# ── AI ANALYSIS ────────────────────────────────────────────────────────────────

def generate_ai_analysis(futures_data, earnings, econ_events, sectors):
    """Call Claude to write the contextual morning briefing."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    futures_str = "\n".join([
        f"  {v['name']}: {v['direction']} {v['pct']:+.2f}% (${v['price']:,.2f})"
        for v in futures_data.values() if v.get('price', 0) > 0
    ])
    earnings_str = "\n".join([
        f"  {e['symbol']} ({e['name']}) - {e['time']} | EPS Est: {e['eps_est']} Actual: {e['eps_actual']} | Surprise: {e['surprise']}"
        for e in earnings[:10]
    ]) or "  No major earnings today"

    econ_str = "\n".join([
        f"  [{e['impact']}] {e['time']} {e['event']} | Forecast: {e['forecast']} Prev: {e['previous']}"
        for e in econ_events
    ]) or "  No major economic events today"

    sector_str = "\n".join([f"  {s['name']}: {s['pct']:+.2f}%" for s in sectors[:5]])

    prompt = f"""You are a professional futures trading desk analyst writing a pre-market morning briefing for a trader who primarily trades ES (S&P 500 futures) and YM (Dow futures). Today is {TODAY}.

FUTURES PRE-MARKET:
{futures_str}

TODAY'S EARNINGS:
{earnings_str}

ECONOMIC CALENDAR TODAY:
{econ_str}

LEADING SECTORS:
{sector_str}

Write a concise, high-signal morning briefing with these sections:

1. **OVERNIGHT SUMMARY** (2-3 sentences): What happened overnight. Key moves, any geopolitical or macro catalysts.

2. **ES vs YM DIVERGENCE ANALYSIS**: Are ES and YM moving together or diverging? Explain WHY based on index composition (tech is ~30% of SPX, industrials/financials dominate the Dow). If there's notable divergence, name the likely cause.

3. **EARNINGS IMPACT**: Which earnings reports matter most for ES and YM? Rate overall impact: 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW.

4. **ECONOMIC DATA IMPACT**: What events today could move futures? Rate each: 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW. Note exact release times.

5. **KNOW BEFORE YOU GO** (3-4 sentences): The single most important thing to watch at the open. What's the dominant theme? Any landmines? What would change your bias?

Be direct, specific, write like a seasoned desk analyst. No filler."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def generate_trade_setups(futures_data, key_levels_es, key_levels_ym, watchlist_data, earnings, econ_events):
    """Call Claude to generate specific trade setups for ES, YM, and watchlist."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    def fmt_levels(name, levels, price, pct):
        if not levels or levels.get("error"):
            return f"{name}: price={price:.2f} chg={pct:+.2f}% (level data unavailable)"
        return f"""{name}:
  Current: {price:,.2f} ({pct:+.2f}%)
  Prev Close: {levels.get('prev_close', 0):,.2f}
  PDH: {levels.get('pdh', 0):,.2f} | PDL: {levels.get('pdl', 0):,.2f}
  Overnight High: {levels.get('overnight_high', 0):,.2f} | Overnight Low: {levels.get('overnight_low', 0):,.2f}
  Prior Week High: {levels.get('pwh', 0):,.2f} | Prior Week Low: {levels.get('pwl', 0):,.2f}
  Nearest Round Above: {levels.get('round_above', 0):,.0f} | Below: {levels.get('round_below', 0):,.0f}"""

    es = futures_data.get("ES", {})
    ym = futures_data.get("YM", {})
    vix = futures_data.get("VIX", {})

    es_str = fmt_levels("ES (S&P 500 Futures)", key_levels_es, es.get("price", 0), es.get("pct", 0))
    ym_str = fmt_levels("YM (Dow Futures)", key_levels_ym, ym.get("price", 0), ym.get("pct", 0))

    watchlist_str = ""
    if watchlist_data:
        watchlist_str = "\nWATCHLIST:\n" + "\n".join([
            f"  {w['ticker']} ({w['name']}): ${w['price']:,.2f} ({w['pct']:+.2f}%)"
            for w in watchlist_data
        ])

    earnings_context = "\n".join([
        f"  {e['symbol']}: EPS {e['eps_actual']} vs {e['eps_est']} est | Surprise: {e['surprise']}"
        for e in earnings[:5] if e.get('symbol') != 'ERROR'
    ]) or "  None"

    econ_context = "\n".join([
        f"  [{e['impact']}] {e['time']} {e['event']}"
        for e in econ_events[:5]
    ]) or "  None"

    prompt = f"""You are a professional futures trader and analyst generating pre-market trade setups. Today is {TODAY}.

This trader's style:
- Trades: Breakout/breakdown of key levels, mean reversion/fade the open, structural breaks at VWAP
- Key levels they use: PDH/PDL, overnight high/low, prior week high/low, round numbers, VWAP
- Wants: 2 setups per instrument (1 long bias, 1 short bias)
- Format must be precise and actionable

MARKET DATA:
{es_str}

{ym_str}
{watchlist_str}

VIX: {vix.get('price', 0):.2f} ({vix.get('pct', 0):+.2f}%)

EARNINGS THIS MORNING:
{earnings_context}

ECONOMIC EVENTS TODAY:
{econ_context}

Generate trade setups in this EXACT JSON format. Return ONLY valid JSON, no other text:

{{
  "setups": [
    {{
      "instrument": "ES",
      "bias": "LONG",
      "setup_type": "Breakout / Mean Reversion / VWAP Reclaim / Fade",
      "trigger": "Specific price level and condition to enter",
      "target1": 0000.00,
      "target2": 0000.00,
      "stop": 0000.00,
      "pts_risk": 00.00,
      "pts_t1": 00.00,
      "pts_t2": 00.00,
      "rr1": "1:0.0",
      "rr2": "1:0.0",
      "condition": "What must happen for this setup to be valid (e.g. NQ must confirm, hold above PDH on 5min close)",
      "invalidated_by": "What price action kills this setup",
      "confidence": "HIGH / MEDIUM / LOW",
      "confidence_color": "#00d4a0 or #ffd166 or #ff4d6d",
      "rationale": "2-3 sentence explanation of why this setup makes sense today given the data"
    }},
    {{
      "instrument": "ES",
      "bias": "SHORT",
      "setup_type": "...",
      "trigger": "...",
      "target1": 0000.00,
      "target2": 0000.00,
      "stop": 0000.00,
      "pts_risk": 00.00,
      "pts_t1": 00.00,
      "pts_t2": 00.00,
      "rr1": "1:0.0",
      "rr2": "1:0.0",
      "condition": "...",
      "invalidated_by": "...",
      "confidence": "HIGH / MEDIUM / LOW",
      "confidence_color": "#00d4a0 or #ffd166 or #ff4d6d",
      "rationale": "..."
    }},
    {{
      "instrument": "YM",
      "bias": "LONG",
      ...same fields...
    }},
    {{
      "instrument": "YM",
      "bias": "SHORT",
      ...same fields...
    }}
  ]
}}

Rules:
- Every price must be a real number based on the actual data provided, not a placeholder
- Risk/reward must be mathematically correct
- Setup types must match this trader's actual style: breakout, fade, VWAP structural break, or mean reversion
- Confidence should reflect VIX level, earnings uncertainty, and economic data risk
- If a high-impact economic event is scheduled (e.g. CPI at 8:30), note that in the condition field
- Be specific — "reclaim of 5412 on a 5-minute close" not "price goes up"
"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        return json.loads(raw)
    except Exception:
        return {"setups": [], "error": raw[:500]}


# ── HTML GENERATION ────────────────────────────────────────────────────────────

def build_setup_cards_html(setups_data):
    """Build HTML for the trade setup cards."""
    if not setups_data or not setups_data.get("setups"):
        return '<div class="setup-error">Setup generation unavailable — check API logs.</div>'

    cards_html = ""
    for s in setups_data["setups"]:
        bias = s.get("bias", "")
        bias_color = "#00d4a0" if bias == "LONG" else "#ff4d6d"
        bias_bg = "rgba(0,212,160,0.08)" if bias == "LONG" else "rgba(255,77,109,0.08)"
        conf_color = s.get("confidence_color", "#ffd166")
        instrument = s.get("instrument", "")

        cards_html += f"""
        <div class="setup-card" style="border-color:{bias_color}20;background:{bias_bg}">
          <div class="setup-header">
            <div class="setup-instrument">{instrument}</div>
            <div class="setup-bias" style="color:{bias_color};border-color:{bias_color}40;background:{bias_color}15">{bias}</div>
            <div class="setup-type-badge">{s.get('setup_type','')}</div>
            <div class="setup-conf" style="color:{conf_color}">● {s.get('confidence','')}</div>
          </div>

          <div class="setup-trigger">
            <span class="setup-label">TRIGGER</span>
            <span class="setup-value">{s.get('trigger','—')}</span>
          </div>

          <div class="setup-levels">
            <div class="level-box level-target">
              <div class="level-label">T1</div>
              <div class="level-price">{s.get('target1',0):,.2f}</div>
              <div class="level-pts" style="color:#00d4a0">+{s.get('pts_t1',0):.1f} pts</div>
              <div class="level-rr">{s.get('rr1','—')}</div>
            </div>
            <div class="level-box level-target">
              <div class="level-label">T2</div>
              <div class="level-price">{s.get('target2',0):,.2f}</div>
              <div class="level-pts" style="color:#00d4a0">+{s.get('pts_t2',0):.1f} pts</div>
              <div class="level-rr">{s.get('rr2','—')}</div>
            </div>
            <div class="level-box level-stop">
              <div class="level-label">STOP</div>
              <div class="level-price">{s.get('stop',0):,.2f}</div>
              <div class="level-pts" style="color:#ff4d6d">-{s.get('pts_risk',0):.1f} pts</div>
              <div class="level-rr">risk</div>
            </div>
          </div>

          <div class="setup-condition">
            <span class="setup-label">CONDITION</span> {s.get('condition','—')}
          </div>
          <div class="setup-invalidated">
            <span class="setup-label" style="color:#ff4d6d">INVALIDATED</span> {s.get('invalidated_by','—')}
          </div>
          <div class="setup-rationale">{s.get('rationale','')}</div>
        </div>"""

    return cards_html


def build_html(futures_data, earnings, econ_events, sectors, analysis, setups_data):
    """Build the full HTML dashboard."""

    priority_keys = ["ES", "YM", "NQ", "VIX", "CL", "GC", "ZB"]
    futures_cards = ""
    for key in priority_keys:
        if key not in futures_data:
            continue
        f = futures_data[key]
        price_str = f"${f['price']:,.2f}" if f.get('price', 0) > 0 else "—"
        pct_str = f"{f['pct']:+.2f}%" if f.get('price', 0) > 0 else "—"
        futures_cards += f"""
        <div class="futures-card">
            <div class="futures-name">{f['name']}</div>
            <div class="futures-price">{price_str}</div>
            <div class="futures-change" style="color:{f['color']}">{f['direction']} {pct_str}</div>
        </div>"""

    earnings_rows = ""
    for e in earnings[:15]:
        surprise_color = "#00d4a0" if str(e.get('surprise','—')).startswith('+') else "#ff4d6d" if str(e.get('surprise','—')).startswith('-') else "#ccc"
        earnings_rows += f"""
        <tr>
            <td class="symbol">{e['symbol']}</td>
            <td>{e['name']}</td>
            <td>{e['time']}</td>
            <td>{e['eps_est']}</td>
            <td>{e['eps_actual']}</td>
            <td style="color:{surprise_color}">{e['surprise']}</td>
        </tr>"""
    if not earnings_rows:
        earnings_rows = '<tr><td colspan="6" class="empty">No major earnings scheduled today</td></tr>'

    econ_rows = ""
    for e in econ_events:
        econ_rows += f"""
        <tr>
            <td>{e['time']}</td>
            <td class="event-name">{e['event']}</td>
            <td style="color:{e['impact_color']}; font-weight:700">{e['impact']}</td>
            <td>{e['forecast']}</td>
            <td>{e['actual']}</td>
            <td>{e['previous']}</td>
        </tr>"""
    if not econ_rows:
        econ_rows = '<tr><td colspan="6" class="empty">No major economic events today</td></tr>'

    sector_bars = ""
    max_abs = max((abs(s['pct']) for s in sectors), default=1)
    for s in sectors:
        bar_width = max(4, int(abs(s['pct']) / max_abs * 100))
        sector_bars += f"""
        <div class="sector-row">
            <div class="sector-label">{s['name']}</div>
            <div class="sector-bar-wrap">
                <div class="sector-bar" style="width:{bar_width}%; background:{s['color']}"></div>
            </div>
            <div class="sector-pct" style="color:{s['color']}">{s['pct']:+.2f}%</div>
        </div>"""

    analysis_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', analysis)
    analysis_html = analysis_html.replace('\n\n', '</p><p>').replace('\n', '<br>')
    analysis_html = f"<p>{analysis_html}</p>"

    setup_cards_html = build_setup_cards_html(setups_data)
    generated_at = datetime.now(ET).strftime("%I:%M %p ET")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Morning Futures Report — {TODAY}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0c10;
    --surface: #111318;
    --border: #1e2330;
    --border-bright: #2a3045;
    --text: #c8d0e0;
    --text-dim: #5a6480;
    --text-bright: #eef2ff;
    --green: #00d4a0;
    --red: #ff4d6d;
    --yellow: #ffd166;
    --blue: #4d9fff;
    --accent: #4d9fff;
    --mono: 'IBM Plex Mono', monospace;
    --sans: 'IBM Plex Sans', sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
  }}
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    background-image: repeating-linear-gradient(0deg, transparent, transparent 40px, rgba(255,255,255,0.012) 40px, rgba(255,255,255,0.012) 41px), repeating-linear-gradient(90deg, transparent, transparent 40px, rgba(255,255,255,0.012) 40px, rgba(255,255,255,0.012) 41px);
    pointer-events: none;
    z-index: 0;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px 60px; position: relative; z-index: 1; }}

  header {{
    border-bottom: 1px solid var(--border-bright);
    padding: 28px 0 20px;
    margin-bottom: 32px;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
  }}
  .header-left .label {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--accent);
    letter-spacing: 0.15em;
    text-transform: uppercase;
    margin-bottom: 6px;
  }}
  .header-left h1 {{
    font-family: var(--mono);
    font-size: 26px;
    font-weight: 700;
    color: var(--text-bright);
    letter-spacing: -0.02em;
  }}
  .header-right {{
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    text-align: right;
  }}
  .live-dot {{
    display: inline-block;
    width: 7px; height: 7px;
    background: var(--green);
    border-radius: 50%;
    margin-right: 6px;
    animation: pulse 2s ease-in-out infinite;
  }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}

  .section-title {{
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}

  /* FUTURES STRIP */
  .futures-strip {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}
  .futures-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    transition: border-color 0.2s;
  }}
  .futures-card:hover {{ border-color: var(--border-bright); }}
  .futures-name {{ font-family: var(--mono); font-size: 11px; color: var(--text-dim); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.08em; }}
  .futures-price {{ font-family: var(--mono); font-size: 18px; font-weight: 700; color: var(--text-bright); margin-bottom: 4px; }}
  .futures-change {{ font-family: var(--mono); font-size: 13px; font-weight: 600; }}

  /* MAIN GRID */
  .main-grid {{
    display: grid;
    grid-template-columns: 1fr 300px;
    gap: 24px;
    margin-bottom: 24px;
  }}
  @media (max-width: 900px) {{ .main-grid {{ grid-template-columns: 1fr; }} }}

  .analysis-panel {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 24px;
  }}
  .analysis-panel p {{ margin-bottom: 12px; color: var(--text); line-height: 1.7; }}
  .analysis-panel strong {{ color: var(--text-bright); }}
  .analysis-panel p:last-child {{ margin-bottom: 0; }}

  .sector-panel {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
  }}
  .sector-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
  .sector-label {{ font-size: 12px; color: var(--text-dim); width: 90px; flex-shrink: 0; font-family: var(--mono); }}
  .sector-bar-wrap {{ flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }}
  .sector-bar {{ height: 100%; border-radius: 3px; }}
  .sector-pct {{ font-family: var(--mono); font-size: 12px; font-weight: 600; width: 56px; text-align: right; }}

  /* TRADE SETUPS */
  .setups-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .setup-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    transition: border-color 0.2s;
  }}
  .setup-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
    flex-wrap: wrap;
  }}
  .setup-instrument {{
    font-family: var(--mono);
    font-size: 18px;
    font-weight: 700;
    color: var(--text-bright);
  }}
  .setup-bias {{
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid;
    letter-spacing: 0.08em;
  }}
  .setup-type-badge {{
    font-family: var(--mono);
    font-size: 10px;
    color: var(--text-dim);
    background: var(--border);
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.05em;
  }}
  .setup-conf {{
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    margin-left: auto;
  }}
  .setup-trigger {{
    background: rgba(77,159,255,0.06);
    border: 1px solid rgba(77,159,255,0.2);
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 14px;
    font-size: 13px;
  }}
  .setup-label {{
    font-family: var(--mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: var(--text-dim);
    margin-right: 8px;
    text-transform: uppercase;
  }}
  .setup-value {{ color: var(--text-bright); }}
  .setup-levels {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
    margin-bottom: 12px;
  }}
  .level-box {{
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    text-align: center;
  }}
  .level-label {{ font-family: var(--mono); font-size: 9px; color: var(--text-dim); letter-spacing: 0.1em; margin-bottom: 4px; }}
  .level-price {{ font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--text-bright); margin-bottom: 2px; }}
  .level-pts {{ font-family: var(--mono); font-size: 11px; font-weight: 600; margin-bottom: 2px; }}
  .level-rr {{ font-family: var(--mono); font-size: 10px; color: var(--text-dim); }}
  .setup-condition {{
    font-size: 12px;
    color: var(--text);
    margin-bottom: 6px;
    line-height: 1.5;
  }}
  .setup-invalidated {{
    font-size: 12px;
    color: var(--text-dim);
    margin-bottom: 10px;
    line-height: 1.5;
  }}
  .setup-rationale {{
    font-size: 12px;
    color: var(--text-dim);
    font-style: italic;
    line-height: 1.6;
    border-top: 1px solid var(--border);
    padding-top: 10px;
    margin-top: 4px;
  }}
  .setup-error {{
    color: var(--text-dim);
    font-style: italic;
    padding: 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 24px;
  }}

  /* TABLES */
  .table-panel {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
    overflow-x: auto;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ font-family: var(--mono); font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em; padding: 0 12px 10px 0; text-align: left; border-bottom: 1px solid var(--border); }}
  td {{ padding: 10px 12px 10px 0; font-size: 13px; color: var(--text); border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  .symbol {{ font-family: var(--mono); font-weight: 700; color: var(--text-bright); font-size: 13px; }}
  .event-name {{ color: var(--text-bright); }}
  .empty {{ color: var(--text-dim); font-style: italic; padding: 20px 0; }}

  footer {{
    border-top: 1px solid var(--border);
    padding-top: 20px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-dim);
    text-align: center;
  }}
</style>
</head>
<body>
<div class="container">

  <header>
    <div class="header-left">
      <div class="label">Pre-Market Intelligence</div>
      <h1>Morning Futures Report</h1>
    </div>
    <div class="header-right">
      <div>{TODAY}</div>
      <div style="margin-top:4px"><span class="live-dot"></span>Generated {generated_at}</div>
    </div>
  </header>

  <!-- FUTURES STRIP -->
  <div class="section-title">Futures Snapshot</div>
  <div class="futures-strip">{futures_cards}</div>

  <!-- MAIN GRID: Analysis + Sectors -->
  <div class="main-grid">
    <div>
      <div class="section-title">AI Morning Briefing</div>
      <div class="analysis-panel">{analysis_html}</div>
    </div>
    <div>
      <div class="section-title">Sector Performance</div>
      <div class="sector-panel">{sector_bars}</div>
    </div>
  </div>

  <!-- TRADE SETUPS -->
  <div class="section-title">Trade Setups — ES &amp; YM</div>
  <div class="setups-grid">{setup_cards_html}</div>

  <!-- EARNINGS TABLE -->
  <div class="section-title">Today's Earnings</div>
  <div class="table-panel">
    <table>
      <thead><tr><th>Symbol</th><th>Company</th><th>Time</th><th>EPS Est</th><th>EPS Actual</th><th>Surprise</th></tr></thead>
      <tbody>{earnings_rows}</tbody>
    </table>
  </div>

  <!-- ECONOMIC CALENDAR -->
  <div class="section-title">Economic Calendar</div>
  <div class="table-panel">
    <table>
      <thead><tr><th>Time</th><th>Event</th><th>Impact</th><th>Forecast</th><th>Actual</th><th>Previous</th></tr></thead>
      <tbody>{econ_rows}</tbody>
    </table>
  </div>

  <footer>
    Data: Yahoo Finance · Nasdaq Earnings Calendar · Alpha Vantage · Analysis: Claude AI &nbsp;|&nbsp;
    Not financial advice. For informational purposes only.
  </footer>

</div>
</body>
</html>"""


# ── EMAIL ──────────────────────────────────────────────────────────────────────

def send_email(html_content, analysis_text, setups_data, dashboard_url):
    """Send the morning report email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Morning Futures Report — {TODAY}"
    msg["From"] = GMAIL_USER
    msg["To"] = TO_EMAIL

    # Build setup summary for email
    setup_lines = ""
    if setups_data and setups_data.get("setups"):
        for s in setups_data["setups"]:
            bias_emoji = "🟢" if s.get("bias") == "LONG" else "🔴"
            setup_lines += f"<div style='margin-bottom:8px'>{bias_emoji} <strong style='color:#eef2ff'>{s.get('instrument')} {s.get('bias')}</strong> — {s.get('trigger','')}<br><span style='color:#5a6480;font-size:12px'>{s.get('setup_type','')} | T1: {s.get('target1',0):,.2f} | Stop: {s.get('stop',0):,.2f} | {s.get('rr1','')}</span></div>"

    dashboard_link = f'<div style="text-align:center;margin:24px 0"><a href="{dashboard_url}" style="color:#4d9fff;font-family:monospace">View Full Dashboard →</a></div>' if dashboard_url else ""

    text_body = f"Morning Futures Report — {TODAY}\n\nView dashboard: {dashboard_url}"
    html_email = f"""
    <div style="background:#0a0c10;padding:32px;font-family:'Courier New',monospace;max-width:680px;margin:0 auto">
      <div style="color:#4d9fff;font-size:11px;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:8px">Pre-Market Intelligence</div>
      <h1 style="color:#eef2ff;font-size:22px;margin:0 0 4px;font-family:monospace">Morning Futures Report</h1>
      <div style="color:#5a6480;font-size:12px;margin-bottom:28px">{TODAY}</div>
      <div style="background:#111318;border:1px solid #1e2330;border-radius:8px;padding:24px;margin-bottom:20px;color:#c8d0e0;font-family:Georgia,serif;font-size:14px;line-height:1.8">
        {analysis_text.replace(chr(10), '<br>')}
      </div>
      <div style="background:#111318;border:1px solid #1e2330;border-radius:8px;padding:20px;margin-bottom:20px">
        <div style="color:#4d9fff;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:14px">Trade Setups</div>
        {setup_lines or '<div style="color:#5a6480">No setups generated</div>'}
      </div>
      {dashboard_link}
      <div style="color:#3a4060;font-size:11px;text-align:center;margin-top:24px">Not financial advice. For informational purposes only.</div>
    </div>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_email, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print("✅ Email sent successfully")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    print(f"🚀 Generating Morning Report for {TODAY}...")

    print("  → Fetching futures data...")
    futures_data = get_futures_data()

    print("  → Fetching key levels for ES and YM...")
    es = futures_data.get("ES", {})
    ym = futures_data.get("YM", {})
    key_levels_es = get_key_levels("ES=F", es.get("price", 0), es.get("prev_close", 0))
    key_levels_ym = get_key_levels("YM=F", ym.get("price", 0), ym.get("prev_close", 0))

    print("  → Fetching watchlist data...")
    watchlist_data = get_watchlist_data()

    print("  → Fetching earnings calendar...")
    earnings = get_earnings_today()

    print("  → Fetching economic calendar...")
    econ_events = get_economic_calendar()

    print("  → Fetching sector data...")
    sectors = get_sector_snapshot()

    print("  → Generating AI morning briefing...")
    analysis = generate_ai_analysis(futures_data, earnings, econ_events, sectors)

    print("  → Generating trade setups...")
    setups_data = generate_trade_setups(futures_data, key_levels_es, key_levels_ym, watchlist_data, earnings, econ_events)

    print("  → Building HTML dashboard...")
    html = build_html(futures_data, earnings, econ_events, sectors, analysis, setups_data)

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w") as f:
        f.write(html)
    print("  → Dashboard saved to docs/index.html")

    print("  → Sending email...")
    send_email(html, analysis, setups_data, DASHBOARD_URL)

    print("✅ Morning report complete!")


if __name__ == "__main__":
    main()
