# Discord Bot

Wielofunkcyjny bot na Discorda napisany w Pythonie z użyciem [discord.py](https://github.com/Rapptz/discord.py).
Łączy system poziomów, moderację, tickety, muzykę i automatyczne powiadomienia w jednym procesie.

## Funkcje

**System XP i rang**
- XP za wiadomości (z cooldownem) i za czas na kanałach głosowych
- automatyczne nadawanie ról po przekroczeniu progów XP
- karta profilu generowana jako obrazek (Pillow): avatar, ranga, pasek postępu, miejsce w rankingu
- codzienny bonus `!daily` z rosnącą nagrodą za serię
- ranking ogólny i miesięczny; 1. dnia miesiąca najaktywniejsza osoba dostaje rolę VIP

**Moderacja i logi**
- wykrywanie zaproszeń na inne serwery, system ostrzeżeń i automatyczny timeout po 3 ostrzeżeniach
- logi wejść, wyjść, banów, usuniętych i edytowanych wiadomości

**Tickety**
- panel z przyciskiem tworzącym prywatny kanał dla użytkownika i supportu
- przyciski działają po restarcie bota (persistent views)
- transkrypt rozmowy zapisywany jako plik `.txt` po zamknięciu ticketu

**Kanały głosowe i muzyka**
- Join-to-Create: wejście na kanał tworzy prywatny pokój, który znika, gdy jest pusty
- odtwarzanie muzyki z kolejką, pauzą, pomijaniem i regulacją głośności (yt-dlp + FFmpeg)

**Automatyczne powiadomienia**
- start transmisji na Twitchu (Twitch Helix API, token aplikacji odświeżany automatycznie)
- nowe filmy na YouTube (kanał RSS, bez klucza API)
- codzienny mem i przypomnienia o `/bump`

## Technologie

Python 3.11+ · discord.py · asyncio / aiohttp · Pillow · yt-dlp · FFmpeg · JSON jako lekka baza danych

## Uruchomienie

```bash
git clone <adres-repozytorium>
cd <folder>
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Wymagany jest też FFmpeg (do muzyki), np. `sudo apt install ffmpeg`.

1. Skopiuj `.env.example` do `.env` i wpisz token bota (oraz opcjonalnie dane aplikacji Twitch).
2. Skopiuj `config.example.json` do `config.json` i uzupełnij ID kanałów i ról ze swojego serwera.
3. W [Discord Developer Portal](https://discord.com/developers/applications) włącz intenty **Server Members** i **Message Content**.
4. Uruchom:

```bash
python bot.py
```

Na serwerze bot może działać pod menedżerem procesów, np. PM2:

```bash
pm2 start bot.py --name discord-bot --interpreter ./venv/bin/python
```

## Komendy

| Komenda | Opis |
|---|---|
| `!profil [@osoba]` | Karta profilu z XP i rangą |
| `!daily` | Codzienny bonus XP |
| `!top`, `!ranking` | Ranking ogólny |
| `!viptop` | Ranking miesięczny |
| `!graj <tytuł/link>` | Odtwarzanie muzyki |
| `!pomin`, `!pauza`, `!wznow`, `!kolejka`, `!glosnosc <0-100>`, `!wyjdz` | Sterowanie muzyką |
| `!dodaj @osoba` | Dodanie osoby do ticketu |
| `!ping` | Opóźnienie bota |

Komendy administracyjne: `!ticketpanel`, `!reg`, `!wyczysc <ilość>`, `!usunxp @osoba`, `!nowyfilm <link>`, `!live <link>`, `!ustaw_bump`.

## O projekcie

Bot powstał na potrzeby mojego serwera na Discordzie i działa na nim na co dzień (VPS z Ubuntu, proces pod PM2).
Przy pisaniu kodu korzystałem z pomocy narzędzi AI – pomysły na funkcje, testowanie na żywym serwerze,
wdrożenie i utrzymanie są moje.
