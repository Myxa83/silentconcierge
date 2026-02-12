import discord
from discord.ext import commands
import json
import asyncio
import re
import os

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_path = os.path.join("data", "members_gear.json")
        self.delays = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        self.target_channel_id = 1358443998603120824 

    async def scrape_gear_links(self, ctx, channel: discord.TextChannel):
        # Лог у консоль про початок
        print(f"--- ЗАПУСК ПАРСИНГУ: {channel.name} ({channel.id}) ---")
        status_msg = await ctx.send(f"⚙️ **Підготовка...** Звертаюся до каналу #{channel.name}")
        
        gear_data = {}
        offset = 0
        count = 0
        pattern = r'https?://(?:www\.)?garmoth\.com/character/\S+'

        messages = [msg async for msg in channel.history(limit=1000)]
        total_found = sum(1 for m in messages if "garmoth.com" in m.content)
        
        print(f"Знайдено повідомлень з посиланнями: {total_found}")
        await status_msg.edit(content=f"🔍 Знайдено посилань у чаті: **{total_found}**. Починаю обробку...")

        for message in messages:
            if "garmoth.com" in message.content:
                links = re.findall(pattern, message.content)
                if links:
                    author_name = message.author.display_name
                    if author_name not in gear_data:
                        gear_data[author_name] = links[0]
                        count += 1
                        
                        delay_idx = (count - 1) % len(self.delays)
                        if delay_idx == 0 and count > 1:
                            offset += 1
                        
                        wait_time = self.delays[delay_idx] + offset
                        
                        # ДЕТАЛЬНИЙ ЛОГ ДЛЯ RENDER
                        print(f"[{count}/{total_found}] Користувач: {author_name} | Затримка: {wait_time}с")
                        
                        await status_msg.edit(content=(
                            f"⏳ **Прогрес:** Оброблено {count} гравців.\n"
                            f"👤 Зараз: `{author_name}`\n"
                            f"⏸️ Очікування: `{wait_time}с`..."
                        ))
                        
                        await asyncio.sleep(wait_time)

        # Лог про завершення збору
        print(f"Збір завершено. Всього унікальних гравців: {len(gear_data)}")
        
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(gear_data, f, ensure_ascii=False, indent=4)

        await status_msg.delete()
        
        if gear_data:
            file = discord.File(self.data_path)
            await ctx.send(f"✅ **Збір завершено!**\n📊 Гравців: {len(gear_data)}\n📂 Файл збережено.", file=file)
        else:
            await ctx.send(f"❌ Посилань не знайдено.")

    @commands.command(name="collect_gear")
    @commands.has_permissions(administrator=True)
    async def collect_gear(self, ctx, channel_id: int = None):
        target_id = channel_id or self.target_channel_id
        try:
            target_channel = self.bot.get_channel(target_id) or await self.bot.fetch_channel(target_id)
            await self.scrape_gear_links(ctx, target_channel)
        except Exception as e:
            print(f"КРИТИЧНА ПОМИЛКА: {e}")
            await ctx.send(f"❌ Сталася помилка: {e}")

async def setup(bot):
    await bot.add_cog(BdoGear(bot))
