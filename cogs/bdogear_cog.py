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
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.output_file = "gear_database.json"
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]

    def get_driver(self):
        options = Options()
        options.add_argument("--headless") # Обов'язково для Render
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # На Render шляхи до бінарників Chrome можуть відрізнятися
        chrome_bin = os.environ.get("GOOGLE_CHROME_BIN")
        if chrome_bin:
            options.binary_location = chrome_bin
            
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    @commands.command(name="start_parse")
    async def start_parse(self, ctx):
        await ctx.send("Парсинг заплановано на 00:00. Бот активний.")
        
        # Логіка очікування півночі
        target_hour = 0
        while datetime.now().hour != target_hour:
            time.sleep(60)
            
        await ctx.send("Північ! Починаю збір даних через Selenium...")
        
        driver = self.get_driver()
        channel_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}"
        
        try:
            # Для Render потрібно передати Discord Token у LocalStorage через JS, 
            # бо ви не зможете ввести логін/пароль вручну
            driver.get("https://discord.com/login")
            # (Тут зазвичай додається скрипт авторизації через токен)
            
            gear_data = {}
            offset = 0
            index = 0
            
            # Емуляція переходу в канал
            driver.get(channel_url)
            time.sleep(10) 

            messages = driver.find_elements(By.XPATH, "//li[contains(@class, 'messageListItem')]")
            
            for msg in messages:
                content = msg.text
                links = re.findall(r'https?://(?:www\.)?garmoth\.com/character/\S+', content)
                
                if links:
                    author = msg.find_element(By.XPATH, ".//span[contains(@class, 'username')]").text
                    gear_data[author] = links[0]
                    
                    # Логіка затримок
                    delay_idx = index % len(self.delays)
                    if delay_idx == 0 and index > 0:
                        offset += 1
                    
                    wait_time = self.delays[delay_idx] + offset
                    time.sleep(wait_time)
                    index += 1

            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(gear_data, f, ensure_ascii=False, indent=4)
            
            await ctx.send(f"Збір завершено! Дані збережено в {self.output_file}")

        finally:
            driver.quit()

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
