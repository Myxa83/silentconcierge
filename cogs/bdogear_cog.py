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
        self.data_path = os.path.join("data", "members_gear.json")
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        self.target_channel_id = 1358443998603120824 
        
        # Налаштування скрапера з імітацією реального браузера
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )

    def fetch_gs_logic(self, url):
        """Спроба витягнути Gearscore з JSON-даних сторінки"""
        try:
            # Garmoth зазвичай віддає дані в структурі вікна або JSON
            response = self.scraper.get(url, timeout=15)
            if response.status_code == 200:
                # Шукаємо "gs":XXX у тексті сторінки
                gs_match = re.search(r'"gs":\s*(\d+)', response.text)
                if gs_match:
                    return gs_match.group(1)
                
                # Альтернативний пошук, якщо структура інша
                gs_alt = re.search(r'Gearscore:\s*(\d+)', response.text)
                if gs_alt:
                    return gs_alt.group(1)
                    
                return "Private"
            return f"Err {response.status_code}"
        except Exception as e:
            print(f"Scraper error: {e}")
            return "Timeout/Blocked"

    async def scrape_gear_links(self, ctx, channel: discord.TextChannel):
        print(f"--- ЗАПУСК ПОВНОГО ПАРСИНГУ: {channel.name} ---")
        status_msg = await ctx.send(f"⚙️ **Підготовка...** Отримую дані з #{channel.name}")
        
        gear_data = {}
        offset = 0
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Читаємо останні 1000 повідомлень
        messages = [msg async for msg in channel.history(limit=1000)]
        valid_messages = [m for m in messages if "garmoth.com" in m.content]
        total_found = len(valid_messages)
        
        await status_msg.edit(content=f"🔍 Знайдено профілів: **{total_found}**. Починаю обхід...")

        for message in valid_messages:
            links = re.findall(pattern, message.content)
            if links:
                author_name = message.author.display_name
                # Беремо тільки найсвіжіше посилання від кожного гравця
                if author_name not in gear_data:
                    link = links[0]
                    count += 1
                    
                    # Спроба отримати реальні цифри
                    gs_val = self.fetch_gs_logic(link)
                    
                    # Лог для Render
                    delay_idx = (count - 1) % len(self.delays)
                    if delay_idx == 0 and count > 1:
                        offset += 1
                    wait_time = self.delays[delay_idx] + offset
                    
                    print(f"[{count}] {author_name} | GS: {gs_val} | Очікування: {wait_time}с")

                    # Відправка красивої картки в чат
                    embed = discord.Embed(
                        title="✨ Garmoth Profile Update",
                        description=f"{message.author.mention} has updated their profile.",
                        color=discord.Color.blue(),
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="GS", value=f"**{gs_val}**", inline=True)
                    embed.add_field(name="Link", value=f"[Garmoth Profile]({link})", inline=False)
                    embed.set_footer(text=f"Прогрес: {count} | Сьогодні", icon_url=message.author.display_avatar.url)
                    
                    await ctx.send(embed=embed)

                    # Зберігаємо в базу
                    gear_data[author_name] = {
                        "link": link,
                        "gs": gs_val,
                        "user_id": message.author.id,
                        "updated": datetime.now().strftime("%d.%m.%Y %H:%M")
                    }

                    # Пауза згідно з вашим графіком
                    await asyncio.sleep(wait_time)

        # Збереження JSON
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        await status_msg.delete()
        if gear_data:
            file = discord.File(self.data_path)
            await ctx.send(f"✅ **Парсинг завершено!**\n📊 Гравців у базі: {len(gear_data)}", file=file)

    @commands.command(name="collect_gear")
    @commands.has_permissions(administrator=True)
    async def collect_gear(self, ctx, channel_id: int = None):
        target_id = channel_id or self.target_channel_id
        try:
            target_channel = self.bot.get_channel(target_id) or await self.bot.fetch_channel(target_id)
            await self.scrape_gear_links(ctx, target_channel)
        except Exception as e:
            await ctx.send(f"❌ Помилка доступу до каналу: {e}")

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
