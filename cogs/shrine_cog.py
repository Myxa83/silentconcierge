import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Шляхи до файлів
DATA_PATH = Path("data/shrine_parties.json")
WEEKLY_PATH = Path("data/shrine_weekly.json")
LOG_PATH = Path("logs/shrine_events.json")

class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077 # Роль Страждущі
        self.report_channel_id = 1421625193134166200 # Основний канал
        self.test_channel_id = 1370522199873814528   # Тестовий канал
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()

    # --- Утиліти для роботи з даними ---
    def load_json(self, path):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_json(self, data, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def log_event(self, text):
        logs = self.load_json(LOG_PATH) if LOG_PATH.exists() else []
        logs.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": text
        })
        self.save_json(logs[-500:], LOG_PATH)

    def get_unix_time(self, time_str):
        try:
            now = datetime.now()
            t = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            return int(t.timestamp())
        except:
            return None

    # --- Головний розклад (Scheduler) ---
    @tasks.loop(minutes=1)
    async def scheduler(self):
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M")
        weekday = now_dt.weekday() # 0=Пн, 5=Сб, 6=Нд

        # 1. Скидання тижня: в ніч з суботи на неділю (Неділя, 00:01)
        if weekday == 6 and now_str == "00:01":
            await self.reset_weekly_progress()
        
        # 2. Ранкове опитування (09:00)
        if now_str == "09:00":
            # У суботу (5) бот нагадує, що це останній день
            await self.run_dm_polling(is_saturday=(weekday == 5))

        # 3. Денне нагадування (15:00)
        if now_str == "15:00":
            await self.run_dm_polling(is_reminder=True)

        # 4. Щоденний звіт (15:15)
        if now_str == "15:15":
            await self.post_daily_report()

    async def reset_weekly_progress(self):
        empty = {}
        self.save_json(empty, WEEKLY_PATH)
        self.log_event("СИСТЕМА: Тижневий прогрес скинуто (Неділя).")
        channel = self.bot.get_channel(self.report_channel_id)
        if channel:
            await channel.send("♻️ Системне повідомлення: Почався новий тиждень! Всі ліміти Black Shrine скинуто.")

    # --- Логіка опитування в DM ---
    async def run_dm_polling(self, is_reminder=False, is_saturday=False):
        guild = self.bot.guilds[0]
        role = guild.get_role(self.role_id)
        if not role: return

        weekly = self.load_json(WEEKLY_PATH)
        
        msg = "Вітаю! Коли плануєш йти на Black Shrine сьогодні?"
        if is_saturday:
            msg = "🚨 Увага! Сьогодні субота — останній день тижня для Black Shrine! Встигни закрити 5/5."
        if is_reminder:
            msg = "Нагадую: ти ще не записався у список на сьогодні, а ліміти ще не закриті!"

        for member in role.members:
            uid = str(member.id)
            # Якщо вже 5/5 — бот не турбує
            if weekly.get(uid, 0) >= 5:
                continue

            try:
                view = discord.ui.View()
                btn = discord.ui.Button(label="Перейти до каналу збору", style=discord.ButtonStyle.link, url=f"https://discord.com/channels/{guild.id}/{self.report_channel_id}")
                view.add_item(btn)
                await member.send(msg, view=view)
            except:
                continue

    # --- Команда для тесту DM ---
    @app_commands.command(name="shrine_test_dm", description="Тест DM для Пані Мушки")
    async def shrine_test_dm(self, interaction: discord.Interaction):
        target_ids = [interaction.user.id, 892107885482491945]
        sent_to = []
        for uid in target_ids:
            try:
                user = await self.bot.fetch_user(uid)
                view = ConfirmProgressView("Тестовий Бос", 1, self)
                await user.send(
                    "🧪 Тестове повідомлення! Підтвердіть проходження для перевірки системи.",
                    view=view
                )
                sent_to.append(user.display_name)
            except:
                sent_to.append(f"Помилка {uid}")
        await interaction.response.send_message(f"✅ Тест надіслано: {', '.join(sent_to)}", ephemeral=True)

    # --- Команди створення рейду ---
    @app_commands.command(name="shrine_create", description="Створити нову пачку на Black Shrine")
    @app_commands.choices(boss=[
        app_commands.Choice(name="Jigwi (Джигві)", value="Jigwi"),
        app_commands.Choice(name="Blue-clad Youth (Хлопчик)", value="Blue-clad Youth"),
        app_commands.Choice(name="Bulgasal (Бульгазар)", value="Bulgasal"),
        app_commands.Choice(name="Uturi (Утурі)", value="Uturi"),
        app_commands.Choice(name="Dark Bonghwang (Фенікс)", value="Dark Bonghwang"),
        app_commands.Choice(name="The Deposed Crown Prince (Принц)", value="Prince")
    ])
    async def shrine_create(self, interaction: discord.Interaction, boss: app_commands.Choice[str], count: int, time: str):
        if interaction.channel.id not in [self.report_channel_id, self.test_channel_id]:
            return await interaction.response.send_message("Тут не можна створювати рейди!", ephemeral=True)

        unix_time = self.get_unix_time(time)
        if not unix_time:
            return await interaction.response.send_message("Використовуйте формат ЧЧ:ММ (наприклад 19:00)", ephemeral=True)

        embed = discord.Embed(
            title=f"⚔️ Black Shrine: {boss.name}",
            description=f"Лідер: {interaction.user.mention}\nКількість: **{count}**\nЧас збору: <t:{unix_time}:T> (<t:{unix_time}:R>)",
            color=discord.Color.green()
        )
        embed.add_field(name="Учасники (1/5)", value=interaction.user.mention)
        
        view = ShrinePartyView(interaction.user.id, boss.name, count, unix_time, self)
        await interaction.response.send_message(embed=embed, view=view)
        
        msg = await interaction.original_response()
        await msg.create_thread(name=f"Рейд {boss.name} - {time}", auto_archive_duration=60)

    async def post_daily_report(self):
        channel = self.bot.get_channel(self.report_channel_id)
        if channel:
            await channel.send("📊 Звіт по активності Black Shrine оновлено!")

