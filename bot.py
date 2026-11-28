import asyncio
import io
import json
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ================= KONFIGURACJA =================

TOKEN_BOTA = os.getenv("DISCORD_TOKEN")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

PLIK_KONFIGURACJI = "config.json"
PLIK_BAZY = "baza.json"


def wczytaj_konfiguracje():
    if not os.path.exists(PLIK_KONFIGURACJI):
        raise SystemExit(f"Brak pliku {PLIK_KONFIGURACJI}. Skopiuj config.example.json i uzupełnij ID.")
    with open(PLIK_KONFIGURACJI, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = wczytaj_konfiguracje()
KANALY = CFG["kanaly"]
ROLE = CFG["role"]

ID_KANALU_LOGOW = KANALY["logi"]
ID_KANALU_BUMP = KANALY["bump"]
ID_KANALU_MEMY = KANALY["memy"]
ID_KANALU_POWITAN = KANALY["powitania"]
ID_KANALU_CZATU = KANALY["czat"]
ID_KANALU_OGLOSZEN = KANALY["ogloszenia"]
ID_KANALU_JTC = KANALY["join_to_create"]
ID_KATEGORII_TICKETOW = KANALY["kategoria_ticketow"]
ID_KANALU_KOMEND = KANALY.get("komendy", 0)

ID_ROLI_NOWY = ROLE["nowy_uzytkownik"]
ID_ROLI_VIP = ROLE["vip"]
ID_ROLI_YT = ROLE["ping_youtube"]
ID_ROLI_TWITCH = ROLE["ping_twitch"]
ID_ROLI_AKTUALIZACJE = ROLE.get("ping_aktualizacje", 0)
ID_ROLI_SUPPORT = ROLE["support"]
ROLE_BEZ_XP = ROLE["bez_xp"]

# Próg XP -> ID roli
RANGI = {int(prog): rola_id for prog, rola_id in CFG["rangi"].items()}

TWITCH_LOGIN = CFG.get("twitch_login", "")
YOUTUBE_CHANNEL_ID = CFG.get("youtube_channel_id", "")
SUBREDDIT_MEMOW = CFG.get("subreddit_memow", "memes")
NAZWA_SERWERA = CFG.get("nazwa_serwera", "serwerze")
STATUSY = CFG.get("statusy", [])
STRONA = CFG.get("strona", "")  # np. https://twoja-domena.pl – link do rankingu online
PREFIKS_TICKETOW = CFG.get("prefiks_ticketow", "tickety")
NAZWA_POKOJU = CFG.get("nazwa_pokoju", "🏠┃pokój {uzytkownik}")
POWITANIA = CFG.get("powitania", [
    "Witaj {uzytkownik}! Rozgość się i czuj się jak u siebie.",
    "Cześć {uzytkownik}! Wpadaj na czat i przywitaj się z resztą.",
    "Super, że jesteś, {uzytkownik}! Witamy na {serwer}.",
])

DAILY_BAZA = 50
DAILY_ZA_DZIEN = 10
DAILY_MAX = 150

XP_WIADOMOSC = (15, 25)
XP_VOICE_NA_MINUTE = 10
COOLDOWN_XP_SEKUNDY = 60

STREFA = ZoneInfo(CFG.get("strefa_czasowa", "Europe/Warsaw"))
KOLOR_KARTY = (88, 101, 242)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.moderation = True


class Bot(commands.Bot):
    async def setup_hook(self):
        # Rejestracja widoków, żeby przyciski ticketów działały po restarcie
        self.add_view(PanelTicketow())
        self.add_view(ZamknijTicket())

    async def on_ready_sync(self):
        """Rejestruje slash-komendy na serwerach bota (natychmiast, bez czekania na globalną propagację)."""
        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        print(f"Zsynchronizowano slash-komendy ({len(self.tree.get_commands())})")


bot = Bot(command_prefix=CFG.get("prefix", "!"), intents=intents)


# ================= BAZA DANYCH =================

def wczytaj_baze():
    if os.path.exists(PLIK_BAZY):
        with open(PLIK_BAZY, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def zapisz_baze(dane):
    # Zapis atomowy: najpierw plik tymczasowy, potem podmiana
    tmp = PLIK_BAZY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dane, f, indent=4, ensure_ascii=False)
    os.replace(tmp, PLIK_BAZY)


def meta(dane):
    return dane.setdefault("METADATA", {})


def tylko_uzytkownicy(dane):
    return {k: v for k, v in dane.items() if k != "METADATA"}


def profil_uzytkownika(dane, user_id):
    return dane.setdefault(str(user_id), {"xp": 0, "monthly_xp": 0, "last_msg": 0})


def dodaj_xp(dane, user_id, ile):
    p = profil_uzytkownika(dane, user_id)
    p["xp"] = p.get("xp", 0) + ile
    p["monthly_xp"] = p.get("monthly_xp", 0) + ile
    return p["xp"]


def bez_xp(member):
    return any(rola.id in ROLE_BEZ_XP for rola in getattr(member, "roles", []))


def info_rangi(xp):
    """Zwraca (id_aktualnej_roli, próg_aktualny, próg_następny)."""
    aktualna_id, prog_od, prog_do = None, 0, None
    for prog in sorted(RANGI):
        if xp >= prog:
            aktualna_id, prog_od = RANGI[prog], prog
        elif prog_do is None:
            prog_do = prog
    return aktualna_id, prog_od, prog_do


def przytnij(tekst, limit=1000):
    if not tekst or len(tekst) <= limit:
        return tekst
    return tekst[:limit] + "..."


async def sprawdz_range(member, xp):
    rola_id, _, _ = info_rangi(xp)
    if not rola_id:
        return

    nowa_rola = member.guild.get_role(rola_id)
    if not nowa_rola or nowa_rola in member.roles:
        return

    stare_role = [
        r for r in (member.guild.get_role(i) for i in RANGI.values() if i != rola_id)
        if r and r in member.roles
    ]
    if stare_role:
        await member.remove_roles(*stare_role)
    await member.add_roles(nowa_rola)

    kanal = bot.get_channel(ID_KANALU_CZATU)
    if kanal:
        embed = discord.Embed(
            title="🎉 Awans!",
            description=f"Gratulacje {member.mention}! Zdobywasz rangę **{nowa_rola.name}**! 🚀",
            color=discord.Color.green(),
        )
        await kanal.send(embed=embed)


# ================= START I ZADANIA CYKLICZNE =================

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    if not getattr(bot, "_zsynchronizowano", False):
        try:
            await bot.on_ready_sync()
            bot._zsynchronizowano = True
        except discord.HTTPException as e:
            print(f"[Slash] Błąd synchronizacji: {e}")
    await posprzataj_pokoje_jtc()
    for petla in (przypomnienie_bump, codzienny_mem, naliczaj_xp_voice, rotacja_statusu,
                  rotacja_vip, sprawdz_twitch, sprawdz_youtube):
        if not petla.is_running():
            petla.start()


async def posprzataj_pokoje_jtc():
    """Usuwa puste pokoje Join-to-Create, które zostały po restarcie bota."""
    dane = wczytaj_baze()
    m = meta(dane)
    zostaja = []
    for kanal_id in m.get("jtc", []):
        kanal = bot.get_channel(kanal_id)
        if kanal is None:
            continue
        if any(not czl.bot for czl in kanal.members):
            zostaja.append(kanal_id)
            continue
        try:
            await kanal.delete()
        except discord.HTTPException:
            zostaja.append(kanal_id)
    m["jtc"] = zostaja
    zapisz_baze(dane)


@tasks.loop(minutes=5)
async def rotacja_statusu():
    czlonkowie = sum(g.member_count or 0 for g in bot.guilds)
    aktywnosci = [discord.Activity(type=discord.ActivityType.watching, name=f"{czlonkowie} osób na serwerze")]
    for s in STATUSY:
        tekst = s["tekst"].format(czlonkowie=czlonkowie)
        if s.get("typ") == "oglada":
            aktywnosci.append(discord.Activity(type=discord.ActivityType.watching, name=tekst))
        else:
            aktywnosci.append(discord.Game(name=tekst))
    await bot.change_presence(activity=random.choice(aktywnosci))


@tasks.loop(minutes=1)
async def naliczaj_xp_voice():
    dane = wczytaj_baze()
    zmiana = False
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            if guild.afk_channel and vc.id == guild.afk_channel.id:
                continue
            for member in vc.members:
                if member.bot or bez_xp(member):
                    continue
                v = member.voice
                if v.self_mute or v.mute or v.self_deaf or v.deaf:
                    continue
                xp = dodaj_xp(dane, member.id, XP_VOICE_NA_MINUTE)
                zmiana = True
                bot.loop.create_task(sprawdz_range(member, xp))
    if zmiana:
        zapisz_baze(dane)


@tasks.loop(minutes=60)
async def rotacja_vip():
    """Pierwszego dnia miesiąca nadaje rolę VIP najaktywniejszej osobie i zeruje licznik miesięczny."""
    teraz = datetime.now(STREFA)
    if teraz.day != 1:
        return

    dane = wczytaj_baze()
    m = meta(dane)
    if m.get("ostatni_reset") == teraz.month:
        return

    uzytkownicy = tylko_uzytkownicy(dane)
    if not uzytkownicy:
        return

    najlepszy_id = max(uzytkownicy, key=lambda k: uzytkownicy[k].get("monthly_xp", 0))
    najlepszy_wynik = uzytkownicy[najlepszy_id].get("monthly_xp", 0)

    if najlepszy_wynik > 0:
        for guild in bot.guilds:
            rola_vip = guild.get_role(ID_ROLI_VIP)
            if not rola_vip:
                continue
            for member in rola_vip.members:
                await member.remove_roles(rola_vip)

            nowy_vip = guild.get_member(int(najlepszy_id))
            if not nowy_vip:
                continue
            await nowy_vip.add_roles(rola_vip)

            kanal = bot.get_channel(ID_KANALU_CZATU)
            if kanal:
                embed = discord.Embed(
                    title="👑 Użytkownik miesiąca (VIP)",
                    description=(
                        f"Tytuł VIP za najwyższą aktywność w minionym miesiącu zdobywa {nowy_vip.mention} "
                        f"z wynikiem **{najlepszy_wynik} pkt**!\n\n"
                        "Licznik miesięczny został wyzerowany – walka o tytuł rusza od nowa."
                    ),
                    color=discord.Color.gold(),
                )
                await kanal.send(embed=embed)

    for k in uzytkownicy:
        dane[k]["monthly_xp"] = 0
    m["ostatni_reset"] = teraz.month
    zapisz_baze(dane)


@rotacja_vip.before_loop
async def przed_rotacja_vip():
    await bot.wait_until_ready()


# ================= OGŁOSZENIA (YOUTUBE + TWITCH) =================

def kanal_ogloszen(zapasowy=None):
    return bot.get_channel(ID_KANALU_OGLOSZEN) or zapasowy


async def ogloszenie_film(kanal, link, tytul=None):
    tytul_txt = f"\n**{tytul}**" if tytul else ""
    await kanal.send(f"🎬 **Nowy film na YouTube!** <@&{ID_ROLI_YT}>{tytul_txt}\n\n{link}")


async def ogloszenie_live(kanal, link, tytul=None, gra=None, miniatura=None):
    opis = ""
    if tytul:
        opis += f"**{tytul}**\n"
    if gra:
        opis += f"🎮 Gra: **{gra}**\n"
    opis += f"\n📺 **Oglądaj:** {link}"
    embed = discord.Embed(title="🔴 Stream na żywo!", description=opis, color=0x9146FF, url=link)
    if miniatura:
        embed.set_image(url=miniatura)
    await kanal.send(content=f"<@&{ID_ROLI_TWITCH}>", embed=embed)


twitch_token = {"wartosc": None, "wygasa": 0}


async def token_twitch(session):
    """Token aplikacji Twitch (client credentials), odświeżany przed wygaśnięciem."""
    if twitch_token["wartosc"] and time.time() < twitch_token["wygasa"] - 60:
        return twitch_token["wartosc"]
    async with session.post("https://id.twitch.tv/oauth2/token", params={
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }) as r:
        d = await r.json()
    twitch_token["wartosc"] = d["access_token"]
    twitch_token["wygasa"] = time.time() + d.get("expires_in", 3600)
    return twitch_token["wartosc"]


@tasks.loop(minutes=2)
async def sprawdz_twitch():
    if not (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET and TWITCH_LOGIN):
        return
    kanal = kanal_ogloszen()
    if not kanal:
        return
    try:
        async with aiohttp.ClientSession() as session:
            token = await token_twitch(session)
            naglowki = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
            async with session.get("https://api.twitch.tv/helix/streams",
                                   params={"user_login": TWITCH_LOGIN}, headers=naglowki) as r:
                if r.status == 401:
                    twitch_token["wartosc"] = None
                    return
                if r.status != 200:
                    return
                d = await r.json()

        stream = d["data"][0] if d.get("data") else None
        if not stream:
            return

        dane = wczytaj_baze()
        m = meta(dane)
        # Zapamiętujemy ID streamu, żeby nie ogłaszać tego samego live dwa razy
        if m.get("twitch_stream_id") == stream["id"]:
            return
        m["twitch_stream_id"] = stream["id"]
        zapisz_baze(dane)

        miniatura = (stream["thumbnail_url"]
                     .replace("{width}", "1280").replace("{height}", "720")
                     + f"?t={int(time.time())}")
        await ogloszenie_live(kanal, f"https://twitch.tv/{TWITCH_LOGIN}",
                              tytul=stream.get("title"), gra=stream.get("game_name"), miniatura=miniatura)
    except Exception as e:
        print(f"[Twitch] Błąd: {e}")


@tasks.loop(minutes=5)
async def sprawdz_youtube():
    if not YOUTUBE_CHANNEL_ID.startswith("UC"):
        return
    kanal = kanal_ogloszen()
    if not kanal:
        return
    try:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return
                tekst = await r.text()

        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        root = ET.fromstring(tekst)
        filmy = [
            (e.find("yt:videoId", ns).text, e.find("atom:title", ns).text)
            for e in root.findall("atom:entry", ns)
        ]
        if not filmy:
            return

        dane = wczytaj_baze()
        m = meta(dane)
        widziane = m.get("yt_widziane")

        if widziane is None:
            # Pierwsze uruchomienie: zapisujemy istniejące filmy, żeby nie ogłaszać starych
            m["yt_widziane"] = [v for v, _ in filmy]
            zapisz_baze(dane)
            return

        nowe = [(v, t) for v, t in filmy if v not in widziane]
        if not nowe:
            return

        m["yt_widziane"] = ([v for v, _ in nowe] + widziane)[:50]
        zapisz_baze(dane)

        vid, tytul = nowe[0]
        await ogloszenie_film(kanal, f"https://www.youtube.com/watch?v={vid}", tytul)
    except Exception as e:
        print(f"[YouTube] Błąd: {e}")


@sprawdz_twitch.before_loop
@sprawdz_youtube.before_loop
async def przed_ogloszeniami():
    await bot.wait_until_ready()


# ================= EVENTY I LOGI =================

async def wyslij_log(embed, **kwargs):
    kanal = bot.get_channel(ID_KANALU_LOGOW)
    if kanal:
        await kanal.send(embed=embed, **kwargs)


def embed_uzytkownika(tytul, kolor, user):
    embed = discord.Embed(title=tytul, color=kolor)
    embed.add_field(name="Użytkownik", value=f"{user.mention} ({user.name})", inline=False)
    return embed


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    # Muzyka: czyścimy kolejkę, gdy bot został rozłączony albo został sam na kanale
    if member.id == bot.user.id and after.channel is None:
        wyczysc_muzyke(guild.id)
    vc = guild.voice_client
    if vc and vc.channel and not any(not m.bot for m in vc.channel.members):
        wyczysc_muzyke(guild.id)
        await vc.disconnect()

    # Join-to-Create: tworzenie prywatnego pokoju
    if after.channel and after.channel.id == ID_KANALU_JTC and not member.bot:
        nowy_kanal = await guild.create_voice_channel(
            name=NAZWA_POKOJU.format(uzytkownik=member.display_name)[:100],
            category=after.channel.category,
        )
        dane = wczytaj_baze()
        meta(dane).setdefault("jtc", []).append(nowy_kanal.id)
        zapisz_baze(dane)
        try:
            await member.move_to(nowy_kanal)
        except discord.HTTPException:
            await nowy_kanal.delete()

    # Join-to-Create: usuwanie pustego pokoju
    if before.channel:
        dane = wczytaj_baze()
        lista_jtc = meta(dane).get("jtc", [])
        if before.channel.id in lista_jtc and not any(not m.bot for m in before.channel.members):
            try:
                await before.channel.delete()
            except discord.NotFound:
                pass
            lista_jtc.remove(before.channel.id)
            zapisz_baze(dane)


@bot.event
async def on_member_join(member):
    rola = member.guild.get_role(ID_ROLI_NOWY)
    if rola:
        await member.add_roles(rola)

    kanal_powitan = bot.get_channel(ID_KANALU_POWITAN)
    if kanal_powitan:
        powitania = [p.format(uzytkownik=member.mention, serwer=NAZWA_SERWERA) for p in POWITANIA]
        await kanal_powitan.send(random.choice(powitania))

    await wyslij_log(embed_uzytkownika("📥 Nowy użytkownik", discord.Color.green(), member))


@bot.event
async def on_member_remove(member):
    await wyslij_log(embed_uzytkownika("👋 Użytkownik opuścił serwer", discord.Color.dark_gray(), member))


@bot.event
async def on_member_ban(guild, user):
    await wyslij_log(embed_uzytkownika("🔨 Użytkownik zbanowany", discord.Color.dark_red(), user))


@bot.event
async def on_member_unban(guild, user):
    await wyslij_log(embed_uzytkownika("🔓 Cofnięto bana", discord.Color.blue(), user))


@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    embed = discord.Embed(title="🗑️ Usunięta wiadomość", color=discord.Color.red())
    embed.add_field(name="Autor", value=message.author.mention, inline=True)
    embed.add_field(name="Kanał", value=message.channel.mention, inline=True)
    embed.add_field(name="Treść", value=przytnij(message.content) or "*Brak tekstu (plik/zdjęcie)*", inline=False)
    await wyslij_log(embed)


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    embed = discord.Embed(title="✏️ Edytowana wiadomość", color=discord.Color.orange())
    embed.add_field(name="Autor", value=before.author.mention, inline=True)
    embed.add_field(name="Kanał", value=before.channel.mention, inline=True)
    embed.add_field(name="Przed", value=przytnij(before.content) or "*Brak*", inline=False)
    embed.add_field(name="Po", value=przytnij(after.content) or "*Brak*", inline=False)
    embed.add_field(name="Link", value=f"[Przejdź do wiadomości]({after.jump_url})", inline=False)
    await wyslij_log(embed)


ZAKAZANE_LINKI = ("discord.gg/", "discord.com/invite/")


async def obsluz_reklame(message):
    """Usuwa zaproszenia na inne serwery, liczy ostrzeżenia i po 3 nakłada timeout."""
    await message.delete()

    dane = wczytaj_baze()
    ostrzezenia = meta(dane).setdefault("ostrzezenia", {})
    uid = str(message.author.id)
    ostrzezenia[uid] = ostrzezenia.get(uid, 0) + 1
    liczba = ostrzezenia[uid]
    if liczba >= 3:
        ostrzezenia[uid] = 0
    zapisz_baze(dane)

    await message.channel.send(
        f"⚠️ {message.author.mention}, zakaz reklamowania! (Ostrzeżenie {liczba}/3)",
        delete_after=5,
    )

    kara = "Brak (tylko ostrzeżenie)"
    if liczba >= 3:
        try:
            await message.author.timeout(timedelta(hours=1), reason="Reklamowanie innych serwerów")
            kara = "Timeout na 1 godzinę"
        except discord.Forbidden:
            kara = "Błąd: bot ma za niskie uprawnienia"

    embed = discord.Embed(title="🚨 Wykryto reklamę", color=discord.Color.dark_red())
    embed.add_field(name="Użytkownik", value=message.author.mention, inline=True)
    embed.add_field(name="Status", value=f"Ostrzeżenie {liczba}/3\n**Akcja:** {kara}", inline=False)
    await wyslij_log(embed)


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    if not bez_xp(message.author):
        dane = wczytaj_baze()
        p = profil_uzytkownika(dane, message.author.id)
        teraz = time.time()
        if teraz - p.get("last_msg", 0) >= COOLDOWN_XP_SEKUNDY:
            xp = dodaj_xp(dane, message.author.id, random.randint(*XP_WIADOMOSC))
            p["last_msg"] = teraz
            zapisz_baze(dane)
            await sprawdz_range(message.author, xp)

    if not message.author.guild_permissions.administrator:
        if any(link in message.content.lower() for link in ZAKAZANE_LINKI):
            await obsluz_reklame(message)
            return

    await bot.process_commands(message)


@bot.check
async def tylko_na_kanale_komend(ctx):
    """Komendy działają tylko na kanale komend (wyjątki: administracja i !dodaj w tickecie)."""
    if not ID_KANALU_KOMEND or not ctx.guild:
        return True
    if ctx.author.guild_permissions.administrator or ctx.channel.id == ID_KANALU_KOMEND:
        return True
    if ctx.command and ctx.command.name == "dodaj" and czy_ticket(ctx.channel):
        return True
    raise ZlyKanal()


class ZlyKanal(commands.CheckFailure, app_commands.CheckFailure):
    pass


async def potwierdz(ctx, emoji, tekst):
    """Przy komendzie z '!' dodaje reakcję, przy slash-komendzie odpisuje (interakcja musi dostać odpowiedź)."""
    if ctx.interaction:
        await ctx.send(f"{emoji} {tekst}")
    else:
        await ctx.message.add_reaction(emoji)


@bot.event
async def on_command_error(ctx, error):
    # Slash-komendy owijają błędy – wyciągamy oryginalny
    while isinstance(error, (commands.HybridCommandError, commands.CommandInvokeError, app_commands.CommandInvokeError)) \
            and getattr(error, "original", None):
        error = error.original
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, ZlyKanal):
        tekst = f"⚠️ {ctx.author.mention}, komend bota używaj na <#{ID_KANALU_KOMEND}>"
        if ctx.interaction:
            await ctx.send(tekst, ephemeral=True)
            return
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(tekst, delete_after=6)
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ Nie masz uprawnień do tej komendy.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Brakuje argumentu. Użycie: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
                       delete_after=8)
    elif isinstance(error, (commands.MemberNotFound, commands.BadArgument)):
        await ctx.send("⚠️ Nieprawidłowy argument.", delete_after=5)
    else:
        print(f"[Komenda {ctx.command}] Błąd: {error}")


