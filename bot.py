import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("door-counter-bot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
COUNT_JSON_PATH = os.getenv(
    "COUNT_JSON_PATH",
    "/home/upl/door-counter-v3/data/count.json",
)
COUNTER_SERVICE = os.getenv("COUNTER_SERVICE", "door-counter.service")
WHO_JSON_URL = os.getenv(
    "WHO_JSON_URL",
    "https://raw.githubusercontent.com/UW-UPL/History/master/who/who.json",
)
SPIRIT_COUNT = 15
SPIRIT_CACHE_PATH = os.getenv(
    "SPIRIT_CACHE_PATH",
    str(Path(__file__).with_name("spirits.json")),
)
SPIRIT_REFRESH_SECONDS = 12 * 60 * 60

SERVICE_DOWN_MESSAGE = (
    "Looks like the door counter script isn't running right now. "
    "Poke someone to restart it!"
)

EMPTY_ROOM_MESSAGES = [
    "Looks like no one is in the UPL... check back later!",
    "The UPL is looking empty right now... try again later!",
    "No signs of life in the UPL at the moment... check back soon!",
]

# no coord is scheduled and the upl is closed
NO_COORD_CLOSED_MESSAGE = (
    "Unfortunatly, the UPL is closed and no coords are scheduled right now. :("
)

# no coord is scheduled, but the upl is open
NO_COORD_OPEN_MESSAGE = (
    "No coord is currently scheduled, but the UPL is open! :D"
)

# coord scheduled, not open
COORD_CLOSED_MESSAGE = (
    "Looks like {coord_name} is scheduled, but not in their office hours... check back later!"
)

# coord scheduled, open
COORD_OPEN_MESSAGE = (
    "{coord_name} is currently scheduled, and the UPL is open!"
)

# feel free to add more lol
VERBS = [
    "programming",
    "coding",
    "working",
    "studying",
    "larping",
    "toiling",
    "hobnobbing",
    "thinking about infra",
]

SOLO_VERBS = [
    "feeling lonely",
    "flying solo",
    "fighting their demons",
    "being a sigma lone wolf",
]

DUO_VERBS = [
    "pair-programming",
]

CROWDED_VERBS = [
    "packing the place",
    "throwing a party",
]

DAYS = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}

SPIRITS = []
_last_spirit_refresh = None

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

if not GUILD_ID:
    raise RuntimeError("Missing GUILD_ID in .env")

class PeopleCounterBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        guild = discord.Object(id=int(GUILD_ID))
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Synced slash commands to guild %s", GUILD_ID)
        update_presence_loop.start()
        load_spirit_cache()
        refresh_spirits_loop.start()


bot = PeopleCounterBot()

async def is_counter_service_active():
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", "--quiet", COUNTER_SERVICE,
        )
        return await proc.wait() == 0
    except FileNotFoundError:
        logger.exception("systemctl not available; cannot check service state")
        return True


def read_count_json():
    path = Path(COUNT_JSON_PATH)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def format_names(names):
    cleaned_names = [str(name).strip() for name in names if str(name).strip()]
    if len(cleaned_names) == 0:
        return ""
    if len(cleaned_names) == 1:
        return cleaned_names[0]
    if len(cleaned_names) == 2:
        return f"{cleaned_names[0]} and {cleaned_names[1]}"

    return f"{', '.join(cleaned_names[:-1])} and {cleaned_names[-1]}"


