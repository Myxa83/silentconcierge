import discord
from discord.ext import commands
import json
import time
import re
import os
import asyncio
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# Спроба імпорту менеджера драйверів для роботи на Render
try:
    from webdriver_manager.chrome import ChromeDriverManager
    WDM_AVAILABLE = True
except ImportError:
    WDM_AVAILABLE = False

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Шлях до файлу згідно з вашою структурою: silentconcierge/data/members_gear.json
        self.data_path = os.path.join("data", "members_gear.json")
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]

    def get_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("window-size=1920,1080")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Використання бінарного файлу Chrome, якщо він встановлений через Buildpacks
        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN")
        if chrome_bin:
            options.binary_location = chrome_bin

        if WDM_AVAILABLE:
            service = Service(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=options)
        else:
            return webdriver.Chrome(options=options)

    async def run_parser(self, ctx):
        await ctx.send("🚀 Запускаю Selenium-двигун...")
        
        # Виконуємо Selenium у фоновому потоці, щоб не блокувати бота
        loop = asyncio.get_event_loop()
        try:
            driver = await loop.run_in_executor(None, self.get_driver)
            channel_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}"
            
            await loop.run_in_executor(None, driver.get, channel_url)
            await asyncio.sleep(15) # Час на провантаження сторінки

            gear_data = {}
            offset = 0
            count = 0
            pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

            # Пошук повідомлень
            messages = driver.find_elements(By.XPATH, "//li[contains(@class, 'messageListItem')]")
            
            for msg in messages:
                text = msg.text
                links = re.findall(pattern, text)
                
                if links:
                    try:
                        author = msg.find_element(By.XPATH, ".//span[contains(@class, 'username')]").text
                        gear_data[author] = links[0]
                        
                        # Розрахунок затримки з вашої умови
                        delay_idx = count % len(self.delays)
                        if delay_idx == 0 and count > 0:
                            offset += 1
                        
                        wait_time = self.delays[delay_idx] + offset
                        await asyncio.sleep(wait_time)
                        count += 1
                    except:
                        continue

            # Створення папки data, якщо її немає
            os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
            
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(gear_data, f, ensure_ascii=False, indent=4)

            await ctx.send(f"✅ Готово! Оброблено {len(gear_data)} гравців.", file=discord.File(self.data_path))
            driver.quit()
            
        except Exception as e:
            await ctx.send(f"❌ Сталася помилка: {str(e)}")

    @commands.command(name="test_parse")
    @commands.has_permissions(administrator=True)
    async def test_parse(self, ctx):
        await self.run_parser(ctx)

    @commands.command(name="start_parse")
    @commands.has_permissions(administrator=True)
    async def start_parse(self, ctx):
        await ctx.send("🌙 Парсинг заплановано на 00:00 за часом сервера.")
        while True:
            now = datetime.now()
            if now.hour == 0 and now.minute == 0:
                break
            await asyncio.sleep(30)
        await self.run_parser(ctx)

# Ця функція ОБОВ'ЯЗКОВА, щоб бот зміг завантажити ког
async def setup(bot):
    await bot.add_cog(BdoGear(bot))
