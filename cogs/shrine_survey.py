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
    if not os.path.exists("data"): 
        os.makedirs("data")
    data = []
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    user_found = False
    for entry in data:
        if entry.get('user_id') == user_id:
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
        if 'bosses_done' in kwargs: kwargs.pop('bosses_done')
        new_entry.update(kwargs)
        data.append(new_entry)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_gs(user_id):
    """Отримує ГС з локального звіту"""
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for r in data:
                if r.get('user_id') == user_id:
                    return f"{r.get('ap', '??')}/{r.get('dp', '??')}"
    return "??/??"

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
        new_leader = interaction.guild.get_member(new_leader_id)
        old_leader = self.view_lfg.leader
        self.view_lfg.leader = new_leader
        self.view_lfg.members.remove(old_leader)
        await interaction.response.edit_message(content=f"👑 Новий ПЛ: {new_leader.mention}", embed=await self.view_lfg.build_embed(), view=self.view_lfg)

# --- LFG SYSTEM ---

class ShrineLFG(discord.ui.View):
    def __init__(self, leader, boss_name, start_time, bosses_count, mode):
        super().__init__(timeout=None)
        self.leader = leader
        self.boss_name = boss_name
        self.start_time = start_time
        self.bosses_count = bosses_count
        self.mode = mode
        self.members = [leader]

    async def build_embed(self):
        color = discord.Color.from_rgb(75, 0, 130) if self.mode == "Hard" else discord.Color.from_rgb(100, 149, 237)
        embed = discord.Embed(
            title=f"🏮 Black Shrine: {self.boss_name} ({self.mode})",
            description=f"**ПЛ:** {self.leader.mention}\n**Час:** {self.start_time}\n**Босів:** {self.bosses_count}",
            color=color
        )
        
        m_list = []
        for m in self.members:
            gs = get_user_gs(m.id)
            icon = '👑' if m == self.leader else '⚔️'
            m_list.append(f"{icon} {m.display_name} [`{gs}`]")
            
        embed.add_field(name=f"Група ({len(self.members)}/5)", value="\n".join(m_list))
        embed.set_image(url=BG_IMAGE)
        return embed

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.success, emoji="⚔️")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.members: return await interaction.response.send_message("Ви вже у групі!", ephemeral=True)
        if len(self.members) >= 5: return await interaction.response.send_message("Група заповнена!", ephemeral=True)
        self.members.append(interaction.user)
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Вийти / Замінитись", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.members: return await interaction.response.send_message("Вас немає в групі.", ephemeral=True)
        if interaction.user == self.leader:
            if len(self.members) > 1:
                t_view = discord.ui.View(); t_view.add_item(LeaderTransferSelect(self.members, self))
                return await interaction.response.send_message("Призначте нового ПЛ перед виходом:", view=t_view, ephemeral=True)
            else:
                if interaction.message.thread: await interaction.message.thread.delete()
                return await interaction.response.edit_message(content="❌ Паті видалено.", embed=None, view=None)
        
        self.members.remove(interaction.user)
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    @discord.ui.button(label="Завершити", style=discord.ButtonStyle.danger, emoji="🏁")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.leader: return await interaction.response.send_message("Тільки ПЛ!", ephemeral=True)
        for m in self.members:
            await update_report(m.id, m.display_name, bosses_done=self.bosses_count)
        
        if interaction.message.thread:
            await interaction.message.thread.delete()
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Похід завершено! {self.bosses_count} босів додано всім.", ephemeral=True)

# --- MAIN COG ---

