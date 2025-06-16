import os
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Modal, TextInput, Select, View, ChannelSelect
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from io import BytesIO
import random
from dotenv import load_dotenv
import asyncio

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", 1324854638276509828))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", 1324854638276509828))
FAREWELL_CHANNEL_ID = 1350571574557675520

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.joined_cache = {}
        self.dm_cache = set()
        self.templates = [
            "@{mention} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! @{mention} розгортає крила над сервером!",
            "В нашій секті… ой, тобто на сервері, новий учасник – @{mention}!",
            "@{mention} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. @{mention} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! @{mention} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість – @{mention}!",
        ]
        self.titles = [
            "📥 Прибуття нового духу!",
            "📥 Прибуття нової солодкої булочки!",
            "📥 Прибуття нового котятка!",
            "📥 Прибуття нової жертви!"
        ]
        self.backgrounds = [
            "assets/corsair_scroll_dark.png",
            "assets/welcome.png"
        ]
        self.avatar_frame_path = "assets/5646541.png"
        self.ban_image_url = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/BAN.png"
        self.leave_emoji = "📤"
        self.join_emoji = "📥"

    async def __cog_load__(self):
        await asyncio.sleep(2)
        try:
            self.bot.tree.add_command(self.greet_simple)
            await self.bot.tree.sync()
            print("🧷 [DEBUG] Слеш-команду /тест_привітання додано і синхронізовано глобально")
        except Exception as e:
            print(f"[DEBUG] ❌ Помилка sync в __cog_load__: {e}")

    async def generate_welcome_image(self, member: discord.Member, welcome_text: str):
        try:
            background_path = random.choice(self.backgrounds)
            bg = Image.open(background_path).convert("RGBA")

            draw = ImageDraw.Draw(bg)
            font_path_bold = "assets/FixelDisplay-Bold.otf"
            font_path_regular = "assets/FixelDisplay-Regular.otf"
            name_font = ImageFont.truetype(font_path_bold, 52)
            text_font = ImageFont.truetype(font_path_regular, 48)

            name = member.display_name
            import textwrap
            wrapped_lines = textwrap.wrap(welcome_text.replace("{mention}", name), width=26)

            text_color = (51, 29, 16)
            x_text = 100
            y_text = 360
            line_spacing = 72

            for i, line in enumerate(wrapped_lines):
                font = name_font if name in line else text_font
                draw.text((x_text, y_text + i * line_spacing), line, font=font, fill=text_color)

            avatar_url = member.display_avatar.url if member.display_avatar else member.default_avatar.url

            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status != 200:
                        print(f"[DEBUG] ❌ Не вдалося отримати аватар ({resp.status})")
                        return None
                    avatar_bytes = await resp.read()

            avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((495, 495))
            mask = Image.new("L", (495, 495), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.rounded_rectangle([0, 0, 495, 495], radius=90, fill=255)
            frame = Image.open(self.avatar_frame_path).convert("RGBA").resize((495, 495))

            avatar_pos = (1180, 690)
            bg.paste(avatar, avatar_pos, mask)
            bg.paste(frame, avatar_pos, frame)

            output_buffer = BytesIO()
            bg.save(output_buffer, format="PNG")
            output_buffer.seek(0)
            return discord.File(fp=output_buffer, filename="welcome.png")
        except Exception as e:
            print(f"[DEBUG] ❌ Помилка генерації картинки: {e.__class__.__name__}: {e}")
            return None

    @app_commands.command(name="тест_привітання", description="Надіслати тестовий welcome ембед")
    @app_commands.describe(канал="Канал, куди буде надіслано ембед")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def greet_simple(self, interaction: discord.Interaction, канал: discord.TextChannel):
        print(f"[DEBUG] ✅ Отримано команду /тест_привітання від {interaction.user} (ID: {interaction.user.id})")
        print(f"[DEBUG] 📥 Канал для надсилання: {канал.name} ({канал.id})")

        class Dummy:
            def __init__(self, user):
                self.display_name = user.display_name
                self.display_avatar = user.display_avatar
                self.default_avatar = user.default_avatar
                self.mention = user.mention

        fake_member = Dummy(interaction.user)
        template = random.choice(self.templates)
        welcome_text = template.replace("{mention}", interaction.user.display_name)
        image_file = await self.generate_welcome_image(fake_member, welcome_text)

        embed = discord.Embed(
            title=random.choice(self.titles),
            description=f"{interaction.user.mention}",
            color=discord.Color.teal()
        )
        if image_file:
            embed.set_image(url="attachment://welcome.png")
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.avatar.url)

        try:
            if image_file:
                await канал.send(file=image_file, embed=embed)
            else:
                await канал.send(embed=embed)
            print(f"[DEBUG] ✅ Ембед успішно надіслано в канал {канал.name}")
        except Exception as e:
            print(f"[DEBUG] ❌ Помилка при надсиланні ембеду в канал: {e}")
            await interaction.response.send_message("❌ Помилка при надсиланні ембеду. Перевір журнал.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Ембед надіслано в {канал.mention}", ephemeral=True)
        print("[DEBUG] ✅ Відповідь користувачу надіслано")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        print(f"📤 Користувач вийшов: {member}")
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="🚪 Учасник покинув сервер",
                description=f"{member.mention} більше з нами нема...",
                color=discord.Color.from_rgb(252, 3, 3)
            )
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)
            if member.joined_at:
                embed.add_field(name="Дата приєднання", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            embed.add_field(name="Дата виходу", value=discord.utils.format_dt(discord.utils.utcnow(), style='f'), inline=True)
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        print(f"⛔ [DEBUG] BAN: {user}")
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        reason = "Не вказано"

        try:
            async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    reason = entry.reason or "Не вказано"
                    break
        except Exception as e:
            print(f"⚠️ [DEBUG] Помилка при отриманні причини бану: {e}")

        try:
            dm_embed = discord.Embed(
                title="⛔ Ви будете заблоковані на сервері Silent Cove",
                description=f"Нажаль ви ({user.name}) не виправдали наданої довіри і ми вимушені з вами попрощатись. Myxa",
                color=discord.Color.red()
            )
            dm_embed.set_image(url=self.ban_image_url)
            await user.send(embed=dm_embed)
            print("📩 [DEBUG] Надіслано попередження в особисті повідомлення")
        except Exception as e:
            print(f"⚠️ [DEBUG] Не вдалося надіслати попередження користувачу {user}: {e}")

        if channel:
            embed = discord.Embed(
                title="⛔ Користувача забанено!",
                description=f"{user.mention} порушив(ла) правила Silent Cove.",
                color=discord.Color.from_rgb(252, 3, 3)
            )
            embed.add_field(name="📌 Причина:", value=reason, inline=False)
            embed.add_field(name="📅 Долучився:", value=self.joined_cache.get(user.id, "невідомо"), inline=True)
            embed.add_field(name="📅 Покинув:", value=discord.utils.utcnow().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            if hasattr(user, 'avatar') and user.avatar:
                embed.set_thumbnail(url=user.avatar.url)
            await channel.send(embed=embed)
            print("📨 [DEBUG] Надіслано повідомлення про бан до каналу")

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))

@bot.event
async def on_ready():
    print(f"[DEBUG] ✅ WelcomeBot увійшов як {bot.user}")
    try:
        await asyncio.sleep(2)
        synced = await bot.tree.sync()
        print(f"[DEBUG] 🔄 Slash-команди синхронізовано глобально: {len(synced)}")
    except Exception as e:
        print(f"[DEBUG] ❌ Помилка синхронізації команд у on_ready: {e}")

async def main():
    print("[DEBUG] 🚀 Старт WelcomeBot...")
    async with bot:
        try:
            print("[DEBUG] 📥 Завантажуємо welcome_cog...")
            await bot.load_extension("cogs.welcome_cog")
            print("[DEBUG] ✅ WelcomeCog завантажено")
        except Exception as e:
            print(f"[DEBUG] ❌ Не вдалося завантажити WelcomeCog: {e}")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
