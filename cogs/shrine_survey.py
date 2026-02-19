import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import aiocron
import datetime
import time

# Шляхи до файлів
HISTORY_FILE = "data/garmoth_history.json"
REPORT_FILE = "data/shrine_weekly_report.json"
BG_IMAGE = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/a8b01adbd7a20240828071624343.jpg?raw=true"

# --- UTILS ---

async def update_report(user_id, display_name, **kwargs):
    """Оновлює дані в JSON: ГС, статус, графік та кількість босів"""
    if not os.path.exists("data"): 
        os.makedirs("data")
    data = []
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    user_found = False
    for entry in data:
        if entry.get('user_id') == user_id:
            # Якщо додаємо босів, то плюсуємо до існуючих
            if 'bosses_done' in kwargs:
                entry['bosses_done'] = entry.get('bosses_done', 0) + kwargs['bosses_done']
                kwargs.pop('bosses_done')
            entry.update(kwargs)
            entry['last_update'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            user_found = True
            break
    
    if not user_found:
        new_entry = {
            "user_id": user_id,
            "name": display_name,
            "status": "active",
            "bosses_done": kwargs.get('bosses_done', 0),
            "schedule": "Не вказано",
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        if 'bosses_done' in kwargs: 
            kwargs.pop('bosses_done')
        new_entry.update(kwargs)
        data.append(new_entry)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- MODALS & SELECTS ---

class GSModal(discord.ui.Modal, title="Оновлення ГС"):
    ap = discord.ui.TextInput(label="Ваш AP", placeholder="310", max_length=3)
    dp = discord.ui.TextInput(label="Ваш DP", placeholder="401", max_length=3)
    async def on_submit(self, interaction: discord.Interaction):
        await update_report(interaction.user.id, interaction.user.display_name, ap=self.ap.value, dp=self.dp.value)
        await interaction.response.send_message("✅ Ваш ГС успішно оновлено!", ephemeral=True)

class ScheduleModal(discord.ui.Modal, title="Ваш графік"):
    time_slot = discord.ui.TextInput(label="Коли зможете бути?", placeholder="19:00 - 21:00")
    async def on_submit(self, interaction: discord.Interaction):
        await update_report(interaction.user.id, interaction.user.display_name, schedule=self.time_slot.value)
        await interaction.response.send_message("✅ Час записано в базу!", ephemeral=True)

class LeaderTransferSelect(discord.ui.Select):
    def __init__(self, members, view_lfg):
        options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members if m.id != view_lfg.leader.id]
        super().__init__(placeholder="Оберіть нового лідера...", options=options)
        self.view_lfg = view_lfg

    async def callback(self, interaction: discord.Interaction):
        new_leader_id = int(self.values[0])
        new_leader = next(m for m in self.view_lfg.members if m.id == new_leader_id)
        old_leader = self.view_lfg.leader
        self.view_lfg.leader = new_leader
        self.view_lfg.members.remove(old_leader)
        await interaction.response.edit_message(content=f"👑 Новий ПЛ: {new_leader.mention}", embed=await self.view_lfg.build_embed(), view=self.view_lfg)

# --- LFG SYSTEM ---

class ShrineLFG(discord.ui.View):
    def __init__(self, leader, boss_name, start_time, bosses_count):
        super().__init__(timeout=None)
        self.leader = leader
        self.boss_name = boss_name
        self.start_time = start_time
        self.bosses_count = bosses_count
        self.members = [leader]

    async def build_embed(self):
        embed = discord.Embed(
            title=f"🏮 Black Shrine: {self.boss_name}",
            description=f"**ПЛ:** {self.leader.mention}\n**Час:** {self.start_time}\n**Босів:** {self.bosses_count}",
            color=discord.Color.from_rgb(75, 0, 130)
        )
        m_list = "\n".join([f"• {m.display_name} {'👑' if m == self.leader else ''}" for m in self.members])
        embed.add_field(name=f"Група ({len(self.members)}/5)", value=m_list)
        embed.set_image(url=BG_IMAGE)
        return embed

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.success, emoji="⚔️")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.members: 
            return await interaction.response.send_message("Ви вже у групі!", ephemeral=True)
        if len(self.members) >= 5: 
            return await interaction.response.send_message("Група заповнена!", ephemeral=True)
        self.members.append(interaction.user)
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Вийти / Замінитись", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.members: 
            return await interaction.response.send_message("Вас немає в групі.", ephemeral=True)
        if interaction.user == self.leader:
            if len(self.members) > 1:
                t_view = discord.ui.View()
                t_view.add_item(LeaderTransferSelect(self.members, self))
                return await interaction.response.send_message("Призначте нового ПЛ перед виходом:", view=t_view, ephemeral=True)
            else:
                return await interaction.response.edit_message(content="❌ Паті видалено.", embed=None, view=None)
        self.members.remove(interaction.user)
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Завершити", style=discord.ButtonStyle.danger, emoji="🏁")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.leader: 
            return await interaction.response.send_message("Тільки ПЛ!", ephemeral=True)
        for m in self.members:
            await update_report(m.id, m.display_name, bosses_done=self.bosses_count)
        await interaction.response.send_message("✅ Похід завершено, дані збережено.", ephemeral=True)
        await interaction.message.delete()