def format_people_message(data):
    count = data.get("count", 0)
    names = data.get("names", [])
    if not isinstance(count, int):
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0

    if not isinstance(names, list):
        names = []
        
    if count <= 0:
        return random.choice(EMPTY_ROOM_MESSAGES)

    cleaned_names = [str(name).strip() for name in names if str(name).strip()]
    cleaned_names = [
        "Mowgli"
        if name.replace(" ", "").lower() in ("lucas", "lucas2") and random.random() < 1 / 15
        else name
        for name in cleaned_names
    ]
    formatted_names = format_names(cleaned_names)
    all_named = len(cleaned_names) == count

    spirit = ""
    if len(cleaned_names) < count and random.random() < 1 / 20:
        present = {name.split()[0].lower() for name in cleaned_names}
        departed = [name for name in SPIRITS if name.split()[0].lower() not in present]
        if departed:
            ghost = discord.utils.escape_markdown(random.choice(departed))
            if cleaned_names:
                formatted_names = format_names(cleaned_names + [f"*the spirit of {ghost}* 👻"])
            else:
                spirit = f"\n*as well as the spirit of {ghost}* 👻"

    if count == 1:
        verb = random.choice(SOLO_VERBS)
        subject = formatted_names if formatted_names else "1 person"
        return f"Looks like {subject} is in the UPL *{verb}*{spirit or '.'}"

    if count == 2 and all_named:
        verb = random.choice(DUO_VERBS)
        return f"Looks like {formatted_names} are in the UPL *{verb}*."

    if count >= 10:
        verb = random.choice(CROWDED_VERBS)
    else:
        verb = random.choice(VERBS)

    if formatted_names:
        return (
            f"Looks like there are ~{count} people *{verb}* in the UPL "
            f"including: {formatted_names}"
        )
    return f"Looks like there are ~{count} people *{verb}* in the UPL{spirit or '!'}"


async def get_presence_text():
    if not await is_counter_service_active():
        return "offline"
    try:
        data = read_count_json()
    except Exception:
        logger.exception("Failed to read count JSON for presence")
        return "offline"

    count = data.get("count", 0)
    if not isinstance(count, int):
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0

    if count <= 0:
        return "empty"
    return f"~{count} people"


def load_spirit_cache():
    try:
        with Path(SPIRIT_CACHE_PATH).open("r", encoding="utf-8") as file:
            cached = json.load(file)
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("Could not read %s", SPIRIT_CACHE_PATH)
        return

    if isinstance(cached, list):
        names = [str(name).strip() for name in cached if str(name).strip()]
        if names:
            SPIRITS[:] = names[-SPIRIT_COUNT:]
            logger.info("Loaded %s past members from cache", len(SPIRITS))


def save_spirit_cache(names):
    path = Path(SPIRIT_CACHE_PATH)
    temporary_path = path.with_suffix(".json.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(names, file, indent=2)
        temporary_path.replace(path)
    except Exception:
        logger.exception("Could not write %s", SPIRIT_CACHE_PATH)


async def fetch_spirit_names():
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(WHO_JSON_URL) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
    except Exception:
        logger.exception("Failed to fetch %s", WHO_JSON_URL)
        return []

    entries = data.get("who") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        logger.warning("%s did not contain a member list", WHO_JSON_URL)
        return []

    names = [
        str(entry.get("name", "")).strip()
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("name", "")).strip()
    ]
    if len(names) < SPIRIT_COUNT:
        logger.warning("Only %s usable names in who.json; keeping current list", len(names))
        return []

    return names[-SPIRIT_COUNT:]

def get_schedule():
    with open("/data/schedule.json", "r") as file:
        office_hours = json.load(file)

    return office_hours

async def get_current_person():
    office_hours = get_schedule()

    now = datetime.now(ZoneInfo("America/Chicago"))

    for slot in office_hours:
        slot_day = DAYS[slot["day"]]

        if now.weekday() != slot_day:
            continue

        start_time = datetime.strptime(slot["start"], "%H:%M").replace(
            tzinfo=now.tzinfo
        ).time()
        end_time = datetime.strptime(slot["end"], "%H:%M").replace(
            tzinfo=now.tzinfo
        ).time()

        if start_time <= now.time() < end_time:
            return {
                "status": "current",
                "person": slot["person"],
                "time": slot["start"]
            }

    next_slot = None
    next_datetime = None

    for slot in office_hours:
        slot_day = DAYS[slot["day"]]
        start_time = datetime.strptime(slot["start"], "%H:%M").replace(
            tzinfo=now.tzinfo
        ).time()

        days_ahead = (slot_day - now.weekday()) % 7

        slot_datetime = datetime.combine(
            now.date() + timedelta(days=days_ahead),
            start_time,
            tzinfo=now.tzinfo
        )

        if slot_datetime <= now:
            slot_datetime += timedelta(days=7)

        if next_datetime is None or slot_datetime < next_datetime:
            next_datetime = slot_datetime
            next_slot = slot

    if next_slot:
        return {
            "status": "next",
            "person": next_slot["person"],
            "datetime": next_datetime
        }

    return None

