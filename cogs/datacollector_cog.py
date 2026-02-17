import discord
from discord.ext import commands
import aiocron  # Додаємо для точного часу
import datetime
import json
# ... інші твої імпорти (playwright, re, subprocess) ...

class DataCollector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_thread_id = 1358443998603120824
        self.data_file = "garmoth_stats.json"
        
        # Налаштовуємо запуск рівно о 00:00 кожної ночі
        @aiocron.crontab('0 0 * * *')
        async def nightly_job():
            print(f"[{datetime.datetime.now()}] Нічний збір даних почато...")
            await self.run_full_collect_process()

    # Спільна функція для команди і для розкладу
    async def run_full_collect_process(self, ctx=None):
        url = await self.find_url_in_thread()
        if not url:
            if ctx: await ctx.send("❌ Посилання в гілці не знайдено.")
            return

        stats = await self.get_stats(url)
        if stats:
            self.save_and_sync(stats)
            if ctx: await ctx.send(f"✅ Статси оновлено та відправлено на GitHub!")
        else:
            if ctx: await ctx.send("❌ Помилка парсингу сайту.")

    @commands.command()
    async def collect(self, ctx):
        """Ручний запуск по команді !collect"""
        await ctx.send("⏳ Запускаю ручний збір даних...")
        await self.run_full_collect_process(ctx)

    # ... тут твої функції get_stats, find_url_in_thread, save_and_sync, push_to_github ...
