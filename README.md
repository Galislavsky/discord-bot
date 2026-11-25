🇬🇧 **English** | 🇵🇱 [Polska wersja](README.pl.md)

# Discord Bot

A multi-purpose Discord bot written in Python with [discord.py](https://github.com/Rapptz/discord.py).
It combines a leveling system, moderation, tickets, music and automatic notifications in a single process.

> The bot's messages and commands are in Polish, since it runs on a Polish-speaking server.

## Features

**XP and ranks**
- XP for chat messages (with a cooldown) and for time spent on voice channels
- automatic role assignment when XP thresholds are reached
- profile card rendered as an image (Pillow): avatar, rank, progress bar, leaderboard position
- `!daily` bonus with a reward that grows with your streak
- all-time and monthly leaderboards; on the 1st of each month the most active member gets the VIP role

**Moderation and logs**
- detection of invites to other servers, a warning system and an automatic timeout after 3 warnings
- logs for joins, leaves, bans, deleted and edited messages

**Tickets**
- panel with a button that creates a private channel for the user and the support team
- buttons keep working after a restart (persistent views)
- conversation transcript saved as a `.txt` file when the ticket is closed

**Voice channels and music**
- Join-to-Create: joining a channel creates a private room that is removed once it's empty
- music playback with a queue, pause, skip and volume control (yt-dlp + FFmpeg)

**Automatic notifications**
- Twitch stream start (Twitch Helix API, app access token refreshed automatically)
- new YouTube videos (RSS feed, no API key needed)
- daily meme and `/bump` reminders

## Tech stack

Python 3.11+ · discord.py · asyncio / aiohttp · Pillow · yt-dlp · FFmpeg · JSON as a lightweight database

## Getting started

```bash
git clone https://github.com/Galislavsky/discord-bot.git
cd discord-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

FFmpeg is also required for music, e.g. `sudo apt install ffmpeg`.

1. Copy `.env.example` to `.env` and add your bot token (and optionally your Twitch app credentials).
2. Copy `config.example.json` to `config.json` and fill in the channel and role IDs from your server.
3. In the [Discord Developer Portal](https://discord.com/developers/applications), enable the **Server Members** and **Message Content** intents.
4. Run:

```bash
python bot.py
```

On a server, the bot can run under a process manager such as PM2:

```bash
pm2 start bot.py --name discord-bot --interpreter ./venv/bin/python
```

## Commands

| Command | Description |
|---|---|
| `!profil [@user]` | Profile card with XP and rank |
| `!daily` | Daily XP bonus |
| `!top`, `!ranking` | All-time leaderboard |
| `!viptop` | Monthly leaderboard |
| `!graj <title/link>` | Play music |
| `!pomin`, `!pauza`, `!wznow`, `!kolejka`, `!glosnosc <0-100>`, `!wyjdz` | Skip, pause, resume, queue, volume, leave |
| `!dodaj @user` | Add someone to a ticket |
| `!ping` | Bot latency |

Admin commands: `!ticketpanel` (ticket panel), `!reg` (server rules), `!wyczysc <amount>` (purge messages), `!usunxp @user` (reset XP), `!nowyfilm <link>` / `!live <link>` (manual announcements), `!ustaw_bump` (reset bump timer).

## About

I built this bot for my own Discord server, where it runs every day (Ubuntu VPS, managed with PM2).
I used AI tools while writing the code – the feature ideas, testing on a live server,
deployment and maintenance are my own.
