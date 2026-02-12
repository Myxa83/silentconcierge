import discord
from discord.ext import commands
import json
import asyncio
import re
import os
from datetime import datetime

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Шлях до вашої папки data
        self.data_path = os.path.join("data", "members_gear.json")
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]

    async def scrape_links(self, ctx):
        await ctx.send("🔍 Починаю збір посилань Garmoth з історії каналу...")
        
        gear_data = {}
        offset = 0
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Читаємо останні 1000 повідомлень у цьому каналі
        async for message in ctx.channel.history(limit=1000):
            if "garmoth.com" in message.content:
                links = re.findall(pattern, message.content)
                if links:
                    author_name = message.author.display_name
                    # Беремо тільки найсвіжіше посилання від кожного гравця
                    if author_name not in gear_data:
                        gear_data[author_name] = links[0]
                        
                        # Ваша унікальна система затримок + зміщення
                        delay_idx = count % len(self.delays)
                        if delay_idx == 0 and count > 0:
                            offset += 1
                        
                        wait_time = self.delays[delay_idx] + offset
                        print(f"Знайдено: {author_name}, очікування {wait_time}с")
                        
                        # Емуляція затримки, як ви просили
                        await asyncio.sleep(wait_time)
                        count += 1

        # Збереження результатів
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        if gear_data:
            file = discord.File(self.data_path)
            await ctx.send(f"✅ Готово! Оброблено {len(gear_data)} гравців. Ось файл:", file=file)
        else:
            await ctx.send("❌ Посилань на Garmoth не знайдено в останніх 1000 повідомленнях.")

    @commands.command(name="test_parse")
    @commands.has_permissions(administrator=True)
    async def test_parse(self, ctx):
        await self.scrape_links(ctx)

    @commands.command(name="start_parse")
    @commands.has_permissions(administrator=True)
    async def start_parse(self, ctx):
        await ctx.send("🌙 Парсинг заплановано на 00:00 за часом сервера.")
        while True:
            now = datetime.now()
            if now.hour == 0 and now.minute == 0:
                break
            await asyncio.sleep(30)
        await self.scrape_links(ctx)

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
