#!/usr/bin/env python3
"""
Afternoon Futures Recap Generator
Runs at 4 PM ET — pulls closing data, fetches morning's setups from dashboard,
grades each setup, and emails a "how did the day play out" recap.
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

ET = pytz.timezone("America/New_York")
TODAY = datetime.now(ET).strftime("%A, %B %d, %Y")
TODAY_SHORT = datetime.now(ET).strftime("%Y-%m-%d")


# ── CLOSING DATA ───────────────────────────────────────────────────────────────

def get_closing_data():
    """Pull end-of-day prices and full day stats."""
    tickers = {
        "ES":  "ES=F",
        "YM":  "YM=F",
        "NQ":  "NQ=F",
        "RTY": "RTY=F",
        "VIX": "^VIX",
        "CL":  "CL=F",
        "GC":  "GC=F",
    }
    data = {}
    for name, sym in tickers.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1d", interval="1m")
            if hist.empty:
                hist = t.history(period="2d", interval="5m")
            if not hist.empty:
                open_p  = float(hist["Open"].iloc[0])
                close_p = float(hist["Close"].iloc[-1])
                high_p  = float(hist["High"].max())
                low_p   = float(hist["Low"].min())
                pct     = ((close_p - open_p) / open_p) * 100
                pts     = close_p - open_p
                data[name] = {
                    "open":  open_p,
                    "close": close_p,
                    "high":  high_p,
                    "low":   low_p,
                    "pct":   pct,
                    "pts":   pts,
                }
        except Exception as e:
            print(f"  Warning: Could not fetch {name}: {e}")
    return data


# ── FETCH MORNING DASHBOARD ────────────────────────────────────────────────────

def fetch_morning_context():
    """Pull this morning's dashboard to extract the setups and thesis."""
    if not DASHBOARD_URL:
        return None, None

    try:
        r = requests.get(DASHBOARD_URL, timeout=15)
        html = r.text

        # Extract morning context JSON (injected by generate_report.py)
        match = re.search(r'id="morning-context"[^>]*>(.*?)</script>', html, re.DOTALL)
        analysis = json.loads(match.group(1).strip()) if match else ""

        # Extract trade setups from the HTML
        setups = []
        setup_blocks = re.findall(r'class="setup-card[^"]*".*?class="setup-rationale">(.*?)</div>\s*</div>', html, re.DOTALL)

        # Extract key setup info from HTML
        instruments = re.findall(r'class="setup-instrument">(.*?)</div>', html)
        biases      = re.findall(r'class="setup-bias"[^>]*>(.*?)</div>', html)
        triggers    = re.findall(r'class="setup-value">(.*?)</span>', html)
        t1s         = re.findall(r'class="level-label">T1</div>\s*<div class="level-price">(.*?)</div>', html)
        t2s         = re.findall(r'class="level-label">T2</div>\s*<div class="level-price">(.*?)</div>', html)
        stops       = re.findall(r'class="level-label">STOP</div>\s*<div class="level-price">(.*?)</div>', html)
        rationales  = re.findall(r'class="setup-rationale">(.*?)</div>', html)

        for i in range(len(instruments)):
            setups.append({
                "instrument": instruments[i] if i < len(instruments) else "",
                "bias":       biases[i] if i < len(biases) else "",
                "trigger":    triggers[i] if i < len(triggers) else "",
                "t1":         t1s[i] if i < len(t1s) else "",
                "t2":         t2s[i] if i < len(t2s) else "",
                "stop":       stops[i] if i < len(stops) else "",
                "rationale":  rationales[i] if i < len(rationales) else "",
            })

        return analysis, setups

    except Exception as e:
        print(f"  Warning: Could not fetch morning dashboard: {e}")
        return None, None


# ── AI RECAP ANALYSIS ──────────────────────────────────────────────────────────

def generate_recap(closing_data, morning_analysis, setups):
    """Generate AI-powered end of day recap."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # Build closing snapshot string
    snap = ""
    for name, d in closing_data.items():
        color = "▲" if d["pct"] >= 0 else "▼"
        snap += f"  {name}: Open {d['open']:,.2f} → Close {d['close']:,.2f} | {color} {d['pct']:+.2f}% ({d['pts']:+.1f} pts) | Range: {d['low']:,.2f} - {d['high']:,.2f}\n"

    # Build setups string
    setups_str = ""
    for s in setups:
        setups_str += f"  {s['instrument']} {s['bias']} — Trigger: {s['trigger']} | T1: {s['t1']} | T2: {s['t2']} | Stop: {s['stop']}\n"

    prompt = f"""Today is {TODAY}. Markets are now closed. You are writing an afternoon recap for a futures trader.

CLOSING PRICES & DAY STATS:
{snap}

THIS MORNING'S THESIS:
{morning_analysis or 'Not available'}

THIS MORNING'S TRADE SETUPS:
{setups_str or 'Not available'}

Write a structured afternoon recap with these sections:

1. **Day Summary** (2-3 sentences): How did the day actually play out? Key narrative — trend day, choppy, news-driven?

