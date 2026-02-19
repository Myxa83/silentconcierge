import discord
from discord.ext import commands
from discord import app_commands
import aiocron
import json
import re
import datetime
import subprocess
import asyncio
import os
from bs4 import BeautifulSoup

class DataCollector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ID гілки Discord
        self.target_thread_id = 1358443998603120824
        # Шлях до файлу (враховуючи папку data з твого GitHub)
        self.data_folder = "data"
        self.data_file = os.path.join(self.data_folder, "garmoth_history.json")
        
        # Створюємо папку data, якщо вона раптом зникне
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
        
        # Автозапуск о 00:00
        self.cron = aiocron.crontab('0 0 * * *', func=self.nightly_job_wrapper)

    async def nightly_job_wrapper(self):
        print(f"[{datetime.datetime.now()}] Початок автоматичного оновлення гільдії...")
        await self.run_full_collect_process()

    async def get_stats(self, url):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                # Чекаємо повного завантаження
                await page.goto(url, wait_until="networkidle", timeout=60000)
                # Чекаємо цифри AP/DP
                await page.wait_for_selector('.grid-cols-4 .text-2xl', timeout=20000)
                await asyncio.sleep(2) # Час на рендер
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                stats_container = soup.find('div', class_='grid-cols-4')
                
                if stats_container:
                    values = stats_container.find_all('p', class_='text-2xl')
                    if len(values) >= 4:
                        return {
                            "AP": values[0].get_text(strip=True),
                            "AAP": values[1].get_text(strip=True),
                            "DP": values[2].get_text(strip=True),
                            "GS": values[3].get_text(strip=True)
                        }
            except Exception as e:
                print(f"Помилка Garmoth ({url}): {e}")
            finally:
                await browser.close()
        return None

    async def collect_all_guild_links(self):
        """Збирає всі унікальні лінки та авторів з чату"""
        links_map = {} # { url: author_name }
        try:
            channel = self.bot.get_channel(self.target_thread_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.target_thread_id)

            async for message in channel.history(limit=100):
                match = re.search(r'https://garmoth\.com/character/\w+', message.content)
                if match:
                    url = match.group(0)
                    if url not in links_map:
                        links_map[url] = message.author.display_name
        except Exception as e:
            print(f"Помилка історії: {e}")
        return links_map

    def push_to_github(self):
        try:
            # Обов'язково додаємо саме файл з папки data
            subprocess.run(["git", "add", self.data_file], check=True)
            commit_msg = f"Guild update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 GitHub успішно оновлено!")
        except Exception as e:
            print(f"Git Error: {e}")

    async def run_full_collect_process(self, interaction=None):
        links = await self.collect_all_guild_links()
        
        if not links:
            if interaction: await interaction.followup.send("❌ У гілці не знайдено посилань на Garmoth.")
            return

        if interaction: 
            await interaction.followup.send(f"🔎 Знайдено {len(links)} персонажів. Починаю збір даних...")

        all_current_stats = []
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        for url, author in links.items():
            print(f"Збір для: {author}")
            res = await self.get_stats(url)
            if res:
                res.update({"Name": author, "time": timestamp, "url": url})
                all_current_stats.append(res)
            await asyncio.sleep(1) # Невелика пауза між гравцями

        if all_current_stats:
            # Записуємо фінальний JSON
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(all_current_stats, f, indent=4, ensure_ascii=False)
            
            self.push_to_github()
            
            if interaction:
                await interaction.followup.send(f"✅ Успішно оновлено статси для {len(all_current_stats)} гравців на GitHub!")
        else:
            if interaction: await interaction.followup.send("❌ Не вдалося зчитати дані з жодного посилання.")

    @app_commands.command(name="collect", description="Оновити дані всієї гільдії з Garmoth")
    async def collect(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.run_full_collect_process(interaction)

async def setup(bot):
    await bot.add_cog(DataCollector(bot))
