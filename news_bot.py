#!/usr/bin/env python3
"""
news_bot.py — Personal daily news digest for Telegram.

WHAT THIS DOES
--------------
Once a day, sends you ONE message split into two clearly separated
sections:

  🎯 DEPTH   — specialist analysis across four lenses: Military &
               Security, Economy & Finance, Technology, and Science
               (ISW, Crisis Group, Breaking Defense, MIT Tech Review,
               ScienceDaily, etc). Top 3 per lens — light touch, not
               a flood.

  🌍 BREADTH — top headlines from SIX continents/regions (North
               America, Europe, Middle East, Africa, Asia-Pacific,
               Latin America), top 3 each, so no region is invisible
               and no single outlet's ranking dominates.

Both sides are capped deliberately light — enough to stay genuinely
aware across every topic and every continent, without any one section
burying the rest. That's the actual point: breadth AND depth, together,
in something you'll actually read every day.

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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Light touch, uniformly, across every lens/continent — enough to stay
# genuinely aware of each topic without any one section burying the rest.
DEPTH_ITEM_CAP = 3
BREADTH_ITEM_CAP = 3

# ── DEPTH: specialist sources, direct feeds, one lens per category ────
DEPTH_FEEDS = {
    "Military & Security": [
        "https://www.understandingwar.org/rss.xml",           # ISW
        "https://www.longwarjournal.org/feed",                  # Long War Journal
        "https://www.crisisgroup.org/rss.xml",                  # Crisis Group
        "https://breakingdefense.com/feed/",                     # Breaking Defense
        "https://www.navalnews.com/feed/",                       # Naval News
    ],
    "Economy & Finance": [
        "https://www.cnbc.com/id/100727362/device/rss/rss.html",  # CNBC World
        "https://foreignpolicy.com/feed/",                        # Foreign Policy (geoeconomics)
    ],
    "Technology": [
        "https://www.technologyreview.com/feed/",               # MIT Tech Review
        "https://feeds.arstechnica.com/arstechnica/index",       # Ars Technica
        "https://techcrunch.com/feed/",                          # TechCrunch
    ],
    "Science": [
        "https://www.sciencedaily.com/rss/all.xml",              # ScienceDaily (broad science news)
    ],
}

# ── BREADTH: top headlines by CONTINENT, so no region is invisible ────
# Google News publishes localized top-headline editions per country —
# using those (in English) gives genuinely different regional news
# agendas, not just one US-based algorithm relabeled as "world news."
# BBC and Al Jazeera are added as two more independent editorial voices
# (London and Doha) since they cover cross-regional stories well.
BREADTH_FEEDS = {
    "North America": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "Europe": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Middle East": "https://www.aljazeera.com/xml/rss/all.xml",
    "Africa": "https://news.google.com/rss?hl=en-ZA&gl=ZA&ceid=ZA:en",
    "Asia-Pacific": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "Latin America": "https://news.google.com/rss?hl=en-MX&gl=MX&ceid=MX:en",
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


def send_chunked(message_parts):
    """Join message_parts with newlines and send, splitting into multiple
    Telegram messages if needed (Telegram caps messages at 4096 chars)."""
    full_text = "\n".join(message_parts)
    if len(full_text) <= 4000:
        send_telegram_message(full_text)
        return
    chunk = ""
    for line in message_parts:
        if len(chunk) + len(line) + 1 > 4000:
            send_telegram_message(chunk)
            chunk = ""
            time.sleep(1)
        chunk += line + "\n"
    if chunk:
        send_telegram_message(chunk)


# ── MAIN ────────────────────────────────────────────────────────────

def run():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
        section = build_section(entries, seen_ids, new_seen_ids, DEPTH_ITEM_CAP)
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
        section = build_section(entries, seen_ids, new_seen_ids, BREADTH_ITEM_CAP)
        if section:
            breadth_had_content = True
            message_parts.append(f"\n<b>{category}</b>")
            message_parts.extend(format_items(section))
    if not breadth_had_content:
        message_parts.append("<i>No new headlines today.</i>")

    send_chunked(message_parts)

    state["seen"] = list(new_seen_ids)
    save_state(state)
    print(f"[ok] Digest sent. {len(new_seen_ids) - len(seen_ids)} new items.")


if __name__ == "__main__":
    run()
