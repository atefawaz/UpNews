#!/usr/bin/env python3
"""
telegram_listener.py — Always-on Telegram bot: type any topic, get
recent articles about it back as a reply.

Run continuously (e.g. as a systemd service on a server):
    python3 telegram_listener.py

HOW IT WORKS
------------
Telegram bots don't get pushed messages automatically — you have to ask
("poll") "any new messages for me?" repeatedly. This script uses "long
polling": each request to Telegram's getUpdates endpoint stays open for
up to 30 seconds waiting for a new message, instead of hammering the API
every second. When a message arrives, it's treated as a search topic,
same as running `python3 search_news.py "<topic>"` yourself, and the
results are sent back as a reply.

Only messages from your own configured TELEGRAM_CHAT_ID are processed,
so if anyone else ever finds your bot's username, their messages are
silently ignored.
"""

import time
import requests

from news_bot import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, format_items, send_chunked
from search_news import search

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

HELP_TEXT = (
    "Send me any topic (e.g. \"Iran vs US\" or \"Jeffrey Epstein\") "
    "and I'll reply with recent articles about it."
)


def get_updates(offset, timeout=30):
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=timeout + 10)
    resp.raise_for_status()
    return resp.json().get("result", [])


def handle_topic(topic):
    if topic.strip().lower() in ("/start", "/help"):
        send_chunked([HELP_TEXT])
        return
    results = search(topic, limit=15)
    message_parts = [f"<b>🔎 {topic}</b>"]
    if results:
        message_parts.extend(format_items(results))
    else:
        message_parts.append("<i>No articles found.</i>")
    send_chunked(message_parts)


def run():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[error] Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        return

    # Skip any backlog on startup — only respond to messages sent from now on.
    offset = None
    backlog = get_updates(offset, timeout=1)
    if backlog:
        offset = backlog[-1]["update_id"] + 1

    print("[ok] Listening for messages...")
    while True:
        try:
            updates = get_updates(offset, timeout=30)
        except requests.RequestException as e:
            print(f"[warn] getUpdates failed: {e}")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text", "")

            if chat_id != str(TELEGRAM_CHAT_ID) or not text:
                continue

            print(f"[ok] Search request: {text}")
            try:
                handle_topic(text)
            except Exception as e:
                print(f"[warn] Failed to handle '{text}': {e}")


if __name__ == "__main__":
    run()
