import os
import re
import io
import asyncio
import sqlite3
import datetime
import aiohttp
import pandas as pd
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==========================================
# 1. BOT SETUP & INTENTS
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required for timeout and role hierarchy checks

bot = commands.Bot(command_prefix='!', intents=intents)

# Regex filters
X_PATTERN = re.compile(r'https?://(?:www\.)?(?:x\.com|twitter\.com)/', re.IGNORECASE)
URL_PATTERN = re.compile(r'https?://[^\s]+')
MALICIOUS_PATTERN = re.compile(
    r"(discord\.gg/|discord\.com/invite/|t\.me/|troll-link\.com)", 
    re.IGNORECASE
)

# ==========================================
# 2. DATABASE INITIALIZATION
# ==========================================
def setup_db():
    conn = sqlite3.connect('activity.db')
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    
    # Leaderboard & activity table
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            user_id TEXT,
            username TEXT,
            message_id TEXT PRIMARY KEY,
            timestamp DATETIME,
            is_x_post BOOLEAN,
            is_gif BOOLEAN,
            is_sticker BOOLEAN,
            is_pure_text BOOLEAN,
            link_count INTEGER,
            avatar_url TEXT
        )
    ''')
    
    # Spam strikes table for bouncer
    c.execute('''
        CREATE TABLE IF NOT EXISTS spam_strikes (
            user_id TEXT PRIMARY KEY,
            strikes INTEGER DEFAULT 0,
            last_strike DATETIME
        )
    ''')
    
    try:
        c.execute("ALTER TABLE messages ADD COLUMN avatar_url TEXT")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

# ==========================================
# 3. MESSAGE PROCESSING & BOUNCER
# ==========================================
def process_and_save_message(message, conn=None):
    if message.author.bot or not message.guild:
        return
        
    if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
        return  # Exclude administrators from leaderboard stats
            
    content_lower = message.content.lower()
    is_x_post = bool(X_PATTERN.search(message.content))
    link_count = len(URL_PATTERN.findall(message.content))
    
    is_gif = False
    if 'tenor.com' in content_lower or 'giphy.com' in content_lower or content_lower.endswith('.gif'):
        is_gif = True
    for embed in message.embeds:
        if embed.type in ['gifv', 'image'] and embed.url:
            if 'tenor.com' in embed.url or 'giphy.com' in embed.url or embed.url.endswith('.gif'):
                is_gif = True
                
    is_sticker = len(message.stickers) > 0
    is_command = message.content.startswith(bot.command_prefix) or message.content.startswith('/')
    is_pure_text = not is_gif and not is_sticker and not is_command
    
    avatar_url = message.author.avatar.url if message.author.avatar else message.author.default_avatar.url
    
    close_conn = False
    if conn is None:
        conn = sqlite3.connect('activity.db', timeout=10)
        close_conn = True
        
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO messages 
        (user_id, username, message_id, timestamp, is_x_post, is_gif, is_sticker, is_pure_text, link_count, avatar_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        str(message.author.id), str(message.author.name), str(message.id), 
        message.created_at.isoformat(), is_x_post, is_gif, is_sticker, is_pure_text, link_count, str(avatar_url)
    ))
    
    if close_conn:
        conn.commit()
        conn.close()

# ==========================================
# 4. PILLOW GRAPHICS ENGINE
# ==========================================
async def fetch_image(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(str(url)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        print(f"Error fetching image: {e}")
    return None

def create_circular_mask(size):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + size, fill=255)
    return mask

def strip_emojis(text):
    cleaned = ''.join(c for c in text if ord(c) < 128)
    return cleaned.strip() if cleaned.strip() else "Member"

async def generate_leaderboard_image(users_data, time_text):
    width, height = 850, 950
    base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
    draw = ImageDraw.Draw(base)
    
    # Modern gradient background
    for y in range(height):
        r = int(15 + 15 * (y / height))
        g = int(23 + 18 * (y / height))
        b = int(42 + 17 * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
        
    try:
        font_large = ImageFont.truetype("arialbd.ttf", 34)
        font_med_bold = ImageFont.truetype("arialbd.ttf", 22)
        font_med = ImageFont.truetype("arial.ttf", 22)
        font_small = ImageFont.truetype("arial.ttf", 18)
    except:
        font_large = font_med_bold = font_med = font_small = ImageFont.load_default()

    # Title
    draw.text((width // 2, 50), "COMMUNITY ENGAGEBOARD", font=font_large, fill=(255, 255, 255), anchor="mm")
    draw.text((width // 2, 95), time_text.upper(), font=font_small, fill=(148, 163, 184), anchor="mm")

    # Podium
    podium_coords = {
        1: (width // 2, 240, 140, (250, 214, 21)),     # Gold
        2: (width // 2 - 200, 270, 110, (148, 163, 184)), # Silver
        3: (width // 2 + 200, 290, 95, (180, 83, 9))      # Bronze
    }

    for user in users_data[:3]:
        rank = user['rank']
        cx, cy, size, color = podium_coords[rank]
        
        # Soft Outer Glow
        padding = 80
        glow_size = size + (padding * 2)
        glow = Image.new("RGBA", (glow_size, glow_size), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse((padding, padding, padding + size, padding + size), fill=(color[0], color[1], color[2], 90))
        glow = glow.filter(ImageFilter.GaussianBlur(30))
        base.paste(glow, (int(cx - glow_size / 2), int(cy - glow_size / 2)), glow)
        
        # Podium Border
        draw.ellipse((cx - size / 2 - 6, cy - size / 2 - 6, cx + size / 2 + 6, cy + size / 2 + 6), fill=color)
        
        if user['avatar']:
            av = user['avatar'].resize((size, size))
            mask = create_circular_mask((size, size))
            base.paste(av, (int(cx - size / 2), int(cy - size / 2)), mask)
            
        clean_name = strip_emojis(user['username'])
        draw.text((cx, cy + size / 2 + 30), clean_name, font=font_med_bold, fill=(255, 255, 255), anchor="mm")
        
        score_text = f"{user['total']} msgs"
        score_bbox = draw.textbbox((cx, cy + size / 2 + 60), score_text, font=font_small, anchor="mm")
        left, top, right, bottom = score_bbox
        draw.rounded_rectangle((left - 15, top - 5, right + 15, bottom + 5), radius=12, fill=(30, 41, 59, 200))
        draw.text((cx, cy + size / 2 + 60), score_text, font=font_small, fill=(color[0], color[1], color[2]), anchor="mm")

    # Master Table (Ranks 4-10)
    if len(users_data) > 3:
        start_y = 480
        draw.text((70, start_y), "Rank", font=font_small, fill=(148, 163, 184), anchor="lm")
        draw.text((140, start_y), "Member", font=font_small, fill=(148, 163, 184), anchor="lm")
        draw.text((450, start_y), "Pure", font=font_small, fill=(148, 163, 184), anchor="mm")
        draw.text((550, start_y), "X Posts", font=font_small, fill=(148, 163, 184), anchor="mm")
        draw.text((650, start_y), "GIFs", font=font_small, fill=(148, 163, 184), anchor="mm")
        draw.text((760, start_y), "Total", font=font_med_bold, fill=(255, 255, 255), anchor="mm")
        
        row_y = start_y + 35
        for user in users_data[3:]:
            draw.rounded_rectangle((40, row_y, width - 40, row_y + 55), radius=12, fill=(30, 41, 59, 180))
            draw.text((70, row_y + 27), f"#{user['rank']}", font=font_med_bold, fill=(148, 163, 184), anchor="lm")
            
            if user['avatar']:
                av = user['avatar'].resize((38, 38))
                mask = create_circular_mask((38, 38))
                draw.ellipse((140 - 2, row_y + 27 - 19 - 2, 140 + 38 + 2, row_y + 27 - 19 + 38 + 2), fill=(100, 116, 139))
                base.paste(av, (140, row_y + 27 - 19), mask)
                
            clean_name = strip_emojis(user['username'])
            draw.text((195, row_y + 27), clean_name, font=font_med_bold, fill=(248, 250, 252), anchor="lm")
            draw.text((450, row_y + 27), str(user['pure']), font=font_med, fill=(203, 213, 225), anchor="mm")
            draw.text((550, row_y + 27), str(user['x_posts']), font=font_med, fill=(203, 213, 225), anchor="mm")
            draw.text((650, row_y + 27), str(user['gifs']), font=font_med, fill=(203, 213, 225), anchor="mm")
            draw.text((760, row_y + 27), str(user['total']), font=font_med_bold, fill=(250, 214, 21), anchor="mm")
            row_y += 65

    return base

# ==========================================
# 5. BOT EVENTS
# ==========================================
@bot.event
async def on_ready():
    setup_db()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Successfully synced {len(synced)} slash command(s) with Discord!")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content.strip()

    # --- TIER 1 BOUNCER: EXECUTIONER ---
    # Instantly delete unauthorized invite/malicious links & timeout the sender
    if MALICIOUS_PATTERN.search(content):
        try:
            await message.delete()
            guild_me = message.guild.me
            
            # Check bot permissions and hierarchy
            if guild_me.guild_permissions.moderate_members and message.author.top_role < guild_me.top_role:
                await message.author.timeout(datetime.timedelta(hours=1), reason="Automated Spam/Invite Link Detection")
                
            conn = sqlite3.connect('activity.db', timeout=10)
            c = conn.cursor()
            c.execute('''
                INSERT INTO spam_strikes (user_id, strikes, last_strike)
                VALUES (?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET strikes = strikes + 1, last_strike = excluded.last_strike
            ''', (str(message.author.id), datetime.datetime.utcnow().isoformat()))
            conn.commit()
            conn.close()
            return
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"Failed to timeout or delete spam from {message.author}: {e}")
            return

    # Track message activity
    process_and_save_message(message)
    await bot.process_commands(message)

# ==========================================
# 6. SLASH COMMANDS
# ==========================================
@bot.tree.command(name="stat", description="Generate Graphical Top 10 Leaderboard")
@discord.app_commands.describe(
    days="Look back X days (default is 7).",
    after_date="Look for messages after a date (Format: DD-MM-YYYY)"
)
async def stat(interaction: discord.Interaction, days: int = None, after_date: str = None):
    await interaction.response.defer(ephemeral=True)
    
    cutoff_date = None
    if after_date is not None:
        try:
            cutoff_date = pd.to_datetime(after_date, format="%d-%m-%Y", utc=True)
            time_text = f"Since {after_date}"
        except ValueError:
            await interaction.followup.send("❌ Invalid date format! Please use DD-MM-YYYY (e.g., 01-10-2023)", ephemeral=True)
            return
    else:
        if days is None:
            days = 7
        cutoff_date = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)
        time_text = f"For the last {days} days"

    conn = sqlite3.connect('activity.db', timeout=10)
    try:
        df = pd.read_sql_query("SELECT * FROM messages WHERE user_id NOT LIKE 'tg_%'", conn)
    except sqlite3.OperationalError:
        await interaction.followup.send("No data found yet!")
        return
    finally:
        conn.close()
        
    if df.empty:
        await interaction.followup.send("No message activity found yet!")
        return
        
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601', utc=True)
    df = df[df['timestamp'] >= cutoff_date]
    
    if df.empty:
        await interaction.followup.send(f"No message activity found {time_text}!")
        return

    user_stats = df.groupby('user_id').agg(
        total_messages=('message_id', 'count'),
        pure_msgs=('is_pure_text', 'sum'),
        x_posts=('is_x_post', 'sum'),
        gifs=('is_gif', 'sum'),
        stickers=('is_sticker', 'sum')
    ).reset_index()
    
    user_stats['gifs_total'] = user_stats['gifs'] + user_stats['stickers']
    
    filtered_rows = []
    for _, row in user_stats.iterrows():
        try:
            uid = int(row['user_id'])
            member = interaction.guild.get_member(uid)
            if member and (member.guild_permissions.administrator or member.bot):
                continue
            filtered_rows.append(row)
        except ValueError:
            continue
            
    if not filtered_rows:
        await interaction.followup.send(f"No valid member activity found {time_text} (Admins excluded)!")
        return
        
    filtered_stats = pd.DataFrame(filtered_rows)
    top_10 = filtered_stats.sort_values(by='total_messages', ascending=False).head(10)
    
    embed = discord.Embed(
        title=f"# 🏆 Community Engageboard ({time_text})",
        color=discord.Color.gold()
    )
    
    users_data = []
    for rank, (_, row) in enumerate(top_10.iterrows(), 1):
        uid = int(row['user_id'])
        try:
            user = await bot.fetch_user(uid)
            avatar_url = user.avatar.url if user.avatar else user.default_avatar.url
            avatar_img = await fetch_image(avatar_url)
            
            users_data.append({
                'rank': rank,
                'username': user.name,
                'avatar': avatar_img,
                'total': int(row['total_messages']),
                'pure': int(row['pure_msgs']),
                'x_posts': int(row['x_posts']),
                'gifs': int(row['gifs_total'])
            })
            
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "🏅"
            embed.add_field(
                name=f"{medal} Rank {rank}",
                value=f"<@{uid}> - **{int(row['total_messages'])}** total messages",
                inline=False
            )
            if rank == 1 and user.avatar:
                embed.set_thumbnail(url=user.avatar.url)
        except Exception as e:
            print(f"Failed to fetch user {uid}: {e}")
            
    if not users_data:
        await interaction.followup.send("Failed to generate leaderboard (no users fetched).")
        return

    img = await generate_leaderboard_image(users_data, time_text)
    embed.set_footer(text=f"Total recorded messages in this period: {len(df)}")
    embed.set_image(url="attachment://leaderboard.png")
    
    with io.BytesIO() as image_binary:
        img.save(image_binary, 'PNG')
        image_binary.seek(0)
        file = discord.File(fp=image_binary, filename='leaderboard.png')
        await interaction.followup.send(embed=embed, file=file)

@bot.tree.command(name="mystats", description="View your personal engagement stats")
async def mystats(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You are an Administrator! Your messages are excluded from engagement tracking.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    conn = sqlite3.connect('activity.db', timeout=10)
    df = pd.read_sql_query("SELECT * FROM messages WHERE user_id = ?", conn, params=(str(interaction.user.id),))
    conn.close()
    
    if df.empty:
        await interaction.followup.send("You haven't sent any tracked messages yet!")
        return
        
    embed = discord.Embed(title=f"📊 Stats for {interaction.user.display_name}", color=discord.Color.blue())
    if interaction.user.avatar:
        embed.set_thumbnail(url=interaction.user.avatar.url)
        
    embed.add_field(name="Total Messages", value=f"{len(df)}", inline=True)
    embed.add_field(name="Pure Text", value=f"{df['is_pure_text'].sum()}", inline=True)
    embed.add_field(name="X Posts", value=f"{df['is_x_post'].sum()}", inline=True)
    embed.add_field(name="GIFs/Stickers", value=f"{df['is_gif'].sum() + df['is_sticker'].sum()}", inline=True)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="sync", description="Manually scrape past messages into the database (Admins Only)")
@discord.app_commands.describe(days="How many days back to scan (default is 7, max 30)")
@discord.app_commands.default_permissions(administrator=True)
async def sync(interaction: discord.Interaction, days: int = 7):
    days = min(days, 30)
    await interaction.response.send_message(f"🔄 **Starting history sync for the past {days} days...**", ephemeral=True)
    
    after_date = discord.utils.utcnow() - datetime.timedelta(days=days)
    conn = sqlite3.connect('activity.db', timeout=10)
    
    total_synced = 0
    for guild in bot.guilds:
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not perms.read_message_history or not perms.read_messages:
                continue
            try:
                async for message in channel.history(limit=None, after=after_date):
                    process_and_save_message(message, conn)
                    total_synced += 1
                    if total_synced % 100 == 0:
                        await asyncio.sleep(0.1)
            except Exception:
                pass
            conn.commit()
    conn.close()
    await interaction.edit_original_response(content=f"✅ **Sync complete!** Scraped {total_synced} past messages.")

# ==========================================
# 7. START BOT (Strictly from .env)
# ==========================================
if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise ValueError("DISCORD_TOKEN not found in .env! Please add it to your .env file.")
    bot.run(token)
