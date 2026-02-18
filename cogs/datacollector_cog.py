import discord
from discord.ext import commands
from discord import app_commands
import aiocron
import json
import re
import datetime
import subprocess
import asyncio
from bs4 import BeautifulSoup

class DataCollector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_thread_id = 1358443998603120824
        self.data_file = "garmoth_history.json"
        
        # Автоматичний запуск о 00:00 кожної ночі
        self.cron = aiocron.crontab('0 0 * * *', func=self.nightly_job_wrapper)

    async def nightly_job_wrapper(self):
        print(f"[{datetime.datetime.now()}] Автоматичний нічний збір даних...")
        await self.run_full_collect_process()

    async def get_stats(self, url):
        """Парсинг через Playwright (емуляція браузера для обходу Cloudflare)"""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            print(f"[{datetime.datetime.now()}] Запуск браузера для: {url}")
            # Запускаємо headless-браузер
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                # Перехід на сторінку
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Чекаємо саме на цифри (клас text-2xl у блоці grid-cols-4)
                await page.wait_for_selector('.grid-cols-4 .text-2xl', timeout=20000)
                
                # Коротка пауза для рендеру цифр
                await asyncio.sleep(1)
                
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
                            "GS": values[3].get_text(strip=True),
                            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
            except Exception as e:
                print(f"Помилка Playwright: {e}")
            finally:
                await browser.close()
        return None

    async def find_url_in_thread(self):
        """Пошук посилання в історії гілки"""
        try:
            channel = self.bot.get_channel(self.target_thread_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.target_thread_id)

            async for message in channel.history(limit=50):
                match = re.search(r'https://garmoth\.com/character/\w+', message.content)
                if match:
                    return match.group(0)
        except Exception as e:
            print(f"Помилка пошуку посилання: {e}")
        return None

    def push_to_github(self):
        """Відправка оновленого файлу на GitHub"""
        try:
            subprocess.run(["git", "add", self.data_file], check=True)
            commit_msg = f"Update stats: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 Дані синхронізовано з GitHub")
        except Exception as e:
            print(f"Помилка Git: {e}")

    async def run_full_collect_process(self, interaction=None):
        """Основний процес збору"""
        url = await self.find_url_in_thread()
        if not url:
            if interaction: await interaction.followup.send("❌ Не знайдено посилання на Garmoth у гілці.")
            return

        stats = await self.get_stats(url)
        if stats:
            all_data = []
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
            except:
                pass

            all_data.append(stats)

            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=4, ensure_ascii=False)
            
            self.push_to_github()

            if interaction:
                await interaction.followup.send(f"✅ Дані зібрано (GS: {stats['GS']}) та відправлено на GitHub.")
        else:
            if interaction:
                await interaction.followup.send("❌ Не вдалося отримати дані. Playwright не зміг знайти статси.")

    @app_commands.command(name="collect", description="Зібрати дані з Garmoth вручну")
    async def collect(self, interaction: discord.Interaction):
        """Слеш-команда /collect"""
        await interaction.response.defer()
        await self.run_full_collect_process(interaction)

async def setup(bot):
    await bot.add_cog(DataCollector(bot))
