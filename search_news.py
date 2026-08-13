#!/usr/bin/env python3
"""
search_news.py — On-demand topic search, e.g.:
    python3 search_news.py "Jeffrey Epstein"
    python3 search_news.py "Iran vs US" --limit 30
    python3 search_news.py "terrorism in MEA" --telegram

Pulls recent articles on any topic from Google News' search RSS feed
(no API key needed), dedupes them, and prints them to the terminal.
Add --telegram to also send the results to your Telegram bot, reusing
the same TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID as news_bot.py.
"""

import argparse
from urllib.parse import quote_plus

from news_bot import (
    fetch_feed_entries,
    dedupe_by_title,
    format_items,
    send_chunked,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)


def search_feed_url(topic):
    return f"https://news.google.com/rss/search?q={quote_plus(topic)}&hl=en-US&gl=US&ceid=US:en"


def search(topic, limit):
    entries = fetch_feed_entries(search_feed_url(topic), limit * 2)
    return dedupe_by_title(entries)[:limit]


def print_results(topic, results):
    print(f"\n{len(results)} articles found for: {topic}\n")
    for e in results:
        title = e.get("title", "Untitled")
        link = e.get("link", "")
        published = e.get("published", "")
        source = getattr(e, "source", None)
        source_name = getattr(source, "title", "") if source else ""
        print(f"- {title}")
        if source_name or published:
            print(f"  {source_name}{' — ' if source_name and published else ''}{published}")
        print(f"  {link}\n")


def main():
    parser = argparse.ArgumentParser(description="Search recent news articles on a topic.")
    parser.add_argument("topic", help="Topic to search for, e.g. \"Jeffrey Epstein\"")
    parser.add_argument("--limit", type=int, default=20, help="Max articles to return (default 20)")
    parser.add_argument("--telegram", action="store_true", help="Also send results to Telegram")
    args = parser.parse_args()

    results = search(args.topic, args.limit)
    print_results(args.topic, results)

    if args.telegram:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("[error] Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to use --telegram.")
            return
        message_parts = [f"<b>🔎 Search: {args.topic}</b>"]
        message_parts.extend(format_items(results))
        send_chunked(message_parts)
        print("[ok] Sent to Telegram.")


if __name__ == "__main__":
    main()