# ================= KARTA RANGI =================

SCIEZKI_CZCIONEK = [
    "font.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def czcionka(rozmiar):
    for sciezka in SCIEZKI_CZCIONEK:
        if os.path.exists(sciezka):
            return ImageFont.truetype(sciezka, rozmiar)
    return ImageFont.load_default(size=rozmiar)


def skroc(draw, tekst, font, max_szer):
    if draw.textlength(tekst, font=font) <= max_szer:
        return tekst
    while tekst and draw.textlength(tekst + "…", font=font) > max_szer:
        tekst = tekst[:-1]
    return tekst + "…"


def rysuj_karte(avatar_bytes, nazwa, ranga, xp, m_xp, prog_od, prog_do, miejsce, seria):
    W, H = 934, 282
    akcent = KOLOR_KARTY
    szary = (181, 186, 193)
    img = Image.new("RGB", (W, H), (30, 31, 34))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((16, 16, W - 16, H - 16), radius=24, fill=(43, 45, 49))
    d.rounded_rectangle((16, 16, 28, H - 16), radius=6, fill=akcent)

    # Okrągły avatar z obwódką
    rozm = 190
    ax, ay = 50, (H - rozm) // 2
    d.ellipse((ax - 6, ay - 6, ax + rozm + 6, ay + rozm + 6), fill=akcent)
    try:
        avatar = ImageOps.fit(Image.open(io.BytesIO(avatar_bytes)).convert("RGBA"), (rozm, rozm))
    except Exception:
        avatar = Image.new("RGBA", (rozm, rozm), (*akcent, 255))
    maska = Image.new("L", (rozm, rozm), 0)
    ImageDraw.Draw(maska).ellipse((0, 0, rozm, rozm), fill=255)
    img.paste(avatar, (ax, ay), maska)

    f_duza, f_srednia, f_mala = czcionka(40), czcionka(28), czcionka(22)
    x0 = ax + rozm + 40
    prawa = W - 50

    # Miejsce w rankingu
    tekst_miejsca = f"#{miejsce}"
    szer_m = d.textlength(tekst_miejsca, font=f_duza)
    d.text((prawa - szer_m, 42), tekst_miejsca, font=f_duza, fill=akcent)
    d.text((prawa - szer_m - d.textlength("MIEJSCE ", font=f_mala) - 4, 56), "MIEJSCE", font=f_mala, fill=szary)

    # Nazwa i ranga
    max_szer_nazwy = prawa - szer_m - 160 - x0
    d.text((x0, 40), skroc(d, nazwa, f_duza, max_szer_nazwy), font=f_duza, fill=(255, 255, 255))
    d.text((x0, 96), f"Ranga: {ranga}", font=f_srednia, fill=szary)

    # Pasek postępu
    by, bh = 160, 34
    d.rounded_rectangle((x0, by, prawa, by + bh), radius=bh // 2, fill=(30, 31, 34))
    if prog_do:
        postep = (xp - prog_od) / (prog_do - prog_od)
        napis_xp = f"{xp:,} / {prog_do:,} XP".replace(",", " ")
    else:
        postep = 1.0
        napis_xp = f"{xp:,} XP · MAX".replace(",", " ")
    postep = max(0.0, min(1.0, postep))
    if postep > 0:
        koniec = x0 + max(bh, int((prawa - x0) * postep))
        d.rounded_rectangle((x0, by, koniec, by + bh), radius=bh // 2, fill=akcent)
    d.text((prawa - d.textlength(napis_xp, font=f_mala), by - 32), napis_xp, font=f_mala, fill=(255, 255, 255))

    # Punkty miesięczne i seria daily
    dol = f"W tym miesiącu: {m_xp:,} pkt".replace(",", " ")
    if seria:
        dol += f"   |   Seria daily: {seria} dni"
    d.text((x0, by + bh + 18), dol, font=f_mala, fill=szary)

    bufor = io.BytesIO()
    img.save(bufor, "PNG")
    bufor.seek(0)
    return bufor


# ================= KOMENDY: PROFIL, RANKINGI, DAILY =================

MEDALE = {1: "🥇", 2: "🥈", 3: "🥉"}


def posortuj(dane, klucz):
    return sorted(tylko_uzytkownicy(dane).items(), key=lambda x: x[1].get(klucz, 0), reverse=True)


def dodaj_link_strony(embed, tekst="Pełny ranking online"):
    if STRONA:
        embed.set_footer(text=f"{tekst}: {STRONA.removeprefix('https://').removeprefix('http://').rstrip('/')}")
    return embed


def nazwa_uzytkownika(guild, user_id):
    member = guild.get_member(int(user_id))
    return member.mention if member else f"Nieznany (ID: {user_id})"


@bot.hybrid_command(description="Twoja karta rangi: XP, ranga i miejsce w rankingu")
@app_commands.describe(member="Czyj profil pokazać (domyślnie Twój)")
async def profil(ctx, member: discord.Member = None):
    await ctx.defer()
    member = member or ctx.author
    dane = wczytaj_baze()
    user_id = str(member.id)

    if user_id not in dane or user_id == "METADATA":
        kto = "nie masz" if member == ctx.author else f"{member.display_name} nie ma"
        await ctx.send(f"⚠️ {ctx.author.mention}, {kto} jeszcze punktów. Pisz na czacie lub wejdź na kanał głosowy!")
        return

    p = dane[user_id]
    xp = p.get("xp", 0)
    rola_id, prog_od, prog_do = info_rangi(xp)
    rola = ctx.guild.get_role(rola_id) if rola_id else None

    miejsce = next((i for i, (k, _) in enumerate(posortuj(dane, "xp"), start=1) if k == user_id), 0)

    # Seria liczy się tylko, jeśli nie została przerwana
    dzis = datetime.now(STREFA).date()
    aktywna = p.get("daily_last") in (dzis.isoformat(), (dzis - timedelta(days=1)).isoformat())
    seria = p.get("daily_streak", 0) if aktywna else 0

    async with ctx.typing():
        avatar_bytes = await member.display_avatar.replace(size=256, format="png").read()
        karta = await asyncio.to_thread(
            rysuj_karte, avatar_bytes, member.display_name, rola.name if rola else "Brak rangi",
            xp, p.get("monthly_xp", 0), prog_od, prog_do, miejsce, seria,
        )
    tresc = f"🌐 Twój profil online: <{STRONA.rstrip('/')}/u/{member.id}>" if STRONA else None
    await ctx.send(content=tresc, file=discord.File(karta, filename="karta.png"))


@bot.hybrid_command(aliases=["codzienny", "bonus"], description="Odbierz codzienny bonus XP")
async def daily(ctx):
    if bez_xp(ctx.author):
        await ctx.send("⚠️ Twoja rola nie zbiera XP, więc bonus dzienny Cię nie dotyczy.")
        return

    dane = wczytaj_baze()
    p = profil_uzytkownika(dane, ctx.author.id)
    teraz = datetime.now(STREFA)
    dzis = teraz.date()
    ostatni = p.get("daily_last")

    if ostatni == dzis.isoformat():
        polnoc = datetime.combine(dzis + timedelta(days=1), datetime.min.time(), tzinfo=STREFA)
        godz, reszta = divmod(int((polnoc - teraz).total_seconds()), 3600)
        await ctx.send(f"⏳ {ctx.author.mention}, bonus już odebrany! Kolejny za **{godz} h {reszta // 60} min**.")
        return

    wczoraj = (dzis - timedelta(days=1)).isoformat()
    seria = p.get("daily_streak", 0) + 1 if ostatni == wczoraj else 1
    nagroda = min(DAILY_BAZA + (seria - 1) * DAILY_ZA_DZIEN, DAILY_MAX)

    xp = dodaj_xp(dane, ctx.author.id, nagroda)
    p["daily_streak"] = seria
    p["daily_last"] = dzis.isoformat()
    zapisz_baze(dane)

    opis = f"Zgarniasz **+{nagroda} XP**!\n🔥 Seria: **{seria}** {'dzień' if seria == 1 else 'dni'} z rzędu."
    if seria == 1 and ostatni and ostatni != wczoraj:
        opis += "\n*(Seria przerwana – wracaj codziennie, żeby nagroda rosła!)*"
    elif nagroda < DAILY_MAX:
        opis += f"\nJutro: **+{min(nagroda + DAILY_ZA_DZIEN, DAILY_MAX)} XP**."
    else:
        opis += "\nMasz już maksymalną nagrodę dzienną! 💪"

    await ctx.send(embed=discord.Embed(title="🎁 Codzienny bonus", description=opis, color=discord.Color.gold()))
    await sprawdz_range(ctx.author, xp)


@bot.hybrid_command(description="Liderzy rankingu miesięcznego – wyścig o VIP")
async def viptop(ctx):
    posortowani = posortuj(wczytaj_baze(), "monthly_xp")
    if not posortowani:
        await ctx.send("Brak danych o aktywności w tym miesiącu.")
        return

    opis = "Osoba z pierwszego miejsca zdobędzie rangę VIP 1. dnia miesiąca!\n\n"
    for miejsce, (u_id, info) in enumerate(posortowani[:3], start=1):
        opis += f"{MEDALE[miejsce]} {nazwa_uzytkownika(ctx.guild, u_id)} - **{info.get('monthly_xp', 0)} pkt**\n"
    await ctx.send(embed=dodaj_link_strony(discord.Embed(title="👑 Wyścig o VIP", description=opis, color=discord.Color.dark_theme()), "Ranking miesięczny online"))


@bot.hybrid_command(description="Podium – top 3 w rankingu ogólnym")
async def top(ctx):
    posortowani = posortuj(wczytaj_baze(), "xp")
    if not posortowani:
        await ctx.send("Brak danych o aktywności.")
        return

    opis = ""
    for miejsce, (u_id, info) in enumerate(posortowani[:3], start=1):
        opis += f"{MEDALE[miejsce]} {nazwa_uzytkownika(ctx.guild, u_id)} - **{info.get('xp', 0)} XP**\n\n"
    await ctx.send(embed=dodaj_link_strony(discord.Embed(title="🏆 Podium (ogólne)", description=opis, color=discord.Color.gold())))


@bot.hybrid_command(description="Pełny ranking XP serwera")
async def ranking(ctx):
    posortowani = posortuj(wczytaj_baze(), "xp")
    if not posortowani:
        await ctx.send("Brak danych o aktywności.")
        return

    opis = ""
    for miejsce, (u_id, info) in enumerate(posortowani, start=1):
        linijka = f"**{miejsce}.** {nazwa_uzytkownika(ctx.guild, u_id)} - **{info.get('xp', 0)} XP**\n"
        if len(opis) + len(linijka) > 4000:  # limit opisu embeda to 4096 znaków
            opis += "\n*...i pozostali*"
            break
        opis += linijka
    await ctx.send(embed=dodaj_link_strony(discord.Embed(title="📋 Pełny ranking", description=opis, color=discord.Color.blue())))


@bot.command()
@commands.has_permissions(administrator=True)
async def usunxp(ctx, member: discord.Member):
    dane = wczytaj_baze()
    user_id = str(member.id)
    if user_id not in dane or user_id == "METADATA":
        await ctx.send(f"⚠️ {member.mention} nie ma jeszcze XP.")
        return

    del dane[user_id]
    zapisz_baze(dane)
    role_rang = [r for r in (ctx.guild.get_role(i) for i in RANGI.values()) if r and r in member.roles]
    if role_rang:
        await member.remove_roles(*role_rang)
    await ctx.send(f"✅ Wyzerowano XP i rangi użytkownika {member.mention}.")


# ================= KOMENDY: ADMINISTRACJA =================

@bot.hybrid_command(description="Sprawdź opóźnienie bota")
async def ping(ctx):
    await ctx.send(f"Pong! Opóźnienie: {round(bot.latency * 1000)} ms")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def wyczysc(ctx, ilosc: int):
    ilosc = max(1, min(ilosc, 200))
    usuniete = await ctx.channel.purge(limit=ilosc + 1)
    await ctx.send(f"🧹 Usunięto {len(usuniete) - 1} wiadomości.", delete_after=4)


# Ręczne ogłoszenia na wypadek, gdyby automat czegoś nie wyłapał
@bot.command()
@commands.has_permissions(administrator=True)
async def nowyfilm(ctx, link: str):
    await ctx.message.delete()
    await ogloszenie_film(kanal_ogloszen(ctx.channel), link)


@bot.command()
@commands.has_permissions(administrator=True)
async def live(ctx, link: str):
    await ctx.message.delete()
    await ogloszenie_live(kanal_ogloszen(ctx.channel), link)


@tasks.loop(hours=2)
async def przypomnienie_bump():
    kanal = bot.get_channel(ID_KANALU_BUMP)
    if kanal:
        embed = discord.Embed(
            title="⏰ Czas na bump!",
            description="Wpisz `/bump`, aby podbić serwer w rankingu Disboard.",
            color=discord.Color.teal(),
        )
        await kanal.send("@here", embed=embed)


@przypomnienie_bump.before_loop
async def przed_przypomnieniem():
    await bot.wait_until_ready()
    await asyncio.sleep(7200)


@bot.command()
@commands.has_permissions(administrator=True)
async def ustaw_bump(ctx):
    przypomnienie_bump.restart()
    await ctx.message.delete()
    await ctx.send("✅ Odliczanie zresetowane – przypomnienie za 2 godziny.", delete_after=5)


@tasks.loop(hours=24)
async def codzienny_mem():
    kanal = bot.get_channel(ID_KANALU_MEMY)
    if not kanal:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://meme-api.com/gimme/{SUBREDDIT_MEMOW}") as r:
                if r.status != 200:
                    return
                dane = await r.json()
        # Tytuł embeda może mieć maksymalnie 256 znaków
        embed = discord.Embed(title=f"🤣 Mem dnia: {dane['title'][:230]}", color=discord.Color.gold())
        embed.set_image(url=dane["url"])
        await kanal.send(embed=embed)
    except Exception as e:
        print(f"[Mem] Błąd: {e}")


@codzienny_mem.before_loop
async def przed_memem():
    await bot.wait_until_ready()


# ================= TICKETY =================

def czy_ticket(kanal):
    return isinstance(kanal, discord.TextChannel) and (kanal.topic or "").startswith("ticket:")


def wlasciciel_ticketu(kanal):
    try:
        return int(kanal.topic.split(":")[1].split()[0])
    except (AttributeError, IndexError, ValueError):
        return None


class PanelTicketow(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Otwórz ticket", emoji="🎫", style=discord.ButtonStyle.primary,
                       custom_id=f"{PREFIKS_TICKETOW}:ticket_otworz")
    async def otworz(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        for kanal in guild.text_channels:
            if czy_ticket(kanal) and wlasciciel_ticketu(kanal) == user.id:
                await interaction.response.send_message(f"Masz już otwarty ticket: {kanal.mention}", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        dostep = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                             attach_files=True, read_message_history=True)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: dostep,
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                  read_message_history=True, manage_channels=True),
        }
        role_support = [r for r in (guild.get_role(i) for i in ID_ROLI_SUPPORT) if r]
        for rola in role_support:
            overwrites[rola] = dostep

        dane = wczytaj_baze()
        m = meta(dane)
        numer = m.get("ticket_licznik", 0) + 1
        m["ticket_licznik"] = numer
        zapisz_baze(dane)

        kategoria = guild.get_channel(ID_KATEGORII_TICKETOW)
        kanal = await guild.create_text_channel(
            name=f"ticket-{numer:04d}",
            category=kategoria if isinstance(kategoria, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"ticket:{user.id} | Zgłoszenie od {user}",
        )

        embed = discord.Embed(
            title=f"🎫 Ticket #{numer:04d}",
            description=(
                f"Cześć {user.mention}! Opisz dokładnie, w czym możemy pomóc.\n"
                "Administracja odpowie najszybciej, jak się da.\n\n"
                "Gdy sprawa będzie załatwiona, kliknij **Zamknij ticket**."
            ),
            color=discord.Color.blurple(),
        )
        oznaczenia = " ".join([user.mention] + [r.mention for r in role_support])
        await kanal.send(content=oznaczenia, embed=embed, view=ZamknijTicket())
        await interaction.followup.send(f"✅ Ticket utworzony: {kanal.mention}", ephemeral=True)

        log = discord.Embed(title="🎫 Otwarto ticket", color=discord.Color.blurple())
        log.add_field(name="Użytkownik", value=user.mention, inline=True)
        log.add_field(name="Kanał", value=kanal.mention, inline=True)
        await wyslij_log(log)


class ZamknijTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Zamknij ticket", emoji="🔒", style=discord.ButtonStyle.danger,
                       custom_id=f"{PREFIKS_TICKETOW}:ticket_zamknij")
    async def zamknij(self, interaction: discord.Interaction, button: discord.ui.Button):
        kanal = interaction.channel
        if not czy_ticket(kanal):
            await interaction.response.send_message("To nie jest kanał ticketu.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"🔒 Ticket zamknięty przez {interaction.user.mention}. Kanał zniknie za 5 sekund..."
        )

        # Transkrypt rozmowy jako plik .txt na kanale logów
        linie = []
        async for msg in kanal.history(limit=None, oldest_first=True):
            czas = msg.created_at.astimezone(STREFA).strftime("%Y-%m-%d %H:%M")
            tresc = msg.content or ""
            tresc += "".join(f" [załącznik: {z.url}]" for z in msg.attachments)
            tresc += "".join(f" [embed: {e.description}]" for e in msg.embeds if e.description)
            linie.append(f"[{czas}] {msg.author}: {tresc}")
        transkrypt = discord.File(io.BytesIO("\n".join(linie).encode("utf-8")), filename=f"{kanal.name}.txt")

        wlasciciel_id = wlasciciel_ticketu(kanal)
        log = discord.Embed(title="🔒 Zamknięto ticket", color=discord.Color.dark_gray())
        log.add_field(name="Ticket", value=kanal.name, inline=True)
        log.add_field(name="Zgłaszający", value=f"<@{wlasciciel_id}>" if wlasciciel_id else "?", inline=True)
        log.add_field(name="Zamknął", value=interaction.user.mention, inline=True)
        await wyslij_log(log, file=transkrypt)

        await asyncio.sleep(5)
        try:
            await kanal.delete(reason=f"Ticket zamknięty przez {interaction.user}")
        except discord.NotFound:
            pass


@bot.command()
@commands.has_permissions(administrator=True)
async def ticketpanel(ctx):
    """Wysyła panel z przyciskiem do otwierania ticketów."""
    await ctx.message.delete()
    embed = discord.Embed(
        title="🎫 Potrzebujesz pomocy?",
        description=(
            "Masz problem, pytanie do administracji albo chcesz kogoś zgłosić?\n\n"
            "Kliknij przycisk poniżej – utworzy się prywatny kanał widoczny tylko dla Ciebie i administracji."
        ),
        color=0x2B2D31,
    )
    await ctx.send(embed=embed, view=PanelTicketow())


@bot.hybrid_command(description="Dodaj osobę do ticketu (użyj na kanale ticketu)")
@app_commands.describe(member="Kogo dodać do ticketu")
async def dodaj(ctx, member: discord.Member):
    """Dodaje osobę do ticketu (użyj na kanale ticketu)."""
    if not czy_ticket(ctx.channel):
        await ctx.send("Tej komendy używa się na kanale ticketu.", delete_after=5)
        return
    if not (ctx.author.guild_permissions.manage_channels or wlasciciel_ticketu(ctx.channel) == ctx.author.id):
        await ctx.send("⛔ Tylko autor ticketu lub administracja może dodawać osoby.", delete_after=5)
        return
    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True,
                                      attach_files=True, read_message_history=True)
    await ctx.send(f"✅ Dodano {member.mention} do ticketu.")


# ================= MUZYKA =================

YTDL_OPCJE = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "scsearch",
    "source_address": "0.0.0.0",
}
FFMPEG_OPCJE = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

