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
        # Використовуємо aiocron для точності
        self.cron = aiocron.crontab('0 0 * * *', func=self.nightly_job_wrapper)

    async def nightly_job_wrapper(self):
        print(f"[{datetime.datetime.now()}] Автоматичний нічний збір даних за розкладом...")
        await self.run_full_collect_process()

    async def get_stats(self, url):
        """Парсинг через Playwright (емуляція браузера для обходу Cloudflare)"""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            print(f"[{datetime.datetime.now()}] Відкриваємо браузер для: {url}")
            
            browser = await p.chromium.launch(headless=True)
            
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                # Перехід на сторінку з очікуванням завантаження
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Чекаємо, поки на сторінці з'являться статси (цифри)
                await page.wait_for_selector('.grid-cols-4 .text-2xl', timeout=20000)
                
                # Даємо сайту 1.5 секунди дорендерити анімації цифр
                await asyncio.sleep(1.5)
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                # Шукаємо контейнер з числами AP/DP
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
                print(f"Помилка при роботі з браузером: {e}")
            finally:
                await browser.close()
                
        return None

    async def find_url_in_thread(self):
        """Шукаємо лінк на Garmoth в історії повідомлень гілки"""
        try:
            channel = self.bot.get_channel(self.target_thread_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.target_thread_id)

            async for message in channel.history(limit=50):
                # Регулярний вираз для пошуку лінка
                match = re.search(r'https://garmoth\.com/character/\w+', message.content)
                if match:
                    return match.group(0)
        except Exception as e:
            print(f"Не вдалося знайти посилання в гілці: {e}")
            
        return None

    def push_to_github(self):
        """Відправляємо оновлений JSON файл на GitHub репозиторій"""
        try:
            subprocess.run(["git", "add", self.data_file], check=True)
            
            commit_msg = f"Update stats: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            
            subprocess.run(["git", "push"], check=True)
            print("🚀 Файл успішно синхронізовано з GitHub")
            
        except Exception as e:
            print(f"Помилка при роботі з Git: {e}")

    async def run_full_collect_process(self, interaction=None):
        """Головний процес: збір -> збереження -> звіт"""
        
        # 1. Знаходимо посилання
        url = await self.find_url_in_thread()
        if not url:
            if interaction:
                await interaction.followup.send("❌ Я не знайшов посилання на Garmoth у цій гілці.")
            return

        # 2. Отримуємо дані з сайту
        stats = await self.get_stats(url)
        
        if stats:
            # 3. Визначаємо нікнейм з Discord ( display_name )
            user_nick = "Користувач"
            if interaction:
                user_nick = interaction.user.display_name
            
            stats["Name"] = user_nick

            # 4. Формуємо звіт для Discord
            display_message = (
                f"👤 **Персонаж:** `{user_nick}`\n"
                f"⚔️ **AP:** {stats['AP']} | **AAP:** {stats['AAP']}\n"
                f"🛡️ **DP:** {stats['DP']}\n"
                f"🌟 **Total GS:** {stats['GS']}\n"
                f"🕒 _Оновлено: {stats['time']}_\n"
                f"🚀 Дані відправлено на GitHub."
            )

            # 5. Зберігаємо в файл garmoth_history.json
            all_data = []
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    file_content = f.read()
                    # Перевіряємо, чи файл не порожній, щоб json.loads не видав помилку
                    if file_content.strip():
                        all_data = json.loads(file_content)
            except (FileNotFoundError, json.JSONDecodeError):
                # Якщо файлу немає або він "битий", починаємо з чистого списку
                print(f"Створюємо новий або виправляємо файл {self.data_file}")

            # Додаємо новий запис в історію
            all_data.append(stats)

            # Записуємо назад у файл з гарними відступами
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=4, ensure_ascii=False)
            
            # 6. Відправляємо на GitHub
            self.push_to_github()

            # 7. Відповідаємо в Discord
            if interaction:
                await interaction.followup.send(display_message)
                
        else:
            if interaction:
                await interaction.followup.send("❌ Не вдалося зчитати дані. Можливо, сайт Garmoth тимчасово недоступний.")

    @app_commands.command(name="collect", description="Зібрати дані з вашого Garmoth прямо зараз")
    async def collect(self, interaction: discord.Interaction):
        """Команда /collect"""
        # Спочатку кажемо Discord, що ми працюємо (щоб не було помилки тайм-ауту)
        await interaction.response.defer()
        # Запускаємо збір
        await self.run_full_collect_process(interaction)

async def setup(bot):
    await bot.add_cog(DataCollector(bot))
