import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime
from pathlib import Path

# Шляхи до файлів
GS_PATH = Path("data/player_gs.json")
WEEKLY_PATH = Path("data/shrine_weekly.json")
LOG_PATH = Path("logs/shrine_events.json")
VACATION_PATH = Path("data/vacations.json")
DATA_PATH = Path("data/shrine_parties.json")

# --- МОДАЛЬНІ ВІКНА ---
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
        path = GS_PATH if self.key == "gs" else VACATION_PATH
        data = self.cog.load_json(path)
        data[str(interaction.user.id)] = self.user_input.value
        self.cog.save_json(data, path)
        await interaction.response.send_message(f"✅ Дані збережено: {self.user_input.value}", ephemeral=True)

# --- ВІКНО ПИТАННЯ В DM ---
class PollResponseView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.select(
        placeholder="Скільки босів плануєте пройти?",
        options=[discord.SelectOption(label=f"{i} бос(ів)", value=str(i)) for i in range(1, 6)]
    )
    async def select_bosses(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_message(f"👌 Записано: {select.values[0]} босів.", ephemeral=True)

    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️", row=1)
    async def set_gs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Гір Скор", "Введіть ваш GS", "Наприклад: 720", "gs", self.cog))

    @discord.ui.button(label="Мій графік", style=discord.ButtonStyle.secondary, emoji="⏳", row=1)
    async def set_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Графік", "Коли ви в грі?", "Наприклад: 10:00 - 23:00", "schedule", self.cog))

    @discord.ui.button(label="Відпустка", style=discord.ButtonStyle.gray, emoji="🌴", row=2)
    async def set_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Відпустка", "Період", "Наприклад: 15.02 - 20.02", "vacation", self.cog))

    @discord.ui.button(label="Пропущу", style=discord.ButtonStyle.danger, emoji="💤", row=2)
    async def skip_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Відпочивайте, сьогодні не турбуємо!", ephemeral=True)

# --- ПІДТВЕРДЖЕННЯ ПРОГРЕСУ ---
class ConfirmProgressView(discord.ui.View):
    def __init__(self, count, cog):
        super().__init__(timeout=3600)
        self.count = count
        self.cog = cog

    @discord.ui.button(label="✅ Підтвердити", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        weekly = self.cog.load_json(WEEKLY_PATH)
        uid = str(interaction.user.id)
        weekly[uid] = min(5, weekly.get(uid, 0) + self.count)
        self.cog.save_json(weekly, WEEKLY_PATH)
        await interaction.response.edit_message(content=f"✅ Прогрес оновлено! ({weekly[uid]}/5)", view=None)

# --- КЕРУВАННЯ РЕЙДОМ (ShrinePartyView) ---
class ShrinePartyView(discord.ui.View):
    def __init__(self, leader_id, boss, count, cog):
        super().__init__(timeout=None)
        self.leader_id = leader_id
        self.members = [leader_id]
        self.boss = boss
        self.count = count
        self.cog = cog

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.blurple)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members: return
        if len(self.members) >= 5: return
        self.members.append(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.members: return
        if interaction.user.id == self.leader_id:
            return await interaction.response.send_message("Лідер має видалити рейд!", ephemeral=True)
        self.members.remove(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="✅ Завершити", style=discord.ButtonStyle.green)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id: return
        for m_id in self.members:
            try:
                user = await self.cog.bot.fetch_user(m_id)
                await user.send(f"🏆 Рейд завершено! Підтвердіть проходження **{self.count}** босів.", 
                                view=ConfirmProgressView(self.count, self.cog))
            except: continue
        if interaction.message.thread: await interaction.message.thread.delete()
        await interaction.message.edit(view=None)
        await interaction.response.send_message("Рейд завершено, запити надіслано!", ephemeral=True)

    async def update_embed(self, interaction):
        embed = interaction.message.embeds[0]
        mentions = [f"<@{m}>" for m in self.members]
        embed.set_field_at(0, name=f"Учасники ({len(self.members)}/5)", value="\n".join(mentions))
        await interaction.response.edit_message(embed=embed, view=self)

# --- ОСНОВНИЙ COG ---
class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077
        self.report_channel_id = 1421625193134166200
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

    @tasks.loop(minutes=1)
    async def scheduler(self):
        now = datetime.now().strftime("%H:%M")
        if now == "09:00":
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
            if uid in vacations or weekly.get(uid, 0) >= 5: continue
            
            embed = discord.Embed(
                title="Вітаю Вас! Нагадую за босів Black Shrine!",
                description=f"Ваш GS: **{gs_data.get(uid, 'Не вказано')}**\nНе пройдено: **{5-weekly.get(uid, 0)}**\n\nОберіть ваші плани:",
                color=0x2ecc71
            )
            embed.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/PolosBir.gif?raw=true")
            embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
            try: await member.send(embed=embed, view=PollResponseView(self))
            except: continue

    @app_commands.command(name="shrine_create", description="Створити нову пачку")
    async def shrine_create(self, interaction: discord.Interaction, boss: str, count: int, time: str):
        embed = discord.Embed(
            title=f"⚔️ Black Shrine: {boss}",
            description=f"Лідер: {interaction.user.mention}\nБосів: **{count}**\nЧас: **{time}**",
            color=0x2ecc71
        )
        embed.add_field(name="Учасники (1/5)", value=interaction.user.mention)
        embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
        view = ShrinePartyView(interaction.user.id, boss, count, self)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        await msg.create_thread(name=f"Рейд {boss}", auto_archive_duration=60)

    @commands.command(name="test_dm")
    @commands.has_permissions(administrator=True)
    async def test_dm(self, ctx):
        await self.run_dm_polling()
        await ctx.send("✅ Опитування надіслано!")

async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