kolejki = {}    # guild_id -> lista utworów
teraz_gra = {}  # guild_id -> aktualny utwór
glosnosc = {}   # guild_id -> 0.0-1.0


class Utwor:
    def __init__(self, tytul, link, czas, zamawiajacy, kanal):
        self.tytul = tytul
        self.link = link
        self.czas = czas
        self.zamawiajacy = zamawiajacy
        self.kanal = kanal


def format_czasu(sekundy):
    if not sekundy:
        return "na żywo"
    g, reszta = divmod(int(sekundy), 3600)
    m, s = divmod(reszta, 60)
    return f"{g}:{m:02d}:{s:02d}" if g else f"{m}:{s:02d}"


def wyczysc_muzyke(guild_id):
    kolejki.pop(guild_id, None)
    teraz_gra.pop(guild_id, None)


async def wyszukaj(zapytanie):
    def _pobierz():
        with yt_dlp.YoutubeDL(YTDL_OPCJE) as ydl:
            info = ydl.extract_info(zapytanie, download=False)
            if info and "entries" in info:
                wpisy = [e for e in info["entries"] if e]
                info = wpisy[0] if wpisy else None
            return info
    return await asyncio.to_thread(_pobierz)


async def graj_nastepny(guild):
    vc = guild.voice_client
    kolejka = kolejki.get(guild.id, [])
    if not vc or not vc.is_connected() or not kolejka:
        teraz_gra.pop(guild.id, None)
        return
    if vc.is_playing() or vc.is_paused():
        return

    utwor = kolejka.pop(0)
    try:
        # Link do strumienia pobieramy dopiero przed odtworzeniem, bo po czasie wygasa
        info = await wyszukaj(utwor.link)
        if not info:
            raise ValueError("brak wyników")
    except Exception as e:
        await utwor.kanal.send(f"⚠️ Nie udało się odtworzyć **{utwor.tytul}** ({e}). Pomijam.")
        await graj_nastepny(guild)
        return

    if vc.is_playing() or vc.is_paused():
        kolejka.insert(0, utwor)
        return

    zrodlo = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(info["url"], **FFMPEG_OPCJE),
        volume=glosnosc.get(guild.id, 0.5),
    )
    teraz_gra[guild.id] = utwor

    def po_utworze(blad):
        if blad:
            print(f"[Muzyka] Błąd odtwarzania: {blad}")
        asyncio.run_coroutine_threadsafe(graj_nastepny(guild), bot.loop)

    vc.play(zrodlo, after=po_utworze)

    embed = discord.Embed(title="🎵 Teraz gra", description=f"[{utwor.tytul}]({utwor.link})", color=discord.Color.green())
    embed.add_field(name="Długość", value=format_czasu(utwor.czas), inline=True)
    embed.add_field(name="Zamówił(a)", value=utwor.zamawiajacy.mention, inline=True)
    if info.get("thumbnail"):
        embed.set_thumbnail(url=info["thumbnail"])
    await utwor.kanal.send(embed=embed)


