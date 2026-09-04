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
import re
import json
import time
import html
import hashlib
from datetime import datetime, timezone
import requests
import feedparser
from bs4 import BeautifulSoup

SUMMARY_MAX_LEN = 180

# ── LOCAL LLM (Ollama) BULLET SUMMARIES ────────────────────────────────
# Only used for the daily digest, whose feeds all have real, directly
# fetchable article links. Falls back to clean_summary() above if
# Ollama isn't running, the article can't be fetched, or anything times
# out — this must never be able to break the digest.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
ARTICLE_FETCH_TIMEOUT = 10
OLLAMA_TIMEOUT = 30
ARTICLE_TEXT_MAX_LEN = 4000

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
# Each region uses a direct outlet feed (not Google News) so entries carry
# a real article summary and a real, directly-fetchable link — Google
# News RSS links only resolve through an obfuscated consent/redirect
# wall, so they can never carry a usable one-line summary.
BREADTH_FEEDS = {
    "North America": "https://feeds.npr.org/1001/rss.xml",              # NPR
    "Europe": "http://feeds.bbci.co.uk/news/world/rss.xml",              # BBC
    "Middle East": "https://www.aljazeera.com/xml/rss/all.xml",          # Al Jazeera
    "Africa": "http://feeds.bbci.co.uk/news/world/africa/rss.xml",       # BBC Africa
    "Asia-Pacific": "https://www.channelnewsasia.com/rssfeeds/8395884",  # CNA Asia
    "Latin America": "https://en.mercopress.com/rss/",                   # MercoPress
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


def clean_summary(entry):
    """Return a short plain-text summary from the feed's own RSS description,
    or "" if there isn't a usable one. Google News feeds stuff their
    <summary> with a bare HTML list of links to related articles rather
    than actual article text, so those are detected and skipped."""
    raw = entry.get("summary", "")
    if not raw or "<a " in raw:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", "", raw))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_MAX_LEN:
        text = text[:SUMMARY_MAX_LEN].rsplit(" ", 1)[0] + "…"
    return text


def fetch_article_text(url):
    """Best-effort fetch of an article's main readable text. Returns ""
    on any failure (network error, no article-shaped content, etc.) —
    callers must treat that as "no bullets available", not an error."""
    try:
        resp = requests.get(url, timeout=ARTICLE_FETCH_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = " ".join(p for p in paragraphs if len(p) > 40)
        return text[:ARTICLE_TEXT_MAX_LEN]
    except Exception:
        return ""


def _ollama_bullets(prompt, max_bullets):
    """Send a prompt to the local Ollama model and pull out its bulleted
    lines. Returns [] on any failure (Ollama not running, timeout, no
    bullet-shaped lines in the response, etc.)."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
    except Exception:
        return []
    bullets = [
        line.strip().lstrip("-•").strip()
        for line in text.splitlines()
        if line.strip().startswith(("-", "•"))
    ]
    return bullets[:max_bullets]


def bullet_summary(title, article_text):
    """Ask the local Ollama model for 2-3 punchy factual bullet points on
    the article. Returns [] if Ollama isn't reachable, times out, or the
    article text is empty — callers should fall back to clean_summary()."""
    if not article_text:
        return []
    prompt = (
        f"Article title: {title}\n\nArticle text:\n{article_text}\n\n"
        "Summarize the key facts in exactly 2-3 short, punchy bullet points "
        "(max ~20 words each, no filler words). "
        "Each bullet on its own line starting with \"- \". "
        "Only use facts from the article text above, no outside knowledge, no commentary."
    )
    return _ollama_bullets(prompt, max_bullets=3)


def topic_recap(topic, entries):
    """Synthesize a short recap of what's currently going on with a topic
    from a list of search-result feed entries. Search results come from
    Google News, whose article pages can't be fetched (see README), so
    this works from headlines + source names only, not full article
    text — still enough signal to merge overlapping coverage into a
    real recap instead of a raw list of near-duplicate headlines.
    Returns [] if there's nothing to summarize or Ollama is unavailable
    — callers should fall back to listing the raw entries."""
    lines = []
    for e in entries:
        title = (e.get("title") or "").strip()
        source = getattr(getattr(e, "source", None), "title", "") or ""
        if title:
            lines.append(f"- {title}" + (f" ({source})" if source else ""))
    if not lines:
        return []
    prompt = (
        f"Topic: {topic}\n\n"
        f"Recent headlines about this topic, from different outlets:\n{chr(10).join(lines)}\n\n"
        "Write a concise recap of what's currently going on, in 4-6 short, "
        "punchy bullet points (max ~20 words each). Merge overlapping "
        "headlines into single facts, don't repeat the same point twice, "
        "and only use information present in the headlines above — don't "
        "invent facts or add outside knowledge. Each bullet on its own "
        "line starting with \"- \"."
    )
    return _ollama_bullets(prompt, max_bullets=6)


def format_items(entries, use_llm=False):
    lines = []
    for e in entries:
        title = e.get("title", "Untitled")
        link = e.get("link", "")
        source = ""
        if hasattr(e, "source") and getattr(e.source, "title", None):
            source = f" ({e.source.title})"
        lines.append(f"• <a href=\"{link}\">{title}</a>{source}")

        bullets = bullet_summary(title, fetch_article_text(link)) if (use_llm and link) else []
        if bullets:
            for b in bullets:
                lines.append(f"  ▸ {html.escape(b)}")
        else:
            summary = clean_summary(e)
            if summary:
                lines.append(f"  <i>{summary}</i>")
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
            message_parts.extend(format_items(section, use_llm=True))
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
            message_parts.extend(format_items(section, use_llm=True))
    if not breadth_had_content:
        message_parts.append("<i>No new headlines today.</i>")

    send_chunked(message_parts)

    state["seen"] = list(new_seen_ids)
    save_state(state)
    print(f"[ok] Digest sent. {len(new_seen_ids) - len(seen_ids)} new items.")


if __name__ == "__main__":
    run()
