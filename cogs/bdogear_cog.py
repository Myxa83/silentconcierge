import discord
from discord.ext import commands
import json
import asyncio
import re
import os

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_path = os.path.join("data", "members_gear.json")
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        # Вставте ID каналу з посиланнями сюди, якщо хочете за замовчуванням
        self.target_channel_id = 1338167475141017765 

    async def scrape_gear_links(self, ctx, channel: discord.TextChannel):
        await ctx.send(f"🔍 Починаю збір з каналу: **#{channel.name}**...")
        
        gear_data = {}
        offset = 0
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        async for message in channel.history(limit=1000):
            if "garmoth.com" in message.content:
                links = re.findall(pattern, message.content)
                if links:
                    author_name = message.author.display_name
                    if author_name not in gear_data:
                        gear_data[author_name] = links[0]
                        
                        delay_idx = count % len(self.delays)
                        if delay_idx == 0 and count > 0:
                            offset += 1
                        
                        wait_time = self.delays[delay_idx] + offset
                        # Виводимо прогрес у консоль Render
                        print(f"Знайдено: {author_name}, очікування {wait_time}с")
                        
                        await asyncio.sleep(wait_time)
                        count += 1

        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        if gear_data:
            file = discord.File(self.data_path)
            await ctx.send(f"✅ Готово! Оброблено {len(gear_data)} гравців з каналу {channel.mention}.", file=file)
        else:
            await ctx.send(f"❌ У каналі {channel.mention} не знайдено посилань на Garmoth.")

    @commands.command(name="collect_gear")
    @commands.has_permissions(administrator=True)
    async def collect_gear(self, ctx, channel_id: int = None):
        """
        Використання: 
        !collect_gear (використає ID з коду)
        !collect_gear 123456789 (використає вказаний ID)
        """
        # Якщо ID не вказано в команді, беремо той, що прописаний у __init__
        target_id = channel_id or self.target_channel_id
        
        target_channel = self.bot.get_channel(target_id)
        
        if not target_channel:
            # Спробуємо завантажити канал, якщо він не в кеші
            try:
                target_channel = await self.bot.fetch_channel(target_id)
            except:
                await ctx.send(f"❌ Не вдалося знайти канал з ID `{target_id}`. Перевірте доступ бота.")
                return

        await self.scrape_gear_links(ctx, target_channel)

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