async def sprawdz_kanal_muzyki(ctx):
    vc = ctx.voice_client
    if not vc:
        await ctx.send("🔇 Nic teraz nie gram.")
        return None
    if not ctx.author.voice or ctx.author.voice.channel != vc.channel:
        await ctx.send("⚠️ Musisz być na tym samym kanale głosowym co bot.")
        return None
    return vc


@bot.hybrid_command(name="graj", aliases=["play", "p"], description="Zagraj muzykę na kanale głosowym")
@app_commands.describe(zapytanie="Tytuł utworu albo link")
async def graj(ctx, *, zapytanie: str):
    await ctx.defer()
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("⚠️ Najpierw wejdź na kanał głosowy.")
        return

    kanal_glosowy = ctx.author.voice.channel
    vc = ctx.voice_client
    if vc is None:
        vc = await kanal_glosowy.connect(self_deaf=True)
    elif vc.channel != kanal_glosowy:
        if vc.is_playing() or vc.is_paused():
            await ctx.send(f"⚠️ Gram już na kanale **{vc.channel.name}**.")
            return
        await vc.move_to(kanal_glosowy)

    async with ctx.typing():
        try:
            info = await wyszukaj(zapytanie)
        except Exception:
            info = None
    if not info:
        await ctx.send("❌ Nic nie znalazłem. Spróbuj innego tytułu albo linku.")
        return

    utwor = Utwor(
        tytul=info.get("title", "Nieznany utwór"),
        link=info.get("webpage_url") or zapytanie,
        czas=info.get("duration"),
        zamawiajacy=ctx.author,
        kanal=ctx.channel,
    )
    kolejka = kolejki.setdefault(ctx.guild.id, [])
    kolejka.append(utwor)

    if vc.is_playing() or vc.is_paused() or ctx.guild.id in teraz_gra:
        await ctx.send(f"➕ Dodano do kolejki (**#{len(kolejka)}**): **{utwor.tytul}** [{format_czasu(utwor.czas)}]")
    else:
        await graj_nastepny(ctx.guild)