async def get_door_status():
    url = "https://doors.amoses.dev/door-status"
    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
    except asyncio.TimeoutError:
        logger.warning("Timed out fetching door status from %s", url)
    except aiohttp.ClientError:
        logger.exception("Failed to fetch door status from %s", url)
    except (json.JSONDecodeError, TypeError):
        logger.exception("Door status response from %s was not valid JSON", url)

    return -1

async def format_coord_message(person):
    t = 0

    # see if person returns something

    # see if upl is open

@tasks.loop(minutes=30)
async def refresh_spirits_loop():
    global _last_spirit_refresh
    if _last_spirit_refresh is not None:
        if time.monotonic() - _last_spirit_refresh < SPIRIT_REFRESH_SECONDS:
            return

    names = await fetch_spirit_names()
    if names:
        SPIRITS[:] = names
        _last_spirit_refresh = time.monotonic()
        save_spirit_cache(names)
        logger.info("Loaded %s past members from who.json", len(SPIRITS))


@tasks.loop(minutes=1)
async def update_presence_loop():
    text = await get_presence_text()
    try:
        await bot.change_presence(activity=discord.CustomActivity(name=text))
    except Exception:
        logger.exception("Failed to update presence")


@update_presence_loop.before_loop
async def _before_update_presence():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    logger.info("Logged in as %s", bot.user)


@bot.tree.command(name="who", description="See who and how many ppl are currently in the UPL room.")
async def who(interaction: discord.Interaction):
    try:
        if not await is_counter_service_active():
            await interaction.response.send_message(SERVICE_DOWN_MESSAGE)
            return

        data = read_count_json()
        message = format_people_message(data)

        await interaction.response.send_message(
            message,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    except json.JSONDecodeError:
        logger.exception("Failed to parse count JSON")
        # all should be ephermeral for now
        await interaction.response.send_message(
            "The people counter is updating right now. Try again in a second.",
            ephemeral=True,
        )

    except FileNotFoundError:
        logger.exception("Count JSON file was not found")

        await interaction.response.send_message(
            "I could not read the people counter right now. Please try again later.",
            ephemeral=True,
        )

    except PermissionError:
        logger.exception("Bot does not have permission to read count JSON")

        await interaction.response.send_message(
            "I could not read the people counter right now. Please try again later.",
            ephemeral=True,
        )

    except Exception:
        logger.exception("Unexpected error while reading people counter")

        await interaction.response.send_message(
            "Something went wrong while checking the people counter. Please try again later.",
            ephemeral=True,
        )

@bot.tree.command(name="coord", description="See which Coord has office hours currently.")
async def coord(interaction: discord.Integration):
    try:
        if not await is_counter_service_active():
            await interaction.response.send_message(SERVICE_DOWN_MESSAGE)
            return

        data = get_current_person()
        message = format_coord_message(data)

        await interaction.response.send_message(
            message
        )

    except json.JSONDecodeError:
            logger.exception("Failed to parse count JSON")
            # all should be ephermeral for now
            await interaction.response.send_message(
                "I could not read the coord schedule right now. Try again in a second.",
                ephemeral=True,
            )
    
    except FileNotFoundError:
        logger.exception("Count JSON file was not found")

        await interaction.response.send_message(
            "I could not read the coord schedule right now. Please try again later.",
            ephemeral=True,
        )

    except PermissionError:
        logger.exception("Bot does not have permission to read count JSON")

        await interaction.response.send_message(
            "I could not read the coord schedule right now. Please try again later.",
            ephemeral=True,
        )

    except Exception:
        logger.exception("Unexpected error while reading people counter")

        await interaction.response.send_message(
            "Something went wrong while checking the coord schedule. Please try again later.",
            ephemeral=True,
        )


bot.run(DISCORD_TOKEN)