2. **Setup Grades** — For each setup listed above, grade it:
   - Did the trigger price get hit? (Yes/No)
   - If yes: Did it hit T1? T2? Or stop out?
   - Grade: ✅ Winner | ❌ Stopped | ⏭ Never triggered | 🔄 Partial
   - One sentence on what actually happened

3. **Thesis Accuracy** — How accurate was the morning thesis? Score it 1-10 and explain in 2 sentences.

4. **Key Lesson** — One specific observation about today's price action to remember for tomorrow.

Be direct and specific. Reference actual price levels. No filler."""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


# ── BUILD HTML EMAIL ───────────────────────────────────────────────────────────

def build_recap_html(closing_data, recap_text):
    """Build the HTML recap email."""

    # Closing cards
    cards = ""
    priority = ["ES", "YM", "NQ", "VIX", "CL", "GC"]
    for name in priority:
        if name not in closing_data:
            continue
        d = closing_data[name]
        color = "#00d4a0" if d["pct"] >= 0 else "#ff4d6d"
        arrow = "▲" if d["pct"] >= 0 else "▼"
        cards += f"""
        <div style="background:#111318;border:1px solid #1e2330;border-radius:8px;padding:14px;min-width:120px">
          <div style="font-family:monospace;font-size:10px;color:#5a6480;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">{name}</div>
          <div style="font-family:monospace;font-size:16px;font-weight:700;color:#eef2ff;margin-bottom:3px">{d['close']:,.2f}</div>
          <div style="font-family:monospace;font-size:12px;color:{color};font-weight:600">{arrow} {d['pct']:+.2f}% ({d['pts']:+.1f})</div>
          <div style="font-family:monospace;font-size:10px;color:#3a4060;margin-top:4px">Range: {d['low']:,.0f}–{d['high']:,.0f}</div>
        </div>"""

    # Format recap text as HTML
    recap_html = recap_text
    recap_html = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#eef2ff">\1</strong>', recap_html)
    recap_html = recap_html.replace('\n\n', '</p><p style="margin:0 0 14px;color:#c8d0e0;line-height:1.8">')
    recap_html = recap_html.replace('\n', '<br>')
    recap_html = f'<p style="margin:0 0 14px;color:#c8d0e0;line-height:1.8">{recap_html}</p>'
    # Color grade emojis
    recap_html = recap_html.replace('✅', '<span style="color:#00d4a0">✅</span>')
    recap_html = recap_html.replace('❌', '<span style="color:#ff4d6d">❌</span>')
    recap_html = recap_html.replace('⏭', '<span style="color:#5a6480">⏭</span>')
    recap_html = recap_html.replace('🔄', '<span style="color:#ffd166">🔄</span>')

    return f"""
    <div style="background:#0a0c10;padding:32px;font-family:'Courier New',monospace;max-width:680px;margin:0 auto">

      <div style="color:#ffd166;font-size:11px;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:8px">📊 Afternoon Recap</div>
      <h1 style="color:#eef2ff;font-size:22px;margin:0 0 4px;font-family:monospace">End of Day Report</h1>
      <div style="color:#5a6480;font-size:12px;margin-bottom:28px">{TODAY} · Markets Closed</div>

      <!-- CLOSING PRICES -->
      <div style="margin-bottom:24px">
        <div style="color:#4d9fff;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px">Closing Prices</div>
        <div style="display:flex;flex-wrap:wrap;gap:10px">
          {cards}
        </div>
      </div>

      <!-- RECAP ANALYSIS -->
      <div style="background:#111318;border:1px solid #1e2330;border-radius:8px;padding:24px;margin-bottom:20px;font-family:Georgia,serif;font-size:14px">
        {recap_html}
      </div>

      {'<div style="text-align:center;margin-bottom:20px"><a href="' + DASHBOARD_URL + '" style="color:#4d9fff;font-family:monospace;font-size:12px">View Morning Dashboard →</a></div>' if DASHBOARD_URL else ''}

      <div style="color:#3a4060;font-size:11px;text-align:center">Not financial advice. For informational purposes only.</div>
    </div>"""


# ── SEND EMAIL ─────────────────────────────────────────────────────────────────

def send_recap_email(html_content, recap_text):
    """Send the afternoon recap email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Afternoon Recap — {TODAY}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL

    text = f"Afternoon Recap — {TODAY}\n\n{recap_text}"
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print("✅ Recap email sent successfully")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    print(f"📊 Generating Afternoon Recap for {TODAY}...")

    print("  → Fetching closing data...")
    closing_data = get_closing_data()

    print("  → Fetching morning dashboard context...")
    morning_analysis, setups = fetch_morning_context()

    print("  → Generating AI recap...")
    recap_text = generate_recap(closing_data, morning_analysis, setups)

    print("  → Building email...")
    html = build_recap_html(closing_data, recap_text)

    print("  → Sending recap email...")
    send_recap_email(html, recap_text)

    print("✅ Afternoon recap complete!")


if __name__ == "__main__":
    main()
