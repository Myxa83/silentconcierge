import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
import re
import os
import time
import subprocess
from datetime import datetime
from bs4 import BeautifulSoup

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Шлях до файлу (зберігаємо у папку data)
        self.data_path = os.path.join("data", "members_gear.json")
        # Список затримок для імітації людини
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
                await asyncio.sleep(2) 
                
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
        
        # Завантажуємо існуючі дані, щоб не видалити тих, кого немає в останніх 500 повідомленнях
        gear_data = {}
        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as f:
                gear_data = json.load(f)

        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        # Читаємо історію повідомлень
        messages = [msg async for msg in channel.history(limit=500)]
        valid_messages = [m for m in messages if "garmoth.com/character/" in m.content]
        
        # Сортуємо від старих до нових, щоб нові записи перекривали старі
        valid_messages.reverse()

        for message in valid_messages:
            links = re.findall(pattern, message.content)
            if links:
                author_name = message.author.display_name
                link = links[-1] # Беремо останнє посилання в повідомленні
                
                # Починаємо парсинг
                count += 1
                stats = await self.fetch_stats_playwright(link)
                
                unix_time = int(time.time())
                wait_time = self.delays[(count - 1) % len(self.delays)]

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
                    
                    # Оновлюємо або додаємо дані в словник
                    gear_data[author_name.lower()] = {
                        "display_name": author_name,
                        "link": link,
                        "gs": stats['gs'],
                        "ap": stats['ap'],
                        "aap": stats['aap'],
                        "dp": stats['dp'],
                        "user_id": message.author.id,
                        "updated": datetime.now().strftime("%d.%m.%Y %H:%M")
                    }
                else:
                    embed.add_field(name="Статус", value="❌ Не вдалося зчитати дані (Private?)", inline=False)
                
                embed.add_field(name="🕒 Час збору", value=f"<t:{unix_time}:f>", inline=False)
                embed.add_field(name="🔗 Посилання", value=f"[Garmoth Profile]({link})", inline=False)
                embed.set_footer(text=f"Прогрес: {count} | Очікування: {wait_time}с", icon_url=message.author.display_avatar.url)
                
                await interaction.channel.send(embed=embed)
                await asyncio.sleep(wait_time)

        # Зберігаємо JSON
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        # Git push
        try:
            subprocess.run(["git", "add", self.data_path], check=True)
            subprocess.run(["git", "commit", "-m", f"Mass update {datetime.now().date()}"], check=True)
            subprocess.run(["git", "push"], check=True)
        except Exception as e:
            print(f"Git push failed: {e}")

        await interaction.channel.send(f"✅ **Парсинг завершено!** В базі тепер гравців: {len(gear_data)}")

    @app_commands.command(name="collect", description="Масовий збір статсів усієї гільдії")
    async def collect(self, interaction: discord.Interaction):
        await interaction.response.defer()
        target_channel = self.bot.get_channel(self.target_channel_id) or await self.bot.fetch_channel(self.target_channel_id)
        await self.run_mass_collect(interaction, target_channel)

    @app_commands.command(name="gear_find", description="Знайти ГС гравця за нікнеймом")
    @app_commands.describe(nickname="Нікнейм гравця в Discord")
    async def gear_find(self, interaction: discord.Interaction, nickname: str):
        """Пошук гравця в базі за ніком"""
        if not os.path.exists(self.data_path):
            await interaction.response.send_message("❌ База даних ще не створена. Запустіть `/collect` спочатку.", ephemeral=True)
            return

        with open(self.data_path, "r", encoding="utf-8") as f:
            gear_data = json.load(f)

        # Пошук без врахування регістру
        user_info = gear_data.get(nickname.lower())

        if not user_info:
            await interaction.response.send_message(f"❌ Гравця з ніком **{nickname}** не знайдено в базі.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🛡️ Gear Info: {user_info['display_name']}",
            color=discord.Color.green(),
            url=user_info['link']
        )
        embed.add_field(name="⚔️ AP/AAP", value=f"{user_info.get('ap', '??')} / {user_info.get('aap', '??')}", inline=True)
        embed.add_field(name="🛡️ DP", value=user_info.get('dp', '??'), inline=True)
        embed.add_field(name="🌟 Gearscore", value=f"**{user_info.get('gs', '??')}**", inline=True)
        embed.add_field(name="📅 Останнє оновлення", value=user_info.get('updated', 'Невідомо'), inline=False)
        embed.set_footer(text=f"ID: {user_info.get('user_id')}")

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
