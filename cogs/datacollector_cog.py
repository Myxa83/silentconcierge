import discord
from discord.ext import commands
import aiocron
import json
import re
import datetime
import subprocess
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

class DataCollector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_thread_id = 1358443998603120824
        self.data_file = "garmoth_history.json"
        
        # Налаштовуємо запуск рівно о 00:00 кожної ночі
        @aiocron.crontab('0 0 * * *')
        async def nightly_job():
            print(f"[{datetime.datetime.now()}] Автоматичний нічний збір даних...")
            await self.run_full_collect_process()

    async def get_stats(self, url):
        """Швидкий парсинг Garmoth без завантаження сміття"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Блокуємо медіа та стилі для економії ресурсів Oracle
            await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}", lambda route: route.abort())
            
            try:
                await page.goto(url, wait_until="commit", timeout=30000)
                await page.wait_for_selector(".grid-cols-4", timeout=15000)
                
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
        thread = self.bot.get_channel(self.target_thread_id)
        if not thread:
            try:
                thread = await self.bot.fetch_channel(self.target_thread_id)
            except:
                return None

        async for message in thread.history(limit=50):
            match = re.search(r'https://garmoth\.com/character/\w+', message.content)
            if match:
                return match.group(0)
        return None

    def push_to_github(self):
        """Відправка оновленого файлу на GitHub"""
        try:
            subprocess.run(["git", "add", self.data_file], check=True)
            commit_msg = f"Update stats: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 Дані успішно синхронізовано з GitHub")
        except Exception as e:
            print(f"Помилка Git: {e}")

    async def run_full_collect_process(self, ctx=None):
        """Основний процес: знайти посилання -> спарсити -> зберегти -> гіт"""
        url = await self.find_url_in_thread()
        if not url:
            if ctx: await ctx.send("❌ Не знайдено посилання на Garmoth у гілці.")
            return

        stats = await self.get_stats(url)
        if stats:
            # Читаємо старі дані
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    all_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                all_data = []

            all_data.append(stats)

            # Зберігаємо локально
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=4, ensure_ascii=False)
            
            # Відправляємо на GitHub
            self.push_to_github()

            if ctx: await ctx.send(f"✅ Дані зібрано (GS: {stats['GS']}) та відправлено на GitHub.")
        else:
            if ctx: await ctx.send("❌ Не вдалося отримати дані з сайту.")

    @commands.command()
    async def collect(self, ctx):
        """Ручна команда !collect"""
        await ctx.send("⌛ Починаю збір даних...")
        await self.run_full_collect_process(ctx)

async def setup(bot):
    await bot.add_cog(DataCollector(bot))
