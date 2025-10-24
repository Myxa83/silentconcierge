# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import pytz
from datetime import datetime

MODERATOR_ROLE_ID = 1375070910138028044

class TimezoneCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("[TIMEZONE] ✅ TimezoneCog ініціалізовано")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Відстежує зміну ролей користувача."""
        if before.roles != after.roles:
            # Якщо користувачу дали роль модератора
            added_roles = [r for r in after.roles if r not in before.roles]
            for role in added_roles:
                if role.id == MODERATOR_ROLE_ID:
                    # Більше не надсилаємо повідомлення у welcome-канал
                    try:
                        await after.send(
                            "Вітаю! Не забудь встановити таймзону через `/set_timezone`."
                        )
                    except discord.Forbidden:
                        # Просто ігноруємо, якщо ДМ закриті
                        print(f"[TIMEZONE] ⚠️ Не вдалося відправити ДМ для {after.name}")
                    break

    @commands.hybrid_command(name="time", description="Показує поточний час за твоєю таймзоною")
    async def time(self, ctx):
        tz = pytz.timezone("Europe/London")
        now = datetime.now(tz)
        await ctx.send(f"🕒 Поточний час: **{now.strftime('%H:%M')}** (Лондон)")

async def setup(bot):
    await bot.add_cog(TimezoneCog(bot))
    print("✅ Silent Concierge | TimezoneCog активовано.")