@bot.hybrid_command(aliases=["skip", "s"], description="Pomiń aktualny utwór")
async def pomin(ctx):
    vc = await sprawdz_kanal_muzyki(ctx)
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()  # callback po_utworze uruchomi następny utwór
        await potwierdz(ctx, "⏭️", "Pominięto utwór.")
    elif vc:
        await ctx.send("🔇 Teraz nic nie gra (albo nie ma czego wznowić).", ephemeral=True)


@bot.hybrid_command(aliases=["pause"], description="Wstrzymaj muzykę")
async def pauza(ctx):
    vc = await sprawdz_kanal_muzyki(ctx)
    if vc and vc.is_playing():
        vc.pause()
        await potwierdz(ctx, "⏸️", "Wstrzymano muzykę.")
    elif vc:
        await ctx.send("🔇 Teraz nic nie gra (albo nie ma czego wznowić).", ephemeral=True)


@bot.hybrid_command(aliases=["resume"], description="Wznów muzykę")
async def wznow(ctx):
    vc = await sprawdz_kanal_muzyki(ctx)
    if vc and vc.is_paused():
        vc.resume()
        await potwierdz(ctx, "▶️", "Wznowiono muzykę.")
    elif vc:
        await ctx.send("🔇 Teraz nic nie gra (albo nie ma czego wznowić).", ephemeral=True)