# --- View для керування паті ---
class ShrinePartyView(discord.ui.View):
    def __init__(self, leader_id, boss, count, unix_time, cog):
        super().__init__(timeout=None)
        self.leader_id = leader_id
        self.members = [leader_id]
        self.boss = boss
        self.count = count
        self.cog = cog

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.blurple)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members:
            return await interaction.response.send_message("Ви вже у групі!", ephemeral=True)
        if len(self.members) >= 5:
            return await interaction.response.send_message("Група повна!", ephemeral=True)
        self.members.append(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.leader_id:
            return await interaction.response.send_message("Лідер не може вийти!", ephemeral=True)
        if interaction.user.id in self.members:
            self.members.remove(interaction.user.id)
            await self.update_embed(interaction)

    @discord.ui.button(label="✅ Завершити", style=discord.ButtonStyle.green)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id:
            return await interaction.response.send_message("Тільки лідер завершує рейд!", ephemeral=True)
        
        for member_id in self.members:
            try:
                user = await self.cog.bot.fetch_user(member_id)
                view = ConfirmProgressView(self.boss, self.count, self.cog)
                await user.send(f"🏆 Рейд на **{self.boss}** завершено! Підтвердіть проходження ({self.count}).", view=view)
            except:
                continue

        if interaction.message.thread:
            await interaction.message.thread.delete()

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.greyple()
        embed.title = f"🏁 Рейд ЗАВЕРШЕНО: {self.boss}"
        await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("Рейд завершено!", ephemeral=True)
        self.stop()

    async def update_embed(self, interaction):
        embed = interaction.message.embeds[0]
        mentions = [f"<@{m}>" for m in self.members]
        embed.set_field_at(0, name=f"Учасники ({len(self.members)}/5)", value="\n".join(mentions))
        await interaction.response.edit_message(embed=embed, view=self)

# --- Підтвердження через DM ---
class ConfirmProgressView(discord.ui.View):
    def __init__(self, boss, count, cog):
        super().__init__(timeout=3600)
        self.boss = boss
        self.count = count
        self.cog = cog

    @discord.ui.button(label="✅ Підтвердити", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        weekly = self.cog.load_json(WEEKLY_PATH)
        uid = str(interaction.user.id)
        current = weekly.get(uid, 0)
        weekly[uid] = min(5, current + self.count)
        self.cog.save_json(weekly, WEEKLY_PATH)
        await interaction.response.edit_message(content=f"✅ Прогрес оновлено! ({weekly[uid]}/5)", view=None)

# Функція setup без відступів
async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
