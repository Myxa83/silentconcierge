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
        # ID гілки, де бот шукає посилання
        self.target_thread_id = 1358443998603120824
        # Назва файлу для збереження історії
        self.data_file = "garmoth_history.json"
        
        # Налаштування автоматичного запуску рівно о 00:00
        self.cron = aiocron.crontab('0 0 * * *', func=self.nightly_job_wrapper)

    async def nightly_job_wrapper(self):
        """Функція для нічного запуску"""
        print(f"[{datetime.datetime.now()}] Початок нічного збору за розкладом...")
        await self.run_full_collect_process()

    async def get_stats(self, url):
        """Парсинг сторінки Garmoth через браузер Playwright"""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            print(f"[{datetime.datetime.now()}] Запуск браузера для: {url}")
            
            # Запускаємо браузер (headless=True означає без вікна)
            browser = await p.chromium.launch(headless=True)
            
            try:
                # Маскуємося під звичайного користувача
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                # Переходимо на сторінку персонажа
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Очікуємо завантаження блоку зі статсами (клас .text-2xl)
                await page.wait_for_selector('.grid-cols-4 .text-2xl', timeout=20000)
                
                # Даємо час на фінальний рендер цифр (1.5 секунди)
                await asyncio.sleep(1.5)
                
                # Беремо вміст сторінки та обробляємо через BeautifulSoup
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                # Знаходимо контейнер, де лежать AP, AAP та DP
                stats_container = soup.find('div', class_='grid-cols-4')
                
                if stats_container:
                    values = stats_container.find_all('p', class_='text-2xl')
                    # Перевіряємо, чи знайшли ми всі 4 значення (AP, AAP, DP, GS)
                    if len(values) >= 4:
                        return {
                            "AP": values[0].get_text(strip=True),
                            "AAP": values[1].get_text(strip=True),
                            "DP": values[2].get_text(strip=True),
                            "GS": values[3].get_text(strip=True),
                            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                        
            except Exception as e:
                print(f"Сталася критична помилка при читанні сайту: {e}")
            finally:
                # Завжди закриваємо браузер
                await browser.close()
                
        return None

    async def find_url_in_thread(self):
        """Шукаємо посилання на Garmoth в останніх повідомленнях"""
        try:
            channel = self.bot.get_channel(self.target_thread_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.target_thread_id)

            # Переглядаємо останні 50 повідомлень
            async for message in channel.history(limit=50):
                match = re.search(r'https://garmoth\.com/character/\w+', message.content)
                if match:
                    return match.group(0)
        except Exception as e:
            print(f"Помилка пошуку лінка: {e}")
            
        return None

    def push_to_github(self):
        """Відправка файлу JSON на GitHub через системні команди Git"""
        try:
            # Додаємо файл в індекс
            subprocess.run(["git", "add", self.data_file], check=True)
            
            # Робимо коміт з поточною датою
            commit_msg = f"Update stats: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            
            # Відправляємо в репозиторій
            subprocess.run(["git", "push"], check=True)
            print("🚀 GitHub успішно оновлено!")
            
        except Exception as e:
            print(f"Помилка синхронізації з GitHub: {e}")

    async def run_full_collect_process(self, interaction=None):
        """Основна логіка роботи бота"""
        
        # Шукаємо лінк
        url = await self.find_url_in_thread()
        if not url:
            if interaction:
                await interaction.followup.send("❌ Посилання на Garmoth не знайдено.")
            return

        # Збираємо дані
        stats = await self.get_stats(url)
        
        if stats:
            # Витягуємо нікнейм того, хто натиснув команду (або за замовчуванням)
            user_nick = "Користувач"
            if interaction:
                user_nick = interaction.user.display_name # Ім'я з сервера Discord
            
            stats["Name"] = user_nick

            # Формуємо красивий текст для відповіді в Discord
            display_message = (
                f"👤 **Персонаж:** `{user_nick}`\n"
                f"⚔️ **AP:** {stats['AP']} | **AAP:** {stats['AAP']}\n"
                f"🛡️ **DP:** {stats['DP']}\n"
                f"🌟 **Total GS:** {stats['GS']}\n"
                f"🕒 _Час збору: {stats['time']}_\n"
                f"🚀 Результати успішно відправлено на GitHub."
            )

            # Робота з файлом історії
            all_data = []
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    raw_content = f.read()
                    # Якщо файл не порожній, завантажуємо дані
                    if raw_content.strip():
                        all_data = json.loads(raw_content)
            except (FileNotFoundError, json.JSONDecodeError):
                # Якщо файлу немає — створимо новий список
                print("Файл не знайдено або він пустий. Починаємо новий запис.")

            # Додаємо свіжий запис
            all_data.append(stats)

            # Зберігаємо оновлену історію в JSON з відступами
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=4, ensure_ascii=False)
            
            # Відправляємо зміни на GitHub
            self.push_to_github()

            # Надсилаємо фінальну відповідь у чат
            if interaction:
                await interaction.followup.send(display_message)
                
        else:
            if interaction:
                await interaction.followup.send("❌ Помилка: Не вдалося отримати цифри з сайту.")

    @app_commands.command(name="collect", description="Зібрати статси Garmoth зараз")
    async def collect(self, interaction: discord.Interaction):
        """Команда /collect"""
        # Повідомляємо Discord, що бот почав думати
        await interaction.response.defer()
        # Запускаємо весь процес
        await self.run_full_collect_process(interaction)

async def setup(bot):
    await bot.add_cog(DataCollector(bot))
