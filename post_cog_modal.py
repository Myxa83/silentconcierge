import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import Modal, TextInput
import aiohttp
from PIL import Image, ImageDraw
import io

class PostModal(Modal, title="📝 Створити допис"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

        self.title_input = TextInput(
            label="Заголовок (необов’язково)",
            required=False,
            max_length=100,
            placeholder="Наприклад: 📢 Умови найму"
        )
        self.text_input = TextInput(
            label="Текст з форматуванням (Markdown підтримується)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1500,
            placeholder="**Khan →** lvl 3 — 2 cannons, 20 balls\n> Примітка: не спамити"
        )
        self.image_input = TextInput(
            label="Посилання на зображення (необов’язково)",
            required=False,
            placeholder="https://example.com/image.png"
        )

        self.add_item(self.title_input)
        self.add_item(self.text_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: Interaction):
        title = self.title_input.value
        description = self.text_input.value
        image_url = self.image_input.value.strip()

        file = None
        image_link = None

        if image_url:
            file, image_link = await self.bot.get_cog("PostCog").rounded_image_from_url(image_url)

        embed = discord.Embed(
            title=title or "📋 Повідомлення",
            description=description,
            color=discord.Color.blurple()
        )
        if image_link:
            embed.set_image(url=image_link)

        embed.set_footer(text="Silent Concierge by Муха")

        await interaction.response.send_message(embed=embed, file=file)

class PostCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def rounded_image_from_url(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None, None
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

    @app_commands.command(name="новий_пост", description="Створити допис з форматуванням (Markdown + зображення)")
    async def новий_пост(self, interaction: Interaction):
        await interaction.response.send_modal(PostModal(self.bot))

async def setup(bot):
    await bot.add_cog(PostCog(bot))