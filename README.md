<p align="center">
  <img src="docs/logo.jpg" alt="The Detective" width="230">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/discord-%2Fwho-5865F2?logo=discord&logoColor=white">
  <img src="https://img.shields.io/badge/discord.py-python-3776ab">
  <a href="https://github.com/UW-UPL/door-counter-v3"><img src="https://img.shields.io/badge/sensor-door--counter--v3-c51a4a"></a>
</p>

The Discord half of [Door Counter v3](https://github.com/UW-UPL/door-counter-v3). The sensor above the UPL door keeps `count.json` up to date, this bot reads it and tells the server.

**`/who`** tells you who and how many people are in the UPL right now. Responses come with a randomized activity: people may be *programming*, *toiling*, *hobnobbing*, or if it's just one person, *being a sigma lone wolf*. The verb lists are at the top of `bot.py`, feel free to add more lol.

The bot also sets its Discord status to the live count every minute (~N people / empty / offline), so most of the time you don't even have to ask. If the counter service dies, `/who` says so and tells you to poke someone.

## Running it

Lives on the same Pi as the counter. It reads `count.json` straight off disk and checks the systemd service before answering.

```bash
pip install -r requirements.txt
python bot.py
```

With a `.env`:

```
DISCORD_TOKEN=your bot token
GUILD_ID=your server id
COUNT_JSON_PATH=/path/to/door-counter-v3/data/count.json
```
