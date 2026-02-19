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
import time  # Додано для UNIX-часу
from bs4 import BeautifulSoup

class DataCollector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ID гілки, де лежать посилання
        self.target_thread_id = 1358443998603120824
        # Правильний шлях до папки з історією
        self.data_folder = "data"
        self.data_file = os.path.join(self.data_folder, "garmoth_history.json")
        
        # Створюємо папку data, якщо її немає
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
            
        # Автозапуск рівно о 00:00
        self.cron = aiocron.crontab('0 0 * * *', func=self.nightly_job_wrapper)

    async def nightly_job_wrapper(self):
        print(f"[{datetime.datetime.now()}] Нічне оновлення статсів гільдії...")
        await self.run_full_collect_process()

    async def get_stats(self, url):
        """Парсинг статсів з Garmoth"""
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Чекаємо цифри AP/DP
                await page.wait_for_selector('.grid-cols-4 .text-2xl', timeout=20000)
                await asyncio.sleep(2) # Час на завантаження динамічних даних
                
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
                print(f"Помилка збору з {url}: {e}")
            finally:
                await browser.close()
        return None

    async def collect_all_links(self):
        """Знаходить усі унікальні посилання та їх авторів у гілці"""
        links_map = {} # { url: display_name }
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
            print(f"Помилка при пошуку лінків: {e}")
        return links_map

    def push_to_github(self):
        """Відправка оновленого JSON на GitHub"""
        try:
            # Важливо: додаємо саме файл у папці data
            subprocess.run(["git", "add", self.data_file], check=True)
            commit_msg = f"Guild stats update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            subprocess.run(["git", "push"], check=True)
            print("🚀 GitHub успішно оновлено!")
        except Exception as e:
            print(f"Git Error: {e}")

    async def run_full_collect_process(self, interaction=None):
        """Основний цикл збору даних"""
        links = await self.collect_all_links()
        
        if not links:
            if interaction: await interaction.followup.send("❌ У цій гілці не знайдено посилань на Garmoth.")
            return

        if interaction:
            await interaction.followup.send(f"🔎 Знайдено {len(links)} персонажів. Починаю збір статсів...")

        all_current_data = []
        unix_time = int(time.time()) # Час для Discord формату

        for url, author in links.items():
            print(f"Зчитування даних для: {author}")
            stats = await self.get_stats(url)
            if stats:
                stats.update({
                    "Name": author,
                    "url": url,
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M") # Для JSON
                })
                all_current_data.append(stats)
                
                # Якщо це ручний запуск, надсилаємо проміжний звіт у Discord
                if interaction:
                    embed_msg = (
                        f"👤 **Персонаж:** `{author}`\n"
                        f"⚔️ **AP:** {stats['AP']} | **AAP:** {stats['AAP']}\n"
                        f"🛡️ **DP:** {stats['DP']}\n"
                        f"🌟 **Total GS:** {stats['GS']}\n"
                        f"🕒 **Час збору:** <t:{unix_time}:f>" # Формат Discord
                    )
                    await interaction.channel.send(embed_msg)
            
            await asyncio.sleep(1) # Захист від блокування сайтом

        if all_current_data:
            # Зберігаємо в файл
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(all_current_data, f, indent=4, ensure_ascii=False)
            
            # Відправляємо на GitHub
            self.push_to_github()
            
            if interaction:
                await interaction.followup.send(f"✅ Оновлено дані для {len(all_current_data)} гравців. Перевірте GitHub!")

    @app_commands.command(name="collect", description="Зібрати статси всієї гільдії з Garmoth")
    async def collect(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.run_full_collect_process(interaction)

async def setup(bot):
    await bot.add_cog(DataCollector(bot))
