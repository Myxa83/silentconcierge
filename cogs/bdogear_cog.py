import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
import re
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Шлях до файлу (зберігаємо у папку data)
        self.data_path = os.path.join("data", "members_gear.json")
        # Твій список затримок для імітації людини
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        # ID гілки за замовчуванням
        self.target_channel_id = 1358443998603120824 

    async def fetch_stats_playwright(self, url):
        """Парсинг статсів через справжній браузер (Playwright)"""
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Чекаємо на появу цифр
                await page.wait_for_selector('.grid-cols-4 .text-2xl', timeout=20000)
                await asyncio.sleep(2) # Даємо час підвантажити реальні цифри
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                stats_container = soup.find('div', class_='grid-cols-4')
                
                if stats_container:
                    values = stats_container.find_all('p', class_='text-2xl')
                    if len(values) >= 4:
                        return {
                            "ap": values[0].get_text(strip=True),
                            "aap": values[1].get_text(strip=True),
                            "dp": values[2].get_text(strip=True),
                            "gs": values[3].get_text(strip=True)
                        }
            except Exception as e:
                print(f"Помилка збору {url}: {e}")
            finally:
                await browser.close()
        return None

    async def run_mass_collect(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Основна логіка масового збору"""
        await interaction.followup.send(f"⚙️ **Запуск...** Отримую дані з #{channel.name}")
        
        gear_data = {}
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Читаємо історію повідомлень (останні 500 для швидкості)
        messages = [msg async for msg in channel.history(limit=500)]
        valid_messages = [m for m in messages if "garmoth.com/character/" in m.content]
        
        for message in valid_messages:
            links = re.findall(pattern, message.content)
            if links:
                author_name = message.author.display_name
                # Беремо тільки найновіше посилання від кожного гравця
                if author_name not in gear_data:
                    link = links[0]
                    count += 1
                    
                    # Отримуємо реальні статси
                    stats = await self.fetch_stats_playwright(link)
                    
                    # Час для Discord формату
                    unix_time = int(time.time())
                    # Затримка з твого списку
                    wait_time = self.delays[(count - 1) % len(self.delays)]

                    # Формуємо Embed картку
                    embed = discord.Embed(
                        title="✨ Garmoth Profile Updated",
                        description=f"Дані гравця **{author_name}** оновлено.",
                        color=discord.Color.blue(),
                        timestamp=datetime.now()
                    )
                    
                    if stats:
                        embed.add_field(name="⚔️ AP/AAP", value=f"{stats['ap']} / {stats['aap']}", inline=True)
                        embed.add_field(name="🛡️ DP", value=stats['dp'], inline=True)
                        embed.add_field(name="🌟 Gearscore", value=f"**{stats['gs']}**", inline=True)
                    else:
                        embed.add_field(name="Статус", value="❌ Не вдалося зчитати дані (Private?)", inline=False)
                    
                    embed.add_field(name="🕒 Час збору", value=f"<t:{unix_time}:f>", inline=False)
                    embed.add_field(name="🔗 Посилання", value=f"[Garmoth Profile]({link})", inline=False)
                    embed.set_footer(text=f"Прогрес: {count} | Очікування: {wait_time}с", icon_url=message.author.display_avatar.url)
                    
                    await interaction.channel.send(embed=embed)

                    # Зберігаємо в базу
                    gear_data[author_name] = {
                        "link": link,
                        "gs": stats['gs'] if stats else "N/A",
                        "all_stats": stats,
                        "user_id": message.author.id,
                        "updated": datetime.now().strftime("%d.%m.%Y %H:%M")
                    }

                    # Пауза перед наступним гравцем
                    await asyncio.sleep(wait_time)

        # Зберігаємо JSON
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        # Відправка файлу на GitHub (через твій налаштований Git)
        try:
            subprocess.run(["git", "add", self.data_path], check=True)
            subprocess.run(["git", "commit", "-m", f"Mass update {datetime.now()}"], check=True)
            subprocess.run(["git", "push"], check=True)
        except:
            print("Git push failed")

        await interaction.channel.send(f"✅ **Парсинг завершено!** Оброблено гравців: {len(gear_data)}")

    @app_commands.command(name="collect", description="Масовий збір статсів усієї гільдії")
    async def collect(self, interaction: discord.Interaction):
        """Команда /collect"""
        await interaction.response.defer()
        target_channel = self.bot.get_channel(self.target_channel_id) or await self.bot.fetch_channel(self.target_channel_id)
        await self.run_mass_collect(interaction, target_channel)

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
