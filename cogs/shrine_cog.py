import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import time as time_module
from datetime import datetime, timedelta
from pathlib import Path

# Шляхи до файлів
GS_PATH = Path("data/player_gs.json")
WEEKLY_PATH = Path("data/shrine_weekly.json")
VACATION_PATH = Path("data/vacations.json")
SCHEDULE_PATH = Path("data/schedule.json")

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
        # Визначаємо шлях залежно від ключа
        paths = {"gs": GS_PATH, "schedule": SCHEDULE_PATH, "vacation": VACATION_PATH}
        path = paths.get(self.key, GS_PATH)
        
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
        options=[discord.SelectOption(label=f"{i} бос(ів)", value=str(i)) for i in range(1, 6)],
        custom_id="shrine_boss_select"
    )
    async def select_bosses(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_message(f"👌 Записано: {select.values[0]} босів.", ephemeral=True)

    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="dm_set_gs")
    async def set_gs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Гір Скор", "Введіть ваш GS", "Наприклад: 720", "gs", self.cog))

    @discord.ui.button(label="Мій графік", style=discord.ButtonStyle.secondary, emoji="⏳", custom_id="dm_set_sched")
    async def set_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Графік", "Коли ви в грі?", "Наприклад: 10:00 - 23:00", "schedule", self.cog))

    @discord.ui.button(label="Відпустка", style=discord.ButtonStyle.gray, emoji="🌴", custom_id="dm_set_vac")
    async def set_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Відпустка", "Період", "Наприклад: 15.02 - 20.02", "vacation", self.cog))

