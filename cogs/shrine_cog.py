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

class GSModal(discord.ui.Modal, title="Оновлення Гір Скору"):
    ap = discord.ui.TextInput(label="Атака (AP)", placeholder="310", min_length=1, max_length=3)
    dp = discord.ui.TextInput(label="Захист (DP)", placeholder="410", min_length=1, max_length=3)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        gs_string = f"{self.ap.value}/{self.dp.value}"
        data = self.cog.load_json(GS_PATH)
        data[str(interaction.user.id)] = gs_string
        self.cog.save_json(data, GS_PATH)
        
        embed = discord.Embed(description=f"✅ Дані оновлено: **{gs_string}**", color=0x2ecc71)
        embed.set_footer(text="Silent Concierge", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class BossModal(discord.ui.Modal, title="Скільки босів уже вбито?"):
    count = discord.ui.TextInput(label="Кількість (0-5)", placeholder="Наприклад: 3", min_length=1, max_length=1)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not self.count.value.isdigit() or not (0 <= int(self.count.value) <= 5):
            return await interaction.response.send_message("❌ Введіть число від 0 до 5!", ephemeral=True)
        
        data = self.cog.load_json(WEEKLY_PATH)
        data[str(interaction.user.id)] = int(self.count.value)
        self.cog.save_json(data, WEEKLY_PATH)
        
        embed = discord.Embed(description=f"✅ Дані оновлено. Залишилося: **{5 - int(self.count.value)}**", color=0x3498db)
        embed.set_footer(text="Silent Concierge", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DetailsModal(discord.ui.Modal):
    def __init__(self, title, label, placeholder, key, cog):
        super().__init__(title=title)
        self.key, self.cog = key, cog
        self.user_input = discord.ui.TextInput(
            label=label, placeholder=placeholder,
            style=discord.TextStyle.paragraph if key == "schedule" else discord.TextStyle.short,
            min_length=1, max_length=150
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        paths = {"schedule": SCHEDULE_PATH, "vacation": VACATION_PATH}
        data = self.cog.load_json(paths[self.key])
        data[str(interaction.user.id)] = self.user_input.value
        self.cog.save_json(data, paths[self.key])
        
        embed = discord.Embed(description=f"✅ Збережено: {self.user_input.value}", color=0x2ecc71)
        embed.set_footer(text="Silent Concierge", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- ВІКНО ПИТАННЯ В DM ---

class PollResponseView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Мій GS", style=discord.ButtonStyle.primary, emoji="⚔️", custom_id="dm_gs")
    async def set_gs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GSModal(self.cog))

    @discord.ui.button(label="Графік", style=discord.ButtonStyle.secondary, emoji="⏳", custom_id="dm_sched")
    async def set_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Мій графік", "Вкажіть час (декілька варіантів)", "Напр: 10:00-12:00, 19:00-22:00", "schedule", self.cog))

    @discord.ui.button(label="Пропуск дня", style=discord.ButtonStyle.danger, emoji="✖️", custom_id="dm_skip")
    async def skip_day(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(description="✅ Записано. Сьогодні повідомлень більше не буде.", color=0xe74c3c)
        embed.set_footer(text="Silent Concierge", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Відпустка", style=discord.ButtonStyle.gray, emoji="🌴", custom_id="dm_vac")
    async def set_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DetailsModal("Відпустка", "Період", "Наприклад: 15.02 - 20.02", "vacation", self.cog))

    @discord.ui.button(label="Відмова (Боси)", style=discord.ButtonStyle.gray, emoji="🛑", custom_id="dm_refuse")
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BossModal(self.cog))

# --- ВІКНО КЕРУВАННЯ РЕЙДОМ ---

class ShrinePartyView(discord.ui.View):
    def __init__(self, leader_id, boss, count, ts, cog):
        super().__init__(timeout=None)
        self.leader_id, self.boss, self.count, self.ts, self.cog = leader_id, boss, count, ts, cog
        self.members = [leader_id]

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.blurple, custom_id="shrine_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.members and len(self.members) < 5:
            self.members.append(interaction.user.id)
            await self.update_embed(interaction)
        else:
            await interaction.response.send_message("Ви вже у групі або вона заповнена!", ephemeral=True)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.red, custom_id="shrine_leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members:
            if interaction.user.id == self.leader_id and len(self.members) > 1:
                return await interaction.response.send_message("Передайте ПЛ перед виходом!", ephemeral=True)
            self.members.remove(interaction.user.id)
            if not self.members:
                if interaction.message.thread:
                    try: await interaction.message.thread.delete()
                    except: pass
                return await interaction.message.delete()
            await self.update_embed(interaction)

    @discord.ui.button(label="✅ Завершити", style=discord.ButtonStyle.green, custom_id="shrine_finish")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.leader_id:
            if interaction.message.thread:
                try: await interaction.message.thread.delete()
                except: pass
            await interaction.message.delete()
        else:
            await interaction.response.send_message("Тільки лідер може завершити!", ephemeral=True)

    async def update_embed(self, interaction):
        embed = interaction.message.embeds[0].copy()
        gs_data, weekly = self.cog.load_json(GS_PATH), self.cog.load_json(WEEKLY_PATH)
        m_list = [f"{'👑' if m == self.leader_id else '⚔️'} <@{m}> [GS: **{gs_data.get(str(m), '??')}** | Зал: **{max(0, 5-weekly.get(str(m), 0))}**]" for m in self.members]
        embed.description = f"Лідер: <@{self.leader_id}>\nБосів: **{self.count}**\nЧас: <t:{self.ts}:t> (<t:{self.ts}:R>)"
        embed.set_field_at(0, name=f"Учасники ({len(self.members)}/5)", value="\n".join(m_list), inline=False)
        embed.set_footer(text="Silent Concierge", icon_url=self.cog.bot.user.display_avatar.url)
        await interaction.response.edit_message(embed=embed, view=self)

# --- ОСНОВНИЙ COG ---

class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = 1323454227816906802
        self.role_id = 1406569206815658077
        self.mod_role_id = 1375070910138028044
        self.main_report_channel = 1421625193134166200
        self.test_report_channel = 1370522199873814528

    async def cog_load(self):
        if not self.scheduler.is_running(): self.scheduler.start()

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
        if now == "09:00": await self.run_dm_polling()
        if now in ["15:00", "15:15"]: await self.send_report_to_channel(self.main_report_channel)

    async def run_dm_polling(self, target=None):
        guild = self.bot.get_guild(self.guild_id)
        role = guild.get_role(self.role_id) if guild else None
        if not role: return
        weekly, gs_data, vacations = self.load_json(WEEKLY_PATH), self.load_json(GS_PATH), self.load_json(VACATION_PATH)
        members = [target] if target else role.members
        for m in members:
            if m.bot or str(m.id) in vacations or weekly.get(str(m.id), 0) >= 5: continue
            try:
                embed = discord.Embed(title="Вітаю! Нагадування Black Shrine", 
                                    description=f"Ваш GS: **{gs_data.get(str(m.id), '??')}**\nЗалишилось: **{5-weekly.get(str(m.id), 0)}**", color=0x2ecc71)
                embed.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/PolosBir.gif?raw=true")
                embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
                await m.send(embed=embed, view=PollResponseView(self))
            except: pass

    async def send_report_to_channel(self, channel_id):
        channel = self.bot.get_channel(channel_id)
        if not channel: return
        weekly, gs_data, sched_data = self.load_json(WEEKLY_PATH), self.load_json(GS_PATH), self.load_json(SCHEDULE_PATH)
        guild = self.bot.get_guild(self.guild_id)
        role = guild.get_role(self.role_id) if guild else None
        if not role: return
        
        lines = []
        for m in role.members:
            if m.bot: continue
            uid = str(m.id)
            status = "✅" if weekly.get(uid, 0) >= 5 else "⏳"
            lines.append(f"{status} **{m.display_name}** | GS: `{gs_data.get(uid, '??')}` | Боси: `{weekly.get(uid, 0)}/5` | Графік: *{sched_data.get(uid, 'Не вказано')}*")
        
        embed = discord.Embed(title="📊 Звіт Black Shrine", description="\n".join(lines) if lines else "Порожньо", color=0x3498db)
        embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    @app_commands.command(name="shrine_test", description="Тестування (тільки тестовий канал)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Тест DM (на себе)", value="dm"),
        app_commands.Choice(name="Тест Списків (ТЕСТОВИЙ КАНАЛ)", value="report")
    ])
    async def shrine_test(self, interaction: discord.Interaction, action: str):
        if not any(r.id == self.mod_role_id for r in interaction.user.roles):
            return await interaction.response.send_message("❌ Немає прав!", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if action == "dm":
            await self.run_dm_polling(target=interaction.user)
            await interaction.followup.send("✅ Перевірте DM.")
        else:
            await self.send_report_to_channel(self.test_report_channel)
            await interaction.followup.send(f"✅ Звіт надіслано в <#{self.test_report_channel}>")

    @app_commands.command(name="shrine_create", description="Створити рейд")
    async def shrine_create(self, interaction: discord.Interaction, boss: str, count: int, time_hhmm: int):
        try:
            h, m = time_hhmm // 100, time_hhmm % 100
            target = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
            if target < datetime.now(): target += timedelta(days=1)
            ts = int(time_module.mktime(target.timetuple()))
        except: return await interaction.response.send_message("❌ Формат часу: 1900", ephemeral=True)
        
        gs = self.load_json(GS_PATH).get(str(interaction.user.id), "??")
        left = 5 - self.load_json(WEEKLY_PATH).get(str(interaction.user.id), 0)
        embed = discord.Embed(title=f"⚔️ Black Shrine: {boss}", color=0x2ecc71)
        embed.description = f"Лідер: {interaction.user.mention}\nБосів: **{count}**\nЧас: <t:{ts}:t> (<t:{ts}:R>)"
        embed.add_field(name="Учасники (1/5)", value=f"👑 {interaction.user.mention} [GS: **{gs}** | Зал: **{max(0, left)}**]", inline=False)
        embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
        
        await interaction.response.send_message(embed=embed, view=ShrinePartyView(interaction.user.id, boss, count, ts, self))
        msg = await interaction.original_response()
        try: await msg.create_thread(name=f"Рейд {boss}")
        except: pass

async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
