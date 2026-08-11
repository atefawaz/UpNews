#!/usr/bin/env python3
"""
news_bot.py — Personal daily news digest for Telegram.

WHAT THIS DOES
--------------
Once a day, sends you ONE message split into two clearly separated
sections:

  🎯 DEPTH   — specialist analysis from think tanks / trade press
               (ISW, Crisis Group, Foreign Policy, etc). Fewer, denser,
               higher signal-to-noise. This is "what does it actually
               mean" content.

  🌍 BREADTH — top general headlines (Google News' own "what's leading
               right now" ranking) across World, Business, and
               Science/Tech. This is "what's happening everywhere"
               content.

Both sides cover geopolitics/security, economy/energy, and tech/science
— you asked for "all" of it, just organized so depth and breadth don't
blur together.

SETUP (one-time)
-----------------
1. Message @BotFather on Telegram -> /newbot -> get a bot token.
2. Message your bot once, then visit:
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   and grab your numeric chat_id from "chat":{"id": ...}.
3. Set environment variables:
   export TELEGRAM_BOT_TOKEN="123456789:ABC..."
   export TELEGRAM_CHAT_ID="987654321"
4. Run once to test: python3 news_bot.py
5. Automate as ONE daily run, e.g. cron at 7:30am:
   30 7 * * * /usr/bin/python3 /path/to/news_bot.py >> /path/to/bot.log 2>&1

NOTE ON FEED URLS
-----------------
The DEPTH_FEEDS below are real, known feed URLs as of research at
build time. Outlets occasionally change their RSS paths — if a feed
stops returning entries, open the URL in a browser to confirm it
still resolves, then update it here.
"""

import os
import json
import time
import hashlib
from datetime import datetime, timezone
import requests
import feedparser

# ── CONFIG ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
MAX_DEPTH_ITEMS = 10   # denser, so keep this list tight
MAX_BREADTH_ITEMS = 10  # per breadth category

# ── DEPTH: specialist sources, direct feeds, grouped loosely by lens ──
DEPTH_FEEDS = {
    "Geopolitics & Security": [
        "https://www.understandingwar.org/rss.xml",          # ISW
        "https://www.longwarjournal.org/feed",                 # Long War Journal
        "https://www.crisisgroup.org/rss.xml",                 # Crisis Group
        "https://foreignpolicy.com/feed/",                      # Foreign Policy
    ],
    "Economy & Energy": [
        "https://www.cnbc.com/id/100727362/device/rss/rss.html",  # CNBC World
    ],
    "Tech & Science": [
        "https://www.technologyreview.com/feed/",               # MIT Tech Review
        "https://feeds.arstechnica.com/arstechnica/index",       # Ars Technica
    ],
}

# ── BREADTH: Google News' own top-headlines ranking, per category ─────
BREADTH_FEEDS = {
    "World": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    "Business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
    "Science & Tech": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
}


# ── STATE (avoid re-sending the same story every day) ──────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"seen": []}


def save_state(state):
    state["seen"] = state["seen"][-6000:]  # cap growth
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def entry_id(entry):
    key = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ── FETCHING ────────────────────────────────────────────────────────

def fetch_feed_entries(url, limit):
    try:
        feed = feedparser.parse(url)
        return feed.entries[:limit]
    except Exception as e:
        print(f"[warn] failed to fetch {url}: {e}")
        return []


def dedupe_by_title(entries):
    seen_titles = set()
    out = []
    for e in entries:
        key = e.get("title", "").lower()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            out.append(e)
    return out


def build_section(entries, seen_ids, new_seen_ids, limit):
    fresh = []
    for e in entries:
        eid = entry_id(e)
        if eid not in seen_ids:
            fresh.append(e)
            new_seen_ids.add(eid)
    return dedupe_by_title(fresh)[:limit]


# ── TELEGRAM ────────────────────────────────────────────────────────

def send_telegram_message(text):
    if not text.strip():
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=15)
    if not resp.ok:
        print(f"[warn] Telegram send failed: {resp.status_code} {resp.text[:200]}")


def format_items(entries):
    lines = []
    for e in entries:
        title = e.get("title", "Untitled")
        link = e.get("link", "")
        source = ""
        if hasattr(e, "source") and getattr(e.source, "title", None):
            source = f" ({e.source.title})"
        lines.append(f"• <a href=\"{link}\">{title}</a>{source}")
    return lines


# ── MAIN ────────────────────────────────────────────────────────────

def run():
    if "PUT_YOUR" in TELEGRAM_BOT_TOKEN or "PUT_YOUR" in TELEGRAM_CHAT_ID:
        print("[error] Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (env vars or in the script).")
        return

    state = load_state()
    seen_ids = set(state["seen"])
    new_seen_ids = set(seen_ids)

    today = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    message_parts = [f"<b>🗞 Daily Digest — {today}</b>"]

    # --- DEPTH section ---
    message_parts.append("\n<b>🎯 DEPTH</b>  <i>(specialist analysis)</i>")
    depth_had_content = False
    for lens, feeds in DEPTH_FEEDS.items():
        entries = []
        for url in feeds:
            entries.extend(fetch_feed_entries(url, 8))
        section = build_section(entries, seen_ids, new_seen_ids, MAX_DEPTH_ITEMS)
        if section:
            depth_had_content = True
            message_parts.append(f"\n<b>{lens}</b>")
            message_parts.extend(format_items(section))
    if not depth_had_content:
        message_parts.append("<i>No new specialist items today.</i>")

    # --- BREADTH section ---
    message_parts.append("\n<b>🌍 BREADTH</b>  <i>(top headlines)</i>")
    breadth_had_content = False
    for category, url in BREADTH_FEEDS.items():
        entries = fetch_feed_entries(url, 15)
        section = build_section(entries, seen_ids, new_seen_ids, MAX_BREADTH_ITEMS)
        if section:
            breadth_had_content = True
            message_parts.append(f"\n<b>{category}</b>")
            message_parts.extend(format_items(section))
    if not breadth_had_content:
        message_parts.append("<i>No new headlines today.</i>")

    full_text = "\n".join(message_parts)

    # Telegram caps messages at 4096 chars — split into chunks if needed
    if len(full_text) <= 4000:
        send_telegram_message(full_text)
    else:
        chunk = ""
        for line in message_parts:
            if len(chunk) + len(line) + 1 > 4000:
                send_telegram_message(chunk)
                chunk = ""
                time.sleep(1)
            chunk += line + "\n"
        if chunk:
            send_telegram_message(chunk)

    state["seen"] = list(new_seen_ids)
    save_state(state)
    print(f"[ok] Digest sent. {len(new_seen_ids) - len(seen_ids)} new items.")


if __name__ == "__main__":
    run()
