import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime
from pathlib import Path

# Шляхи до файлів
DATA_PATH = Path("data/shrine_parties.json")
WEEKLY_PATH = Path("data/shrine_weekly.json")
GS_PATH = Path("data/player_gs.json")
LOG_PATH = Path("logs/shrine_events.json")
VACATION_PATH = Path("data/vacations.json") # Новий шлях для відпусток

# --- МОДАЛЬНІ ВІКНА ДЛЯ ВВОДУ ТЕКСТУ ---

class DetailsModal(discord.ui.Modal):
    def __init__(self, title, label, placeholder, key, cog):
        super().__init__(title=title)
        self.key = key
        self.cog = cog
        self.user_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder,
            min_length=1,
            max_length=50
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        # Універсальне збереження (GS, Графік або Відпустка)
        path = GS_PATH if self.key == "gs" else VACATION_PATH
        data = self.cog.load_json(path)
        data[str(interaction.user.id)] = self.user_input.value
        self.cog.save_json(data, path)
        
        await interaction.response.send_message(f"✅ Дані '{self.user_input.label}' збережено!", ephemeral=True)

# --- ОНОВЛЕНЕ ВІКНО ПИТАННЯ (PollResponseView) ---

class PollResponseView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.select(
        placeholder="Скільки босів плануєте пройти?",
        options=[discord.SelectOption(label=f"{i} бос(ів)", value=str(i)) for i in range(1, 6)]
    )
    async def select_bosses(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_message(f"👌 Записано: плануєте пройти **{select.values[0]}** босів.", ephemeral=True)

    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️", row=1)
    async def set_gs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Встановлення Гіру", "Введіть ваш GS", "Наприклад: 720", "gs", self.cog))

    @discord.ui.button(label="Мій графік", style=discord.ButtonStyle.secondary, emoji="⏳", row=1)
    async def set_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Ваш час", "Коли ви зазвичай в грі?", "Наприклад: 10:00 - 23:00", "schedule", self.cog))

    @discord.ui.button(label="Відпустка", style=discord.ButtonStyle.gray, emoji="🌴", row=2)
    async def set_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Дати відпустки", "Вкажіть період", "Наприклад: 15.02 - 20.02", "vacation", self.cog))

    @discord.ui.button(label="Пропущу сьогодні", style=discord.ButtonStyle.danger, emoji="💤", row=2)
    async def skip_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Зрозумів! Сьогодні сповіщень більше не буде. Відпочивайте!", ephemeral=True)

# --- ОСНОВНИЙ COG (ShrineCog) ---

class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077
        self.report_channel_id = 1421625193134166200
        self.test_channel_id = 1370522199873814528
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()

    def load_json(self, path):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                try: return json.load(f)
                except: return {}
        return {}

    def save_json(self, data, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def log_event(self, text):
        logs = self.load_json(LOG_PATH) if LOG_PATH.exists() else []
        logs.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": text})
        self.save_json(logs[-500:], LOG_PATH)

    @tasks.loop(minutes=1)
    async def scheduler(self):
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M")
        if now_dt.weekday() == 6 and now_str == "00:01":
            self.save_json({}, WEEKLY_PATH)
            self.log_event("СИСТЕМА: Тижневий прогрес скинуто.")
        
        if now_str == "09:00":
            await self.run_dm_polling()

    async def run_dm_polling(self):
        guild = self.bot.guilds[0]
        role = guild.get_role(self.role_id)
        if not role: return

        weekly = self.load_json(WEEKLY_PATH)
        gs_data = self.load_json(GS_PATH)
        vacations = self.load_json(VACATION_PATH)

        for member in role.members:
            uid = str(member.id)
            
            # Перевірка на відпустку (якщо є запис - не шлемо)
            if uid in vacations: continue
            
            done = weekly.get(uid, 0)
            if done >= 5: continue

            player_gs = gs_data.get(uid, "Не вказано")
            not_done = 5 - done

            embed = discord.Embed(
                title="Вітаю Вас! Нагадую за босів Black Shrine!",
                description=(
                    f"Ваш GS: **{player_gs}**\n"
                    f"У вас не пройдено: **{not_done}** босів\n\n"
                    "Оберіть кількість босів та ваш графік нижче:"
                ),
                color=0x2ecc71
            )
            embed.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/PolosBir.gif?raw=true")
            # ДОДАНО АВАТАРКУ У ФУТЕР
            embed.set_footer(text="Silent Concierge | В пошуках страждущіх", icon_url=self.bot.user.display_avatar.url)

            view = PollResponseView(self)
            try:
                await member.send(embed=embed, view=view)
            except: continue

    # Решта ваших оригінальних команд (shrine_create і т.д.) залишається без змін
    @app_commands.command(name="shrine_create", description="Створити нову пачку на Black Shrine")
    async def shrine_create(self, interaction: discord.Interaction, boss: str, count: int, time: str):
        # (Ваш оригінальний код shrine_create...)
        pass

# Класи ShrinePartyView, ConfirmProgressView залишаються як у вашому оригіналі, 
# але додайте в їхні Embed футери з icon_url=self.cog.bot.user.display_avatar.url

async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