class ShrineSurvey(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_thread_id = 1358443998603120824
        # Розклад (UTC +2 зазвичай для Києва, підправ за потреби)
        self.morning_cron = aiocron.crontab('0 7 * * *', func=self.send_daily_survey)
        self.afternoon_cron = aiocron.crontab('0 13 * * *', func=self.send_daily_survey)
        self.report_cron = aiocron.crontab('15 13 * * *', func=self.post_guild_report)
        self.cleanup_cron = aiocron.crontab('0 22 * * *', func=self.cleanup_thread)

    async def send_daily_survey(self):
        guild = self.bot.guilds[0]
        role = guild.get_role(1406569206815658077)
        reports = []
        if os.path.exists(REPORT_FILE):
            with open(REPORT_FILE, "r", encoding="utf-8") as f: reports = json.load(f)

        for m in role.members:
            user_report = next((r for r in reports if r.get('user_id') == m.id), None)
            if user_report and (user_report.get('status') in ['skip', 'vacation'] or user_report.get('bosses_done', 0) >= 5):
                continue
            
            gs = get_user_gs(m.id)
            embed = discord.Embed(title="Black Shrine Нагадування", description=f"Ваш ГС: **{gs}**\nОберіть дію:", color=discord.Color.from_rgb(0, 255, 191))
            embed.set_image(url=BG_IMAGE)
            try: await m.send(embed=embed, view=ShrineSurveyView())
            except: pass

    async def post_guild_report(self, channel_override=None):
        channel = channel_override or self.bot.get_channel(self.target_thread_id)
        if not channel or not os.path.exists(REPORT_FILE): return
        with open(REPORT_FILE, "r", encoding="utf-8") as f: reports = json.load(f)
        
        embed = discord.Embed(title="📊 Страждущі на сьогодні", color=discord.Color.from_rgb(0, 255, 191))
        embed.set_image(url=BG_IMAGE)
        found = False
        for r in reports:
            if r.get('status') == 'active' and r.get('bosses_done', 0) < 5:
                embed.add_field(name=r['name'], value=f"⚙️ GS: {r.get('ap','?')}/{r.get('dp','?')}\n👾 Босів залишилось: {5-r['bosses_done']}\n⏳ Час: {r['schedule']}", inline=False)
                found = True
        if found: await channel.send(embed=embed)

    async def cleanup_thread(self):
        channel = self.bot.get_channel(self.target_thread_id)
        if channel:
            async for m in channel.history(limit=100):
                if m.author == self.bot.user: await m.delete()

    @app_commands.command(name="shrine_party", description="Створити збір на босів")
    @app_commands.choices(
        boss=[
            app_commands.Choice(name="Jigwi (Джигві)", value="Jigwi"),
            app_commands.Choice(name="Blue-clad Youth (Хлопчик в трусіках)", value="Blue-clad Youth"),
            app_commands.Choice(name="Bulgasal (Бульгазар)", value="Bulgasal"),
            app_commands.Choice(name="Uturi (Утурі)", value="Uturi"),
            app_commands.Choice(name="Dark Bonghwang (Фенікс)", value="Dark Bonghwang"),
            app_commands.Choice(name="Bihyung (Дід)", value="Bihyung"),
            app_commands.Choice(name="Crown Prince (Принц)", value="Deposed Crown Prince")
        ],
        mode=[
            app_commands.Choice(name="Normal Mode", value="Normal"),
            app_commands.Choice(name="Hard Mode", value="Hard")
        ]
    )
    async def shrine_party(self, interaction: discord.Interaction, boss: str, mode: str, start_time: str, count: int):
        if not (1 <= count <= 5): return await interaction.response.send_message("Кількість босів: від 1 до 5", ephemeral=True)
        view = ShrineLFG(interaction.user, boss, start_time, count, mode)
        await interaction.response.send_message(embed=await view.build_embed(), view=view)
        
        msg = await interaction.original_response()
        await msg.create_thread(name=f"Паті на {boss}", auto_archive_duration=60)

    @app_commands.command(name="shrine_test", description="Тестовий запуск (Модератори)")
    async def shrine_test(self, interaction: discord.Interaction):
        if not any(role.id == 1375070910138028044 for role in interaction.user.roles):
            return await interaction.response.send_message("❌ Немає прав!", ephemeral=True)
        await interaction.response.send_message("🚀 Тест запущено...", ephemeral=True)
        await self.send_daily_survey()
        await self.post_guild_report(channel_override=interaction.channel)

class ShrineSurveyView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def gs(self, interaction: discord.Interaction, b: discord.ui.Button): await interaction.response.send_modal(GSModal())
    @discord.ui.button(label="Графік", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def sched(self, interaction: discord.Interaction, b: discord.ui.Button): await interaction.response.send_modal(ScheduleModal())
    @discord.ui.button(label="Пропуск", style=discord.ButtonStyle.danger, emoji="❌")
    async def skip(self, interaction: discord.Interaction, b: discord.ui.Button):
        await update_report(interaction.user.id, interaction.user.display_name, status="skip")
        await interaction.response.send_message("Зрозумів, сьогодні не турбую!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ShrineSurvey(bot))
