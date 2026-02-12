import discord
from discord.ext import commands
import json
import time
import re
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# Спробуємо імпортувати менеджер драйверів
try:
    from webdriver_manager.chrome import ChromeDriverManager
    WDM_AVAILABLE = True
except ImportError:
    WDM_AVAILABLE = False

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_path = os.path.join("data", "members_gear.json")
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]

    def get_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("window-size=1920,1080")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Шлях до Chrome на Render (після додавання Buildpacks)
        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN")
        if chrome_bin:
            options.binary_location = chrome_bin

        if WDM_AVAILABLE:
            service = Service(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=options)
        else:
            # Спроба запустити без менеджера, якщо він не встановився
            return webdriver.Chrome(options=options)

    @commands.command(name="test_parse")
    async def test_parse(self, ctx):
        if not WDM_AVAILABLE:
            await ctx.send("❌ Помилка: webdriver-manager не встановлено. Перевірте requirements.txt")
            return
            
        await ctx.send("🧪 Запускаю Selenium тест...")
        # ... решта логіки парсингу ...
