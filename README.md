# UpNews

A personal Telegram news system with three parts:

- **`news_bot.py`** — sends one daily digest at 8am, split into:
  - **🎯 Depth** — specialist analysis (ISW, Crisis Group, Long War Journal, Breaking Defense, Naval News, Foreign Policy, MIT Tech Review, Ars Technica, TechCrunch, ScienceDaily)
  - **🌍 Breadth** — top headlines from six regions (North America, Europe, Middle East, Africa, Asia-Pacific, Latin America), so no region is invisible
- **`search_news.py`** — on-demand topic search from the command line (e.g. `python3 search_news.py "Iran vs US"`)
- **`telegram_listener.py`** — always-on bot: type any topic to the bot in Telegram, get recent articles back as a reply

All three avoid re-sending the same story via `state.json`, and never crash the whole run if one feed is down.

## Setup

1. **Install dependencies**
   ```bash
   git clone <your-repo-url>
   cd UpNews
   pip install -r requirements.txt
   ```

2. **Get a Telegram bot token**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow the prompts
   - Copy the token it gives you

3. **Get your chat ID**
   - Message your new bot once (anything)
   - Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find `"chat":{"id": ...}` in the response — that's your chat ID

4. **Configure your secrets**
   Create a `.env` file (gitignored, never committed):
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

5. **Run it once to test**
   ```bash
   set -a; source .env; set +a
   python3 news_bot.py
   ```

## Running it in production

This is deployed on a small always-on Ubuntu server (Hetzner):

- **Daily digest** — a cron job (in `crontab -e`) runs `news_bot.py` at 8am, `TZ=Asia/Beirut`:
  ```
  TZ=Asia/Beirut
  0 8 * * * cd /opt/UpNews && /bin/bash -c "set -a; source .env; set +a; ./venv/bin/python3 news_bot.py" >> /var/log/upnews-digest.log 2>&1
  ```
- **On-demand search** — `telegram_listener.py` runs continuously as a systemd service (`upnews-search.service`), so you can message the bot any topic, anytime, and get a reply — no need to run anything manually.
  ```
  systemctl status upnews-search.service   # check it's running
  journalctl -u upnews-search.service -f   # watch logs live
  ```

## Project structure

```
UpNews/
├── news_bot.py           # daily digest: fetch → dedupe → format → send
├── search_news.py        # CLI: search a topic on demand, optional --telegram flag
├── telegram_listener.py  # always-on: replies to any message with a search on that topic
├── requirements.txt      # Python dependencies
├── .gitignore             # keeps secrets and local state out of git
└── state.json              # local, gitignored — tracks what's already been sent
```

## Customizing sources

Edit the `DEPTH_FEEDS` and `BREADTH_FEEDS` dictionaries at the top of
`news_bot.py`. Each is just a list of RSS feed URLs — add or remove
freely. If a feed stops returning items, open its URL in a browser to
confirm it still resolves.

## Notes / known limitations

- Feed URLs for specialist sources (ISW, Crisis Group, etc.) were
  sourced from research, not fetched and verified live — check them
  once in a browser before relying on this daily.
- `telegram_listener.py` only responds to messages from the chat ID in
  `.env` — messages from anyone else who finds the bot are ignored.
