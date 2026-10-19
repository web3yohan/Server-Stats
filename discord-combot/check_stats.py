import sys
import sqlite3
import pandas as pd

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

conn = sqlite3.connect('activity.db')

print("=" * 60)
print("ACTIVITY DATABASE HEALTH & DATA CHECK")
print("=" * 60)

# 1. Total counts & platform breakdown
df_summary = pd.read_sql_query("""
    SELECT 
        CASE WHEN user_id LIKE 'tg_%' THEN 'Telegram' ELSE 'Discord' END as platform,
        COUNT(*) as total_messages,
        COUNT(DISTINCT user_id) as unique_users,
        SUM(is_pure_text) as pure_text_messages,
        SUM(is_x_post) as x_posts,
        SUM(is_gif + is_sticker) as media_messages,
        MIN(timestamp) as earliest_date,
        MAX(timestamp) as latest_date
    FROM messages
    GROUP BY platform
""", conn)
print("\n[PLATFORM BREAKDOWN]")
print(df_summary.to_string(index=False))

# 2. Grand Total
total_row = pd.read_sql_query("SELECT COUNT(*) as total_all, COUNT(DISTINCT user_id) as total_users FROM messages", conn)
print(f"\n[GRAND TOTAL]: {total_row['total_all'][0]:,} messages across {total_row['total_users'][0]:,} unique members.")

# 3. Top 10 Telegram Members from the imported history
top_tg = pd.read_sql_query("""
    SELECT 
        username,
        COUNT(*) as total_messages,
        SUM(is_pure_text) as pure_text,
        SUM(is_x_post) as x_links,
        SUM(is_gif + is_sticker) as gifs_stickers
    FROM messages
    WHERE user_id LIKE 'tg_%'
    GROUP BY user_id, username
    ORDER BY total_messages DESC
    LIMIT 10
""", conn)

print("\n[TOP 10 TELEGRAM MEMBERS (FROM 208K IMPORT)]")
print(top_tg.to_string(index=False))

# 4. Check for any anomalies or nulls
null_checks = pd.read_sql_query("""
    SELECT 
        SUM(CASE WHEN user_id IS NULL THEN 1 ELSE 0 END) as null_users,
        SUM(CASE WHEN timestamp IS NULL THEN 1 ELSE 0 END) as null_dates,
        SUM(CASE WHEN is_x_post IS NULL THEN 1 ELSE 0 END) as null_x_flags
    FROM messages
""", conn)
print("\n[DATABASE INTEGRITY CHECK]")
print(null_checks.to_string(index=False))
print("=" * 60)

conn.close()
