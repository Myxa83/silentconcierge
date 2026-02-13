import discord
from discord.ext import commands
import json
import asyncio
import re
import os
import cloudscraper
from datetime import datetime

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Шлях до файлу (використовуємо English names для папок/файлів)
        self.data_path = os.path.join("data", "members_gear.json")
        # Ваша унікальна черга затримок
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        # ID цільового каналу
        self.target_channel_id = 1358443998603120824 
        # Скрапер для обходу захисту Garmoth
        self.scraper = cloudscraper.create_scraper()

    def fetch_gs_logic(self, url):
        """Спроба витягнути Gearscore зі сторінки"""
        try:
            response = self.scraper.get(url, timeout=10)
            if response.status_code == 200:
                # Шукаємо ГС у коді сторінки
                gs_match = re.search(r'"gs":(\d+)', response.text)
                if gs_match:
                    return gs_match.group(1)
                return "Private"
            return "Error"
        except:
            return "Blocked"

    async def scrape_gear_links(self, ctx, channel: discord.TextChannel):
        print(f"--- ЗАПУСК ПОВНОГО ПАРСИНГУ: {channel.name} ---")
        status_msg = await ctx.send(f"⚙️ **Підготовка...** Звертаюся до каналу #{channel.name}")
        
        gear_data = {}
        offset = 0
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Завантажуємо історію
        messages = [msg async for msg in channel.history(limit=1000)]
        total_found = sum(1 for m in messages if "garmoth.com" in m.content)
        
        await status_msg.edit(content=f"🔍 Знайдено посилань: **{total_found}**. Починаю обробку...")

        for message in messages:
            if "garmoth.com" in message.content:
                links = re.findall(pattern, message.content)
                if links:
                    author_name = message.author.display_name
                    if author_name not in gear_data:
                        link = links[0]
                        count += 1
                        
                        # Спроба дістати ГС
                        gs_val = self.fetch_gs_logic(link)
                        
                        # Лог у консоль Render
                        delay_idx = (count - 1) % len(self.delays)
                        if delay_idx == 0 and count > 1:
                            offset += 1
                        wait_time = self.delays[delay_idx] + offset
                        
                        print(f"[{count}] {author_name} | GS: {gs_val} | Wait: {wait_time}s")

                        # Створення синьої картки (як у Yappi)
                        embed = discord.Embed(
                            title="✨ Garmoth Profile Update",
                            description=f"{message.author.mention} has updated their profile.",
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )
                        embed.add_field(name="GS", value=f"**{gs_val}**", inline=True)
                        embed.add_field(name="Link", value=f"[Garmoth Profile]({link})", inline=False)
                        embed.set_footer(text=f"Progress: {count}/{total_found}", icon_url=message.author.display_avatar.url)
                        
                        await ctx.send(embed=embed)

                        # Зберігаємо дані
                        gear_data[author_name] = {
                            "link": link,
                            "gs": gs_val,
                            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }

                        await asyncio.sleep(wait_time)

        # Збереження результатів
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        await status_msg.delete()
        
        if gear_data:
            file = discord.File(self.data_path)
            await ctx.send(f"✅ **Збір завершено!** Оброблено {len(gear_data)} гравців.", file=file)
        else:
            await ctx.send(f"❌ Посилань не знайдено.")

    @commands.command(name="collect_gear")
    @commands.has_permissions(administrator=True)
    async def collect_gear(self, ctx, channel_id: int = None):
        target_id = channel_id or self.target_channel_id
        try:
            target_channel = self.bot.get_channel(target_id) or await self.bot.fetch_channel(target_id)
            await self.scrape_gear_links(ctx, target_channel)
        except Exception as e:
            print(f"КРИТИЧНА ПОМИЛКА: {e}")
            await ctx.send(f"❌ Помилка: {e}")

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