# --- СЕЛЕКТ ДЛЯ ПЕРЕДАЧІ ЛІДЕРА ---
class LeaderSelect(discord.ui.Select):
    def __init__(self, members, view, bot):
        self.party_view = view
        self.bot = bot
        options = []
        for m_id in members:
            if m_id == view.leader_id: continue
            user = bot.get_user(m_id)
            name = user.display_name if user else f"ID: {m_id}"
            options.append(discord.SelectOption(label=name, value=str(m_id), emoji="👑"))
        super().__init__(placeholder="Оберіть нового лідера...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.party_view.leader_id:
            return await interaction.response.send_message("Тільки лідер може це зробити!", ephemeral=True)
        self.party_view.leader_id = int(self.values[0])
        await self.party_view.update_embed(interaction)
        await interaction.followup.send(f"✅ Новим лідером призначено <@{self.party_view.leader_id}>", ephemeral=True)

# --- ВІКНО КЕРУВАННЯ РЕЙДОМ ---
class ShrinePartyView(discord.ui.View):
    def __init__(self, leader_id, boss, count, ts, cog):
        super().__init__(timeout=None)
        self.leader_id = leader_id
        self.members = [leader_id]
        self.boss = boss
        self.count = count
        self.ts = ts
        self.cog = cog

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.blurple, custom_id="shrine_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members: return
        if len(self.members) >= 5: return
        self.members.append(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.red, custom_id="shrine_leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.members: return
        if interaction.user.id == self.leader_id and len(self.members) > 1:
            return await interaction.response.send_message("Передайте ПЛ перед виходом!", ephemeral=True)
        self.members.remove(interaction.user.id)
        if not self.members:
            if interaction.message.thread:
                try: await interaction.message.thread.delete()
                except: pass
            await interaction.message.delete()
            return
        await self.update_embed(interaction)

    @discord.ui.button(label="Передати ПЛ", style=discord.ButtonStyle.gray, emoji="👑", custom_id="shrine_delegate")
    async def delegate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id: return
        if len(self.members) < 2: return
        view = discord.ui.View(timeout=60)
        view.add_item(LeaderSelect(self.members, self, self.cog.bot))
        await interaction.response.send_message("Оберіть нового лідера:", view=view, ephemeral=True)

    @discord.ui.button(label="✅ Завершити", style=discord.ButtonStyle.green, custom_id="shrine_finish")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id: return
        if interaction.message.thread:
            try: await interaction.message.thread.delete()
            except: pass
        await interaction.message.delete()

    async def update_embed(self, interaction):
        if not interaction.message.embeds: return
        embed = interaction.message.embeds[0].copy()
        gs_data = self.cog.load_json(GS_PATH)
        weekly = self.cog.load_json(WEEKLY_PATH)
        
        member_list = []
        for m_id in self.members:
            prefix = "👑 " if m_id == self.leader_id else "⚔️ "
            m_gs = gs_data.get(str(m_id), "??")
            m_left = 5 - weekly.get(str(m_id), 0)
            member_list.append(f"{prefix}<@{m_id}> [GS: **{m_gs}** | Зал: **{max(0, m_left)}**]")

        embed.description = f"Лідер: <@{self.leader_id}>\nБосів: **{self.count}**\nЧас: <t:{self.ts}:t> (<t:{self.ts}:R>)"
        embed.set_field_at(0, name=f"Учасники ({len(self.members)}/5)", value="\n".join(member_list), inline=False)
        
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

# --- ОСНОВНИЙ COG ---
class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077
        self.report_channel_id = 1421625193134166200
        self.guild_id = 1335930065090641971

    async def cog_load(self):
        if not self.scheduler.is_running():
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
        
        # Ранкова розсилка о 09:00
        if now == "09:00":
            await self.run_dm_polling()

        # Звіт у канал о 15:00 та о 15:15
        if now in ["15:00", "15:15"]:
            await self.send_daily_report()

    async def run_dm_polling(self):
        guild = self.bot.get_guild(self.guild_id)
        role = guild.get_role(self.role_id) if guild else None
        if not role: return

        weekly = self.load_json(WEEKLY_PATH)
        gs_data = self.load_json(GS_PATH)
        vacations = self.load_json(VACATION_PATH)

        for member in role.members:
            uid = str(member.id)
            if member.bot or uid in vacations or weekly.get(uid, 0) >= 5: continue
            
            try:
                embed = discord.Embed(
                    title="Вітаю Вас! Нагадую за босів Black Shrine!",
                    description=f"Ваш GS: **{gs_data.get(uid, '??')}**\nНе пройдено: **{5 - weekly.get(uid, 0)}**\n\nОберіть ваші плани:",
                    color=0x2ecc71
                )
                embed.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/PolosBir.gif?raw=true")
                embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
                await member.send(embed=embed, view=PollResponseView(self))
            except discord.Forbidden:
                pass

    async def send_daily_report(self):
        channel = self.bot.get_channel(self.report_channel_id)
        if not channel: return

        weekly = self.load_json(WEEKLY_PATH)
        gs_data = self.load_json(GS_PATH)
        sched_data = self.load_json(SCHEDULE_PATH)
        guild = self.bot.get_guild(self.guild_id)
        role = guild.get_role(self.role_id) if guild else None
        
        if not role: return

        report = "📊 **Звіт про статус Black Shrine:**\n\n"
        for member in role.members:
            if member.bot: continue
            uid = str(member.id)
            done = weekly.get(uid, 0)
            gs = gs_data.get(uid, "??")
            sched = sched_data.get(uid, "Не вказано")
            
            status_icon = "✅" if done >= 5 else "⏳"
            report += f"{status_icon} **{member.display_name}** | GS: `{gs}` | Боси: `{done}/5` | Графік: *{sched}*\n"

        await channel.send(report)

    @app_commands.command(name="shrine_create", description="Створити рейд")
    async def shrine_create(self, interaction: discord.Interaction, boss: str, count: int, time_hhmm: int):
        try:
            now = datetime.now()
            h, m = time_hhmm // 100, time_hhmm % 100
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target < now: target += timedelta(days=1)
            ts = int(time_module.mktime(target.timetuple()))
        except:
            return await interaction.response.send_message("❌ Невірний час!", ephemeral=True)

        gs_data = self.load_json(GS_PATH)
        weekly = self.load_json(WEEKLY_PATH)
        my_gs = gs_data.get(str(interaction.user.id), "??")
        my_left = 5 - weekly.get(str(interaction.user.id), 0)

        embed = discord.Embed(title=f"⚔️ Black Shrine: {boss}", color=0x2ecc71)
        embed.description = f"Лідер: {interaction.user.mention}\nБосів: **{count}**\nЧас: <t:{ts}:t> (<t:{ts}:R>)"
        embed.add_field(name="Учасники (1/5)", value=f"👑 {interaction.user.mention} [GS: **{my_gs}** | Зал: **{max(0, my_left)}**]", inline=False)
        
        view = ShrinePartyView(interaction.user.id, boss, count, ts, self)
        await interaction.response.send_message(embed=embed, view=view)
        
        msg = await interaction.original_response()
        try: await msg.create_thread(name=f"Рейд {boss}")
        except: pass

async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
