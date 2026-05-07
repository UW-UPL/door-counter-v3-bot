import asyncio
import json
import logging
import os
import random
from pathlib import Path

import discord
from discord import app_commands
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

SERVICE_DOWN_MESSAGE = (
    "Looks like the door counter script isn't running right now. "
    "Poke someone to restart it!"
)

EMPTY_ROOM_MESSAGES = [
    "Looks like no one is in the UPL... check back later!",
    "The UPL is looking empty right now... try again later!",
    "No signs of life in the UPL at the moment... check back soon!",
]

VERBS = [
    "programming",
    "coding",
    "working",
    "studying",
    "larping",
    "toiling",
    "hobnobbing",
]

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

    verb = random.choice(VERBS)
    formatted_names = format_names(names)

    if formatted_names:
        return (
            f"Looks like there are ~{count} people {verb} in the UPL "
            f"including: {formatted_names}"
        )
    return f"Looks like there are ~{count} people {verb} in the UPL!"


@bot.event
async def on_ready():
    logger.info("Logged in as %s", bot.user)


@bot.tree.command(name="who", description="See who and how many ppl are currently in the UPL room.")
async def who(interaction: discord.Interaction):
    try:
        if not await is_counter_service_active():
            await interaction.response.send_message(SERVICE_DOWN_MESSAGE, ephemeral=True)
            return

        data = read_count_json()
        message = format_people_message(data)

        await interaction.response.send_message(message)

    except json.JSONDecodeError:
        logger.exception("Failed to parse count JSON")

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


bot.run(DISCORD_TOKEN)