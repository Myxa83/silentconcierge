
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button
import aiohttp
from PIL import Image, ImageDraw
import io

class PostView(View):
    def __init__(self, options):
        super().__init__(timeout=None)
        for label in options:
            self.add_item(PostButton(label))

class PostButton(Button):
    def __init__(self, label):
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        await interaction.response.send_message(f"✅ Ви обрали: **{self.label}**", ephemeral=True)

class PostCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def rounded_image_from_url(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()

            image = Image.open(io.BytesIO(data)).convert("RGBA")
            width, height = image.size
            radius = 40

            mask = Image.new('L', (width, height), 255)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle([(0, 0), (width, height)], radius=radius, fill=0)
            image.putalpha(255 - mask)

            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            return discord.File(buffer, filename="rounded.png"), "attachment://rounded.png"
        except Exception as e:
            print(f"❌ Помилка обробки зображення: {e}")
            return None, None

    @app_commands.command(name="пост", description="Створити допис або опитування з кнопками")
    @app_commands.describe(
        заголовок="Заголовок повідомлення",
        текст="Основний текст (markdown підтримується)",
        картинка="Посилання на зображення (буде округлене)",
        шрифт="Назва шрифту (не візуально, а як текст)",
        опитування1="Варіант 1",
        опитування2="Варіант 2",
        опитування3="Варіант 3",
        опитування4="Варіант 4",
        опитування5="Варіант 5"
    )
    async def пост(self, interaction: Interaction,
        заголовок: str = None,
        текст: str = None,
        картинка: str = None,
        шрифт: str = None,
        опитування1: str = None,
        опитування2: str = None,
        опитування3: str = None,
        опитування4: str = None,
        опитування5: str = None
    ):
        await interaction.response.defer()

        embed = None
        file = None
        image_url = None

        if заголовок or текст or картинка:
            embed = discord.Embed(
                title=заголовок or "",
                description=текст or "",
                color=discord.Color.teal()
            )
            if шрифт:
                embed.set_author(name=f"Шрифт: {шрифт}")
            if картинка:
                file, image_url = await self.rounded_image_from_url(картинка)
                if image_url:
                    embed.set_image(url=image_url)

        options = [opt for opt in [опитування1, опитування2, опитування3, опитування4, опитування5] if opt]

        if not embed and options:
            view = PostView(options)
            await interaction.followup.send("📊 Виберіть варіант:", view=view)
        elif embed and options:
            view = PostView(options)
            await interaction.followup.send(embed=embed, view=view, file=file)
        elif embed:
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send("❌ Ви не заповнили жодне поле.")

async def setup(bot):
    await bot.add_cog(PostCog(bot))
