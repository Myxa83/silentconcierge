import discord
from discord.ext import commands
import json
import asyncio
import re
import os

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Шлях до файлу у вашій структурі GitHub
        self.data_path = os.path.join("data", "members_gear.json")
        # Ваша послідовність затримок
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        # Встановлюємо ваш новий ID каналу як основний
        self.target_channel_id = 1358443998603120824 

    async def scrape_gear_links(self, ctx, channel: discord.TextChannel):
        await ctx.send(f"🔍 Починаю збір посилань з каналу: **#{channel.name}**...")
        
        gear_data = {}
        offset = 0
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Зчитуємо історію цільового каналу
        async for message in channel.history(limit=1000):
            if "garmoth.com" in message.content:
                links = re.findall(pattern, message.content)
                if links:
                    author_name = message.author.display_name
                    # Зберігаємо лише найновіше посилання від кожного гравця
                    if author_name not in gear_data:
                        gear_data[author_name] = links[0]
                        
                        # Розрахунок затримок: список + 1с кожне повне коло
                        delay_idx = count % len(self.delays)
                        if delay_idx == 0 and count > 0:
                            offset += 1
                        
                        wait_time = self.delays[delay_idx] + offset
                        # Лог у консоль Render для контролю
                        print(f"Парсинг: {author_name}, очікування {wait_time}с")
                        
                        await asyncio.sleep(wait_time)
                        count += 1

        # Перевірка та створення папки data
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        
        # Запис у JSON
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        if gear_data:
            # Відправляємо файл у чат, де була введена команда
            file = discord.File(self.data_path)
            await ctx.send(f"✅ Готово! Оброблено {len(gear_data)} гравців. Дані збережені з каналу {channel.mention}.", file=file)
        else:
            await ctx.send(f"❌ У каналі {channel.mention} не знайдено жодного посилання на Garmoth.")

    @commands.command(name="collect_gear")
    @commands.has_permissions(administrator=True)
    async def collect_gear(self, ctx, channel_id: int = None):
        """
        Команда для збору даних. Можна викликати в будь-якому каналі.
        Приклад: !collect_gear
        """
        # Використовуємо вказаний ID або наш стандартний 1358443998603120824
        target_id = channel_id or self.target_channel_id
        
        target_channel = self.bot.get_channel(target_id)
        
        # Якщо канал не знайдено в кеші, спробуємо отримати його напряму
        if not target_channel:
            try:
                target_channel = await self.bot.fetch_channel(target_id)
            except Exception as e:
                await ctx.send(f"❌ Не вдалося знайти канал з ID `{target_id}`. Перевірте права бота.")
                print(f"Помилка пошуку каналу: {e}")
                return

        await self.scrape_gear_links(ctx, target_channel)

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
