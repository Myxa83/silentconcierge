import discord
import json
from discord.ext import tasks, commands
from datetime import datetime, timedelta
import pytz

class VellReminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_vell_event.start()

    def cog_unload(self):
        self.check_vell_event.cancel()

    @tasks.loop(minutes=1)
    async def check_vell_event(self):
        now = datetime.now(pytz.timezone("Europe/London"))
        weekday = now.weekday()  # Monday = 0, Sunday = 6

        if weekday not in [2, 6]:  # Only check on Wednesday (2) and Sunday (6)
            return

        try:
            with open("vell_data.json", "r") as f:
                vell_data = json.load(f)
        except FileNotFoundError:
            return

        # Simulated Vell time (replace with dynamic if needed)
        vell_time = now + timedelta(minutes=2)  # TEST MODE
        notify_time = vell_time - timedelta(minutes=30)
        final_time = vell_time

        # Notify at -30min
        if now.strftime("%H:%M") == notify_time.strftime("%H:%M"):
            channel = self.bot.get_channel(1370522199873814528)  # Replace with your channel ID
            if channel:
                timestamp = int((vell_time - timedelta(minutes=5)).timestamp())
                await channel.send("Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲")

                embed = discord.Embed(
                    title="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
                    description=f"Скоро хтось лутне ![серце](https://bdocodex.com/items/new_icon/03_etc/04_dropitem/00044335.webp), а ти лутнеш ![крони](https://bdocodex.com/items/new_icon/03_etc/00016080.webp) 4 крони.\n\n"
                                f"🕒 Час: <t:{timestamp}:t>\n\n"
                                f"📍 Сервер: {vell_data['server']}\n"
                                f"🧭 Додаткове інфо: {'summon' if vell_data['summon'] else 'без summon'}\n\n"
                                f"📌 Шепотіть:\n```ansi\n\u001b[0;31m{vell_data['responsible']}\u001b[0m\n```",
                    color=discord.Color.teal()
                )
                embed.set_thumbnail(url="https://bdocodex.com/items/new_icon/03_etc/04_dropitem/00044335.webp")
                embed.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/raw.png")
                embed.set_footer(text="Silent Concierge by Myxa")
                await channel.send(embed=embed)

        # Change visual at exact Vell time
        if now.strftime("%H:%M") == final_time.strftime("%H:%M"):
            channel = self.bot.get_channel(1370522199873814528)
            if channel:
                embed = discord.Embed(
                    title="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
                    description="Йой! Хтось і лутнув ![серце](https://bdocodex.com/items/new_icon/03_etc/04_dropitem/00044335.webp), а ти ![крони](https://bdocodex.com/items/new_icon/03_etc/00016080.webp) 4 крони.\nА може ти, навіть, з нами не пішов 🫠",
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url="https://bdocodex.com/items/new_icon/03_etc/04_dropitem/00044335.webp")
                embed.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/raw.png")
                embed.set_footer(text="Silent Concierge by Myxa")
                await channel.send(embed=embed)

    @check_vell_event.before_loop
    async def before_check_vell_event(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(VellReminder(bot))
