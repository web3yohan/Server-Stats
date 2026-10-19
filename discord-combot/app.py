import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# Set minimalist dark theme config
st.set_page_config(
    page_title="Community Engageboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern minimalist design
st.markdown("""
<style>
    .metric-card {
        background-color: #1e293b;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        text-align: center;
        border: 1px solid #334155;
        transition: transform 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-5px);
    }
    .metric-title {
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-bottom: 8px;
    }
    .metric-value {
        color: #f8fafc;
        font-size: 2.5rem;
        font-weight: 800;
    }
    .podium-card {
        padding: 24px;
        border-radius: 16px;
        text-align: center;
        margin-bottom: 24px;
        transition: transform 0.2s ease;
    }
    .podium-card:hover {
        transform: scale(1.02);
    }
</style>
""", unsafe_allow_html=True)

st.title("🏆 Community Engageboard")
st.markdown("### Advanced Admin Dashboard")

# Caching the database read for lightning-fast UI (refreshes every 60 seconds)
@st.cache_data(ttl=60)
def load_data():
    conn = sqlite3.connect('activity.db')
    try:
        df = pd.read_sql_query("SELECT * FROM messages", conn)
    except sqlite3.OperationalError:
        df = pd.DataFrame(columns=['user_id', 'username', 'message_id', 'timestamp', 'is_x_post', 'is_gif', 'is_sticker', 'is_pure_text', 'link_count'])
    finally:
        conn.close()
    
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601', utc=True)
        # Strip emojis for a perfectly clean web table
        df['username'] = df['username'].apply(lambda x: ''.join(c for c in str(x) if ord(c) < 128).strip() or "Member")
    return df

df = load_data()

st.sidebar.title("⚙️ Admin Controls")

if df.empty:
    st.info("No message activity found in the database. Run the Discord bot and send some messages!")
    st.stop()

min_date = df['timestamp'].dt.date.min()
max_date = df['timestamp'].dt.date.max()

date_range = st.sidebar.date_input(
    "📅 Filter Date Range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date
)

if len(date_range) == 2:
    start_date, end_date = date_range
    mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
    filtered_df = df.loc[mask]
else:
    filtered_df = df

if filtered_df.empty:
    st.warning("No data available for the selected dates.")
    st.stop()

# ==========================================
# KPI METRICS PANEL
# ==========================================
st.markdown("<br><h4>📊 Server Overview</h4>", unsafe_allow_html=True)
col1, col2, col3, col4 = st.columns(4)

total_msgs = len(filtered_df)
active_users = filtered_df['user_id'].nunique()
total_x = filtered_df['is_x_post'].sum()
total_media = filtered_df['is_gif'].sum() + filtered_df['is_sticker'].sum()

def render_metric(title, value):
    return f"""
    <div class="metric-card">
        <div class="metric-title">{title}</div>
        <div class="metric-value">{value}</div>
    </div>
    """

with col1:
    st.markdown(render_metric("Total Messages", f"{total_msgs:,}"), unsafe_allow_html=True)
with col2:
    st.markdown(render_metric("Active Members", f"{active_users:,}"), unsafe_allow_html=True)
with col3:
    st.markdown(render_metric("X (Twitter) Links", f"{total_x:,}"), unsafe_allow_html=True)
with col4:
    st.markdown(render_metric("GIFs & Stickers", f"{total_media:,}"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.divider()

# ==========================================
# ACTIVITY TIMELINE CHART
# ==========================================
st.markdown("#### 📈 Activity Timeline")
st.markdown("<span style='color: #94a3b8;'>Daily message volume across the selected period.</span>", unsafe_allow_html=True)
timeline_df = filtered_df.copy()
timeline_df['date'] = timeline_df['timestamp'].dt.date
daily_counts = timeline_df.groupby('date').size().reset_index(name='Messages')
# Streamlit's native aesthetic line chart
st.line_chart(daily_counts.set_index('date'), use_container_width=True, color="#3b82f6")

st.divider()

# ==========================================
# LEADERBOARD LOGIC
# ==========================================
user_stats = filtered_df.groupby(['user_id', 'username']).agg(
    total_messages=('message_id', 'count'),
    pure_messages=('is_pure_text', 'sum'),
    x_posts=('is_x_post', 'sum'),
    gifs=('is_gif', 'sum'),
    stickers=('is_sticker', 'sum')
).reset_index()

user_stats['gifs_and_stickers'] = user_stats['gifs'] + user_stats['stickers']

st.sidebar.markdown("<br>", unsafe_allow_html=True)
sort_option = st.sidebar.radio(
    "🏆 Sort Leaderboard By:", 
    ("Total Messages", "Most Pure Messages", "Most X Posts Shared")
)

if sort_option == "Total Messages":
    user_stats = user_stats.sort_values(by=['total_messages', 'pure_messages'], ascending=[False, False])
elif sort_option == "Most Pure Messages":
    user_stats = user_stats.sort_values(by=['pure_messages', 'total_messages'], ascending=[False, False])
elif sort_option == "Most X Posts Shared":
    user_stats = user_stats.sort_values(by=['x_posts', 'total_messages'], ascending=[False, False])

user_stats['Rank'] = range(1, len(user_stats) + 1)

# ==========================================
# PODIUM
# ==========================================
st.markdown("#### 🏆 The Podium")
podium_cols = st.columns(3)
top_3 = user_stats.head(3)

# Exact color matching with the Discord Bot's Pillow Image
colors = [
    {"bg": "#fef08a", "border": "#eab308", "text": "#facc15"}, # Gold
    {"bg": "#f8fafc", "border": "#94a3b8", "text": "#cbd5e1"}, # Silver
    {"bg": "#fed7aa", "border": "#f97316", "text": "#fb923c"}  # Bronze
]
titles = ["🥇 1st Place", "🥈 2nd Place", "🥉 3rd Place"]

for i in range(len(top_3)):
    row = top_3.iloc[i]
    with podium_cols[i]:
        st.markdown(
            f"""
            <div class="podium-card" style="background-color: {colors[i]['border']}15; border: 2px solid {colors[i]['border']}40; border-top: 4px solid {colors[i]['border']};">
                <h3 style="color: {colors[i]['text']}; margin: 0; font-size: 1.2rem; font-weight: 800;">{titles[i]}</h3>
                <h1 style="color: #f8fafc; margin: 15px 0; font-weight: 900;">{row['username']}</h1>
                <p style="color: #94a3b8; font-size: 1.1rem; margin: 0;"><b>{int(row['total_messages'])}</b> total messages</p>
            </div>
            """, 
            unsafe_allow_html=True
        )

# ==========================================
# MASTER TABLE WITH PROGRESS BARS
# ==========================================
st.markdown("<br>#### 📋 Full Member Rankings", unsafe_allow_html=True)

display_df = user_stats[['Rank', 'username', 'pure_messages', 'x_posts', 'gifs_and_stickers', 'total_messages']].copy()
max_msgs = int(display_df['total_messages'].max()) if not display_df.empty else 100

st.dataframe(
    display_df,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Rank": st.column_config.NumberColumn("Rank", format="#%d"),
        "username": st.column_config.TextColumn("Member"),
        "pure_messages": st.column_config.NumberColumn("Pure Messages"),
        "x_posts": st.column_config.NumberColumn("X (Twitter) Links"),
        "gifs_and_stickers": st.column_config.NumberColumn("GIFs & Stickers"),
        "total_messages": st.column_config.ProgressColumn(
            "Total Messages (Progress)",
            format="%d",
            min_value=0,
            max_value=max_msgs
        )
    }
)
