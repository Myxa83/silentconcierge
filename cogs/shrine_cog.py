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

# --- СЕЛЕКТ ДЛЯ ПЕРЕДАЧІ ЛІДЕРА ---
class LeaderSelect(discord.ui.Select):
    def __init__(self, members, view, bot):
        self.party_view = view
        self.bot = bot
        
        options = []
        for m_id in members:
            if m_id == view.leader_id:
                continue
            user = bot.get_user(m_id)
            name = user.display_name if user else f"ID: {m_id}"
            options.append(discord.SelectOption(label=name, value=str(m_id), emoji="👑"))
        
        super().__init__(placeholder="Оберіть нового лідера...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.party_view.leader_id:
            return await interaction.response.send_message("Тільки лідер може це зробити!", ephemeral=True)
        
        new_leader_id = int(self.values[0])
        self.party_view.leader_id = new_leader_id
        
        await self.party_view.update_embed(interaction)
        await interaction.response.send_message(f"✅ Ви призначили <@{new_leader_id}> новим лідером.", ephemeral=True)

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

    @discord.ui.button(label="Приєднатися", style=discord.ButtonStyle.blurple)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members:
            return await interaction.response.send_message("Ви вже у групі!", ephemeral=True)
        if len(self.members) >= 5:
            return await interaction.response.send_message("Група заповнена!", ephemeral=True)
        
        self.members.append(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.members:
            return await interaction.response.send_message("Вас немає у цій групі.", ephemeral=True)

        if interaction.user.id == self.leader_id and len(self.members) > 1:
            return await interaction.response.send_message(
                "Спочатку передайте лідерство іншому учаснику через кнопку '👑 Передати ПЛ'.", 
                ephemeral=True
            )

        self.members.remove(interaction.user.id)
        
        if not self.members:
            if interaction.message.thread:
                try: await interaction.message.thread.delete()
                except: pass
            try: await interaction.message.delete()
            except: pass
            return

        await self.update_embed(interaction)

    @discord.ui.button(label="Передати ПЛ", style=discord.ButtonStyle.gray, emoji="👑")
    async def delegate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id:
            return await interaction.response.send_message("Тільки лідер може передати права!", ephemeral=True)
        
        if len(self.members) < 2:
            return await interaction.response.send_message("У групі немає кому передавати лідерство.", ephemeral=True)

        select_view = discord.ui.View(timeout=60)
        select_view.add_item(LeaderSelect(self.members, self, self.cog.bot))
        await interaction.response.send_message("Кому передати корону?", view=select_view, ephemeral=True)

    @discord.ui.button(label="✅ Завершити", style=discord.ButtonStyle.green)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.leader_id:
            return await interaction.response.send_message("Тільки лідер може завершити рейд!", ephemeral=True)
        
        if interaction.message.thread:
            try: await interaction.message.thread.delete()
            except: pass
        try: await interaction.message.delete()
        except: pass

    async def update_embed(self, interaction):
        if not interaction.message.embeds: return
        embed = interaction.message.embeds[0].copy()
        
        gs_data = self.cog.load_json(GS_PATH)
        weekly = self.cog.load_json(WEEKLY_PATH)
        
        member_list = []
        for m_id in self.members:
            prefix = "👑 " if m_id == self.leader_id else "⚔️ "
            m_gs = gs_data.get(str(m_id), "??")
            m_done = weekly.get(str(m_id), 0)
            member_list.append(f"{prefix}<@{m_id}> [GS: **{m_gs}** | Зал: **{max(0, 5-m_done)}**]")

        embed.description = f"Лідер: <@{self.leader_id}>\nБосів: **{self.count}**\nЧас: <t:{self.ts}:t> (<t:{self.ts}:R>)"
        embed.set_field_at(0, name=f"Учасники ({len(self.members)}/5)", value="\n".join(member_list), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

# --- ОСНОВНИЙ COG ---
class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077

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
        # Логіка scheduler (наприклад, перевірка часу або розсилка в 09:00)
        pass

    @app_commands.command(name="shrine_create", description="Створити нову пачку")
    @app_commands.describe(time_hhmm="Час цифрами (наприклад 1900)")
    async def shrine_create(self, interaction: discord.Interaction, boss: str, count: int, time_hhmm: int):
        try:
            now = datetime.now()
            h, m = time_hhmm // 100, time_hhmm % 100
            if not (0 <= h < 24 and 0 <= m < 60): raise ValueError
            
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target < now: target += timedelta(days=1)
            ts = int(time_module.mktime(target.timetuple()))
        except:
            return await interaction.response.send_message("❌ Невірний формат часу! Використовуйте ГГММ (наприклад, 1930).", ephemeral=True)

        gs_data = self.load_json(GS_PATH)
        weekly = self.load_json(WEEKLY_PATH)
        uid = str(interaction.user.id)
        my_gs = gs_data.get(uid, "??")
        my_left = 5 - weekly.get(uid, 0)

        embed = discord.Embed(title=f"⚔️ Black Shrine: {boss}", color=0x2ecc71)
        embed.description = f"Лідер: {interaction.user.mention}\nБосів: **{count}**\nЧас: <t:{ts}:t> (<t:{ts}:R>)"
        embed.add_field(
            name="Учасники (1/5)", 
            value=f"👑 {interaction.user.mention} [GS: **{my_gs}** | Зал: **{max(0, my_left)}**]", 
            inline=False
        )
        embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)

        view = ShrinePartyView(interaction.user.id, boss, count, ts, self)
        await interaction.response.send_message(embed=embed, view=view)
        
        msg = await interaction.original_response()
        try:
            await msg.create_thread(name=f"Рейд {boss}", auto_archive_duration=60)
        except:
            pass

async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
