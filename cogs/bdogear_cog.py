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
        # Ваша послідовність затримок
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]

    async def scrape_gear_links(self, ctx):
        await ctx.send("🔍 Починаю збір посилань на екіпірування з історії каналу...")
        
        gear_data = {}
        offset = 0
        count = 0
        # Регулярний вираз для пошуку посилань на Garmoth
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Зчитуємо останні 1000 повідомлень у каналі
        async for message in ctx.channel.history(limit=1000):
            if "garmoth.com" in message.content:
                links = re.findall(pattern, message.content)
                if links:
                    author_name = message.author.display_name
                    # Зберігаємо тільки останнє (найсвіжіше) посилання від кожного гравця
                    if author_name not in gear_data:
                        gear_data[author_name] = links[0]
                        
                        # Ваша логіка затримок: список + додавання 1с після кожного повного кола
                        delay_idx = count % len(self.delays)
                        if delay_idx == 0 and count > 0:
                            offset += 1
                        
                        wait_time = self.delays[delay_idx] + offset
                        print(f"Оброблено: {author_name}, очікування {wait_time}с")
                        
                        # Чекаємо згідно з вашим графіком
                        await asyncio.sleep(wait_time)
                        count += 1

        # Створення директорії, якщо вона відсутня
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        
        # Запис у JSON файл
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        if gear_data:
            file = discord.File(self.data_path)
            await ctx.send(f"✅ Готово! Оброблено {len(gear_data)} гравців. Ось файл з результатами:", file=file)
        else:
            await ctx.send("❌ У цьому каналі не знайдено посилань на Garmoth в останніх 1000 повідомленнях.")

    @commands.command(name="collect_gear")
    @commands.has_permissions(administrator=True)
    async def collect_gear(self, ctx):
        """Нова команда для збору даних (замість test_parse та start_parse)"""
        await self.scrape_gear_links(ctx)

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