@bot.hybrid_command(aliases=["stop", "leave"], description="Zatrzymaj muzykę i wyrzuć bota z kanału")
async def wyjdz(ctx):
    vc = await sprawdz_kanal_muzyki(ctx)
    if vc:
        wyczysc_muzyke(ctx.guild.id)
        vc.stop()
        await vc.disconnect()
        await potwierdz(ctx, "👋", "Do usłyszenia!")


@bot.hybrid_command(name="kolejka", aliases=["queue", "q"], description="Pokaż kolejkę utworów")
async def kolejka_cmd(ctx):
    obecny = teraz_gra.get(ctx.guild.id)
    lista = kolejki.get(ctx.guild.id, [])
    if not obecny and not lista:
        await ctx.send(f"📭 Kolejka jest pusta. Dodaj coś przez `{ctx.prefix}graj <tytuł lub link>`.")
        return
    opis = ""
    if obecny:
        opis += f"🎵 **Teraz:** [{obecny.tytul}]({obecny.link}) [{format_czasu(obecny.czas)}]\n\n"
    for i, u in enumerate(lista[:10], start=1):
        opis += f"**{i}.** {u.tytul} [{format_czasu(u.czas)}] – {u.zamawiajacy.display_name}\n"
    if len(lista) > 10:
        opis += f"\n*...i jeszcze {len(lista) - 10}*"
    await ctx.send(embed=discord.Embed(title="📜 Kolejka", description=opis, color=discord.Color.green()))


