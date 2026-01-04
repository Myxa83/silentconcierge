# bot_main.py
import asyncio
import discord
from discord.ext import commands

from config.loader import DISCORD_TOKEN, GUILD_ID

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            help_command=None
        )

    async def setup_hook(self):
        EXTENSIONS = [
            # твої коги
        ]

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        if GUILD_ID:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"Ready as {self.user} ({self.user.id})")

async def main():
    bot = Bot()
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
