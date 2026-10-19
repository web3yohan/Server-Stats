import sys
import os
import re
import html
import asyncio
import sqlite3
import datetime
import pandas as pd
from dotenv import load_dotenv
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Ensure Windows terminal doesn't crash on UTF-8 / emojis
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

# ==========================================
# 1. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('activity.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS spam_strikes (
            user_id TEXT PRIMARY KEY,
            strikes INTEGER DEFAULT 0,
            last_strike DATETIME
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. REGEX PATTERNS
# ==========================================
X_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/[a-zA-Z0-9_]+", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
MALICIOUS_PATTERN = re.compile(
    r"(discord\.gg/|discord\.com/invite/|t\.me/joinchat/|t\.me/\+[a-zA-Z0-9_-]+|troll-link\.com)", 
    re.IGNORECASE
)

# ==========================================
# 3. AUTO-DELETE HELPER
# ==========================================
async def auto_delete_message(message, delay_seconds: int):
    """Wait for specified seconds and delete the message."""
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception:
        pass

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if the sender is an admin or creator."""
    try:
        if not update.effective_chat or update.effective_chat.type == "private":
            return False
        member = await update.effective_chat.get_member(update.effective_user.id)
        return member.status in ['creator', 'administrator']
    except Exception:
        return False

# ==========================================
# 4. MESSAGE HANDLER & TIER 1 BOUNCER
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not msg or not user or user.is_bot:
        return

    raw_content = msg.text or msg.caption or ""
    content = raw_content.strip()

    # --- TIER 1 BOUNCER: EXECUTIONER ---
    if MALICIOUS_PATTERN.search(content):
        # Admins are exempt from being muted/banned
        if not await is_admin(update, context):
            try:
                await msg.delete()

                until_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_time
                )

                conn = sqlite3.connect('activity.db', timeout=10)
                c = conn.cursor()
                c.execute('''
                    INSERT INTO spam_strikes (user_id, strikes, last_strike)
                    VALUES (?, 1, ?)
                    ON CONFLICT(user_id) DO UPDATE SET strikes = strikes + 1, last_strike = excluded.last_strike
                ''', (f"tg_{user.id}", datetime.datetime.utcnow().isoformat()))
                conn.commit()
                conn.close()

                warning = await chat.send_message(
                    f"⚠️ {user.mention_html()} has been muted for 1 hour (Unauthorized Link).",
                    parse_mode="HTML"
                )
                asyncio.create_task(auto_delete_message(warning, 30))
                return
            except Exception as e:
                print(f"Error executing Telegram bouncer: {e}")
                return

    # Identify message traits
    is_x_post = bool(X_PATTERN.search(content))
    link_count = len(URL_PATTERN.findall(content))
    
    is_sticker = bool(msg.sticker)
    is_gif = bool(msg.animation) or ("tenor.com" in content.lower()) or ("giphy.com" in content.lower())
    is_media = bool(msg.photo or msg.video or msg.document)

    if (is_sticker or is_gif or is_media) and not content:
        return

    is_pure_text = not is_gif and not is_sticker and not is_media and not is_x_post and (link_count == 0)

    # Record message dynamically into activity.db
    try:
        conn = sqlite3.connect('activity.db', timeout=10)
        c = conn.cursor()
        display_name = user.username or user.first_name or "Telegram User"
        
        c.execute('''
            INSERT OR IGNORE INTO messages 
            (user_id, username, message_id, timestamp, is_x_post, is_gif, is_sticker, is_pure_text, link_count, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            f"tg_{user.id}",
            display_name,
            f"tg_{msg.message_id}_{chat.id}",
            datetime.datetime.utcnow().isoformat(),
            is_x_post,
            is_gif,
            is_sticker,
            is_pure_text,
            link_count,
            None
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database write error: {e}")

# ==========================================
# 5. AUTO-DELETING TELEGRAM COMMANDS
# ==========================================
async def cmd_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View personal stats (Auto-deletes after 60 seconds)."""
    try:
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg:
            return

        conn = sqlite3.connect('activity.db', timeout=10)
        try:
            df = pd.read_sql_query("SELECT * FROM messages WHERE user_id = ?", conn, params=(f"tg_{user.id}",))
        finally:
            conn.close()

        if df.empty:
            reply = await msg.reply_text("You haven't sent any tracked messages yet!")
            asyncio.create_task(auto_delete_message(reply, 60))
            asyncio.create_task(auto_delete_message(msg, 60))
            return

        total = len(df)
        pure = int(df['is_pure_text'].sum())
        x_posts = int(df['is_x_post'].sum())
        media = int(df['is_gif'].sum() + df['is_sticker'].sum())

        safe_name = html.escape(user.first_name or "Member")
        text = (
            f"📊 <b>Stats for {safe_name}</b>\n\n"
            f"💬 <b>Total Messages:</b> <code>{total:,}</code>\n"
            f"✍️ <b>Pure Text:</b> <code>{pure:,}</code>\n"
            f"🐦 <b>X (Twitter) Links:</b> <code>{x_posts:,}</code>\n"
            f"🎭 <b>GIFs/Stickers:</b> <code>{media:,}</code>\n\n"
            f"⏱ <i>This message will auto-delete in 60s</i>"
        )
        reply = await msg.reply_html(text)
        asyncio.create_task(auto_delete_message(reply, 60))
        asyncio.create_task(auto_delete_message(msg, 60))
    except Exception as e:
        print(f"Error in cmd_mystats: {e}")

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View Top 10 contest leaders in Telegram (Auto-deletes after 60 seconds)."""
    try:
        msg = update.effective_message
        if not msg:
            return

        conn = sqlite3.connect('activity.db', timeout=10)
        try:
            df = pd.read_sql_query("""
                SELECT username, COUNT(*) as count 
                FROM messages 
                WHERE user_id LIKE 'tg_%' 
                GROUP BY user_id, username 
                ORDER BY count DESC 
                LIMIT 10
            """, conn)
        finally:
            conn.close()

        if df.empty:
            reply = await msg.reply_text("No contest activity recorded yet!")
            asyncio.create_task(auto_delete_message(reply, 60))
            asyncio.create_task(auto_delete_message(msg, 60))
            return

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = ["🏆 <b>Contest Leaderboard</b>\n"]
        for i, (_, row) in enumerate(df.iterrows()):
            medal = medals[i] if i < len(medals) else f"#{i+1}"
            safe_name = html.escape(str(row['username']))
            lines.append(f"{medal} <b>{safe_name}</b> — <code>{row['count']:,}</code> msgs")
            
        lines.append("\n⏱ <i>This message will auto-delete in 60s</i>")

        reply = await msg.reply_html("\n".join(lines))
        asyncio.create_task(auto_delete_message(reply, 60))
        asyncio.create_task(auto_delete_message(msg, 60))
    except Exception as e:
        print(f"Error in cmd_leaderboard: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Telegram Bot Exception: {context.error}")

# ==========================================
# 6. APPLICATION ENTRY POINT
# ==========================================
if __name__ == '__main__':
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token or token == 'your_telegram_bot_token_here':
        raise ValueError("TELEGRAM_BOT_TOKEN not found in .env! Please set it before running.")

    application = Application.builder().token(token).build()

    # Commands (Using /contest and /mystats so they never collide with Combot)
    application.add_handler(CommandHandler("mystats", cmd_mystats))
    application.add_handler(CommandHandler("contest", cmd_leaderboard))
    application.add_handler(CommandHandler("contestboard", cmd_leaderboard))

    # All regular messages (text, photos, stickers, gifs)
    application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

    application.add_error_handler(error_handler)

    print("[SUCCESS] Telegram Bot & Tier 1 Bouncer (/contest & /mystats) is now running!")
    application.run_polling()