@bot.hybrid_command(name="glosnosc", aliases=["volume", "vol"], description="Ustaw głośność muzyki (0–100)")
@app_commands.describe(procent="Głośność w procentach")
async def glosnosc_cmd(ctx, procent: app_commands.Range[int, 0, 100]):
    vc = await sprawdz_kanal_muzyki(ctx)
    if not vc:
        return
    procent = max(0, min(procent, 100))
    glosnosc[ctx.guild.id] = procent / 100
    if isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = procent / 100
    await ctx.send(f"🔊 Głośność: **{procent}%**")


# ================= AKTUALIZACJE =================

@bot.command()
@commands.has_permissions(administrator=True)
async def aktualizacja(ctx, *, tresc: str):
    """Ogłasza aktualizację serwera/bota na kanale ogłoszeń i pinguje rolę Aktualizacje."""
    await ctx.message.delete()
    kanal = kanal_ogloszen(ctx.channel)
    embed = discord.Embed(title="🆕 Aktualizacja", description=tresc, color=discord.Color.blurple(),
                          timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"Ogłosił(a): {ctx.author.display_name}")
    ping = f"<@&{ID_ROLI_AKTUALIZACJE}>" if ID_ROLI_AKTUALIZACJE else None
    await kanal.send(content=ping, embed=embed,
                     allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False))
    if kanal != ctx.channel:
        await ctx.send(f"✅ Ogłoszono na {kanal.mention}", delete_after=5)


