# News Digest Bot

A personal Telegram bot that sends one daily digest of news, split into
two clearly separated sections:

- **🎯 Depth** — specialist analysis (ISW, Crisis Group, Long War
  Journal, Foreign Policy, MIT Tech Review, Ars Technica, CNBC World)
- **🌍 Breadth** — top general headlines (Google News' own "leading
  right now" ranking) across World, Business, and Science & Tech

## Why

Generic news aggregators optimize for popularity, not depth. This bot
gives you both, clearly labeled, once a day, with no repeats (it tracks
what it's already sent you in `state.json`).

## Setup

1. **Clone this repo and install dependencies**
   ```bash
   git clone <your-repo-url>
   cd news-digest-bot
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
   ```bash
   cp .env.example .env
   # then edit .env and fill in your real token and chat ID
   ```

5. **Run it once to test**
   ```bash
   export $(cat .env | xargs)
   python3 news_bot.py
   ```

## Running it daily

**Option A — cron (if running on your own server)**
```bash
crontab -e
# add this line to run every day at 7:30am:
30 7 * * * cd /path/to/news-digest-bot && export $(cat .env | xargs) && /usr/bin/python3 news_bot.py >> bot.log 2>&1
```

**Option B — GitHub Actions (no server needed)**
This repo includes `.github/workflows/digest.yml`, which runs the bot
automatically on GitHub's own servers every day. See that file's
comments for setup — you just need to add your token/chat ID as
GitHub repo secrets instead of a local `.env` file.

## Project structure

```
news-digest-bot/
├── news_bot.py              # main script
├── requirements.txt         # Python dependencies
├── .env.example              # template for required secrets
├── .gitignore                 # keeps secrets and local state out of git
└── .github/workflows/
    └── digest.yml             # optional: run daily via GitHub Actions
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
- Economy/Energy depth coverage is currently thin (just CNBC World) —
  a good first contribution if you want to extend this yourself.
# UpNews