# --- SURVEY VIEW ---

class ShrineSurveyView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)
    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def gs(self, interaction: discord.Interaction, b: discord.ui.Button): 
        await interaction.response.send_modal(GSModal())
    @discord.ui.button(label="Графік", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def sched(self, interaction: discord.Interaction, b: discord.ui.Button): 
        await interaction.response.send_modal(ScheduleModal())
    @discord.ui.button(label="Пропуск", style=discord.ButtonStyle.danger, emoji="❌")
    async def skip(self, interaction: discord.Interaction, b: discord.ui.Button):
        await update_report(interaction.user.id, interaction.user.display_name, status="skip")
        await interaction.response.send_message("Зрозумів, сьогодні не турбую!", ephemeral=True)

# --- MAIN COG ---

class ShrineSurvey(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_thread_id = 1358443998603120824
        self.morning_cron = aiocron.crontab('0 7 * * *', func=self.send_daily_survey)
        self.afternoon_cron = aiocron.crontab('0 13 * * *', func=self.send_daily_survey)
        self.report_cron = aiocron.crontab('15 13 * * *', func=self.post_guild_report)
        self.cleanup_cron = aiocron.crontab('0 22 * * *', func=self.cleanup_thread)

    async def send_daily_survey(self):
        guild = self.bot.guilds[0]
        role = guild.get_role(1406569206815658077)
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: 
                history = json.load(f)
        
        reports = []
        if os.path.exists(REPORT_FILE):
            with open(REPORT_FILE, "r", encoding="utf-8") as f:
                reports = json.load(f)

        for m in role.members:
            user_report = next((r for r in reports if r.get('user_id') == m.id), None)
            if user_report:
                if user_report.get('status') in ['skip', 'vacation'] or user_report.get('bosses_done', 0) >= 5:
                    continue

            char = next((c for c in history if c.get('Name') == m.display_name), None)
            gs_display = f"{char['AP']}/{char['DP']}" if char else "Не знайдено (натисніть 'Мій GS')"
            embed = discord.Embed(title="Black Shrine Нагадування", description=f"Ваш ГС: **{gs_display}**\nОберіть дію:", color=discord.Color.from_rgb(0, 255, 191))
            embed.set_image(url=BG_IMAGE)
            try: 
                await m.send(embed=embed, view=ShrineSurveyView())
            except: 
                pass

    async def post_guild_report(self, channel_override=None):
        channel = channel_override or self.bot.get_channel(self.target_thread_id)
        if not channel or not os.path.exists(REPORT_FILE): 
            return
        with open(REPORT_FILE, "r", encoding="utf-8") as f: 
            reports = json.load(f)
        
        embed = discord.Embed(title="📊 Страждущі на сьогодні", color=discord.Color.from_rgb(0, 255, 191))
        embed.set_image(url=BG_IMAGE)
        found = False
        for r in reports:
            if r.get('status') == 'active' and r.get('bosses_done', 0) < 5:
                embed.add_field(name=r['name'], value=f"⚙️ GS: {r.get('ap','?')}/{r.get('dp','?')}\n👾 Босів залишилось: {5-r['bosses_done']}\n⏳ Час: {r['schedule']}", inline=False)
                found = True
        
        if found:
            await channel.send(embed=embed)

    async def cleanup_thread(self):
        channel = self.bot.get_channel(self.target_thread_id)
        if channel:
            async for m in channel.history(limit=100):
                if m.author == self.bot.user: 
                    await m.delete()

    @app_commands.command(name="shrine_party", description="Створити збір на босів")
    @app_commands.choices(boss=[
        app_commands.Choice(name="Фенікс (Bonghwang)", value="Dark Bonghwang"),
        app_commands.Choice(name="Принц (Crown Prince)", value="Deposed Crown Prince"),
        app_commands.Choice(name="Утурі (Uturi)", value="Uturi"),
        app_commands.Choice(name="Бульга (Bulgasal)", value="Bulgasal"),
        app_commands.Choice(name="Мальчик в трусіках (Blue-clad)", value="Blue-clad Youth"),
        app_commands.Choice(name="Джигви (Jigwi)", value="Jigwi"),
        app_commands.Choice(name="Дід (Bihyung)", value="Bihyung")
    ])
    async def shrine_party(self, interaction: discord.Interaction, boss: str, start_time: str, count: int):
        if not (1 <= count <= 5): 
            return await interaction.response.send_message("Кількість босів: від 1 до 5", ephemeral=True)
        view = ShrineLFG(interaction.user, boss, start_time, count)
        await interaction.response.send_message(embed=await view.build_embed(), view=view)

    @app_commands.command(name="shrine_test", description="Тестовий запуск (тільки Модератори)")
    async def shrine_test(self, interaction: discord.Interaction):
        mod_role_id = 1375070910138028044
        if not any(role.id == mod_role_id for role in interaction.user.roles):
            return await interaction.response.send_message("❌ Недостатньо прав!", ephemeral=True)
        
        await interaction.response.send_message("🚀 Запуск тесту...", ephemeral=True)
        await self.send_daily_survey()
        await self.post_guild_report(channel_override=interaction.channel)

async def setup(bot):
    await bot.add_cog(ShrineSurvey(bot))