# ================= REGULAMIN =================

@bot.command()
@commands.has_permissions(administrator=True)
async def reg(ctx):
    await ctx.message.delete()
    p = ctx.prefix
    embed = discord.Embed(
        title="📜 Regulamin i informacje",
        description=(
            "🤝 **Szacunek** – zero wyzwisk, hejtu i toksycznego zachowania.\n\n"
            "🛑 **Zakaz spamu** – nie pinguj bez potrzeby (@everyone, @here) i nie powtarzaj wiadomości.\n\n"
            "💬 **Kanały** – trzymaj się tematu danego kanału.\n\n"
            "🔞 **Zero NSFW** – zakaz treści 18+ i drastycznych.\n\n"
            "🚫 **Brak reklam** – nie wysyłaj zaproszeń na inne serwery na czacie ani w DM.\n\n"
            "👑 **Administracja** – decyzje administracji i moderacji są ostateczne.\n\n"
            "🤖 **Bot i komendy:**\n"
            "📈 **Rangi** – XP za pisanie i rozmowy na kanałach głosowych, bot sam nadaje wyższe rangi.\n"
            "🌟 **VIP** – 1. dnia miesiąca najaktywniejsza osoba z poprzedniego miesiąca dostaje rangę VIP.\n"
            f"👤 **{p}profil** – karta rangi: XP, ranga, miejsce w rankingu.\n"
            f"🎁 **{p}daily** – codzienny bonus XP, rosnący z serią.\n"
            f"👑 **{p}viptop** – liderzy bieżącego miesiąca.\n"
            f"🏆 **{p}top** i **{p}ranking** – ranking ogólny.\n"
            f"🎵 **{p}graj <tytuł/link>** – muzyka ({p}pomin, {p}pauza, {p}wznow, {p}kolejka, {p}glosnosc, {p}wyjdz).\n"
            "🎫 **Tickety** – kontakt z administracją przez kanał pomocy."
            + (f"\n🤖 Komend bota używaj na <#{ID_KANALU_KOMEND}>." if ID_KANALU_KOMEND else "")
            + (f"\n🌐 **Ranking online:** {STRONA}" if STRONA else "")
        ),
        color=0x2B2D31,
    )
    embed.set_footer(text="Dołączenie do serwera oznacza akceptację regulaminu.")
    await ctx.send(embed=embed)


if __name__ == "__main__":
    if not TOKEN_BOTA:
        raise SystemExit("Brak tokena! Ustaw DISCORD_TOKEN w pliku .env")
    bot.run(TOKEN_BOTA)
