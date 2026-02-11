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

class ShrineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.role_id = 1406569206815658077 # Роль Страждущі
        self.report_channel_id = 1421625193134166200 # Основний канал
        self.test_channel_id = 1370522199873814528   # Тестовий канал
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()

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

    @tasks.loop(minutes=1)
    async def scheduler(self):
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M")
        weekday = now_dt.weekday() # 6 = Неділя

        if weekday == 6 and now_str == "00:01":
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

        for member in role.members:
            uid = str(member.id)
            done = weekly.get(uid, 0)
            if done >= 5: continue

            player_gs = gs_data.get(uid, "Не вказано")
            not_done = 5 - done

            # Створення стильного Ембеда як на референсі
            embed = discord.Embed(
                title="Вітаю Вас! Нагадую за босів Black Shrine!",
                description=(
                    f"Ваш гір підходить (GS: **{player_gs}**)\n"
                    f"У вас не пройдено: **{not_done}** босів\n\n"
                    f"Коли Вам буде комфортно пройти босів сьогодні?"
                ),
                color=0x2ecc71
            )
            # Гіфка смужка внизу
            embed.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/PolosBir.gif?raw=true")
            # Футер
            embed.set_footer(text="Silent Concierge | В пошуках страждущіх")

            view = PollResponseView(self.report_channel_id)
            try:
                await member.send(embed=embed, view=view)
            except: continue

    @app_commands.command(name="shrine_set_gs", description="Вказати свій Gear Score (Гармот)")
    async def shrine_set_gs(self, interaction: discord.Interaction, gs: int):
        data = self.load_json(GS_PATH)
        data[str(interaction.user.id)] = gs
        self.save_json(data, GS_PATH)
        await interaction.response.send_message(f"✅ Ваш GS ({gs}) збережено!", ephemeral=True)

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

        embed = discord.Embed(
            title=f"⚔️ Black Shrine: {boss.name}",
            description=f"Лідер: {interaction.user.mention}\nКількість босів: **{count}**\nЧас збору: **{time}**",
            color=0x2ecc71
        )
        embed.add_field(name="Учасники (1/5)", value=interaction.user.mention)
        
        view = ShrinePartyView(interaction.user.id, boss.name, count, self)
        await interaction.response.send_message(embed=embed, view=view)
        
        msg = await interaction.original_response()
        await msg.create_thread(name=f"Рейд {boss.name}", auto_archive_duration=60)

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

    @discord.ui.button(label="Вийти (Світло)", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.members: return
        if interaction.user.id == self.leader_id:
            return await interaction.response.send_message("Лідер має видалити рейд!", ephemeral=True)

        self.members.remove(interaction.user.id)
        await self.update_embed(interaction)
        
        if interaction.message.thread:
            await interaction.message.thread.send(
                f"⚠️ <@&{self.cog.role_id}>, {interaction.user.mention} вийшов (немає світла). **Потрібна заміна!**"
            )

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
        await interaction.response.send_message("Запити надіслано!", ephemeral=True)

    async def update_embed(self, interaction):
        embed = interaction.message.embeds[0]
        mentions = [f"<@{m}>" for m in self.members]
        embed.set_field_at(0, name=f"Учасники ({len(self.members)}/5)", value="\n".join(mentions))
        await interaction.response.edit_message(embed=embed, view=self)

class PollResponseView(discord.ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="Вже пройшов(ла)", style=discord.ButtonStyle.green, row=0)
    async def already_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Чудово! Гарного дня.", ephemeral=True)

    @discord.ui.button(label="О 19:00", style=discord.ButtonStyle.blurple, row=1)
    async def t1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Записано! Чекаємо вас.", ephemeral=True)

    @discord.ui.button(label="О 21:00", style=discord.ButtonStyle.blurple, row=1)
    async def t2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Записано! Чекаємо вас.", ephemeral=True)

    @discord.ui.button(label="3 боси", style=discord.ButtonStyle.gray, row=2)
    async def c3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Прийнято: 3 боси.", ephemeral=True)

    @discord.ui.button(label="5 босів", style=discord.ButtonStyle.gray, row=2)
    async def c5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Прийнято: повний забіг (5).", ephemeral=True)

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

async def setup(bot):
    await bot.add_cog(ShrineCog(bot))
