# --== bot.py (Объединённый бот со всеми функциями) ==--
import os
import asyncio
import logging
import json
import sqlite3
from datetime import datetime, timedelta
import re
from dotenv import load_dotenv

load_dotenv()

# ===== Часовой пояс Europe/Warsaw =====
def get_warsaw_tz():
    try:
        from zoneinfo import ZoneInfo
        try:
            return ZoneInfo("Europe/Warsaw")
        except Exception:
            try:
                import tzdata
                from zoneinfo import ZoneInfo as ZI2
                return ZI2("Europe/Warsaw")
            except Exception:
                pass
    except Exception:
        pass
    try:
        return datetime.now().astimezone().tzinfo
    except Exception:
        return None

WARSAW = get_warsaw_tz()

# ===== Discord =====
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, UserSelect, Select

# ===== HTTP сервер =====
from aiohttp import web

async def _health(_request):
    return web.Response(text="OK")

async def _setup_http():
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)

    host = os.getenv("HOST") or "127.0.0.1"
    ports_to_try = []
    if os.getenv("PORT"):
        try:
            ports_to_try.append(int(os.getenv("PORT")))
        except Exception:
            pass
    ports_to_try += [10000, 0]

    runner = web.AppRunner(app)
    await runner.setup()

    for port in ports_to_try:
        try:
            site = web.TCPSite(runner, host=host, port=port)
            await site.start()
            try:
                if getattr(site, "_server", None) and site._server.sockets:
                    port = site._server.sockets[0].getsockname()[1]
            except Exception:
                pass
            logging.getLogger("http").info(f"HTTP сервер здоровья на {host}:{port}")
            return
        except Exception as e:
            logging.getLogger("http").warning(f"Порт {port} не удался: {e}")
    logging.getLogger("http").warning("Сервер здоровья НЕ запущен.")

# ===== Конфигурация =====
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REQUIRED_ROLE_ID = int(os.getenv("REQUIRED_ROLE_ID", "0"))
CAPT_CHANNEL_ID = int(os.getenv("CAPT_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
LOGO_URL = os.getenv("LOGO_URL", "")
REGENT_GIF_URL = os.getenv("REGENT_GIF_URL", "")

# Настройки баллов
AP_PER_INTERVAL = float(os.getenv("AP_PER_INTERVAL", "0.5"))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "1800"))
MIN_USERS_IN_VOICE = int(os.getenv("MIN_USERS_IN_VOICE", "2"))

ROLE_BOOSTER_ID = int(os.getenv("ROLE_BOOSTER_ID", "0"))
ROLE_DONOR_ID = int(os.getenv("ROLE_DONOR_ID", "0"))
ROLE_AFK_ID = int(os.getenv("ROLE_AFK_ID", "0"))

# Настройки наград за события
CAPT_REWARD = float(os.getenv("CAPT_REWARD", "2.0"))
MCL_REWARD = float(os.getenv("MCL_REWARD", "1.5"))
ZONEWARS_REWARD = float(os.getenv("ZONEWARS_REWARD", "1.5"))

# Конфигурация Regent FamQ - ИСПРАВЛЕНО: теперь роли хранятся как ID или имя
ROLE_RECRUITER = os.getenv("ROLE_RECRUITER", "𝐑𝐞𝐜𝐫𝐮𝐢𝐭👨🏻‍💻")
ROLE_APPLICANT = os.getenv("ROLE_APPLICANT", "Подал заявку")
ROLE_OWNER = os.getenv("ROLE_OWNER", "𝙊𝙬𝙣𝙚𝙧👑")
ROLE_DEP_OWNER = os.getenv("ROLE_DEP_OWNER", "𝘿𝙚𝙥.O𝙬𝙣𝙚𝙧⭐")
TICKETS_CATEGORY_NAME = os.getenv("TICKETS_CATEGORY_NAME", "🎫𝙏𝙞𝙘𝙠𝙚𝙩")
VOICE_CHANNELS = os.getenv("VOICE_CHANNELS", "🔊Обзвон 1,🔊Обзвон 2,🔊Обзвон 3").split(",")

# Поля формы для заявок
RP_FIELDS = [
    ("Ваш игровой ник", "Введите игровой никнейм", True, 50),
    ("Ваш Discord ник", "Введите Discord тег", True, 50),
    ("Возраст", "Укажите ваш возраст", True, 3),
    ("Опыт в GTA RP", "Опишите ваш опыт", False, 200),
    ("Почему хотите в семью?", "Кратко опишите мотивацию", True, 300),
]

CAPT_FIELDS = [
    ("Ваш игровой ник", "Введите игровой никнейм", True, 50),
    ("Ваш Discord ник", "Введите Discord тег", True, 50),
    ("Готовность к PvP", "1-10", True, 2),
    ("Опыт в каптах", "Опишите ваш опыт", False, 200),
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

# ===== Глобальная проверка ролей =====
class GuildRoleGatedTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cmd = getattr(interaction, "command", None)
        name = getattr(cmd, "name", None) or getattr(cmd, "qualified_name", None)
        if str(name).lower() in {"spect", "unspect"}:
            return True

        if interaction.guild is None:
            raise app_commands.CheckFailure("Эту команду можно использовать только на сервере.")

        m: discord.Member = interaction.user
        if m.guild_permissions.administrator or m == interaction.guild.owner:
            return True
        if REQUIRED_ROLE_ID and any(r.id == REQUIRED_ROLE_ID for r in m.roles):
            return True

        raise app_commands.CheckFailure("У вас нет необходимой роли.")

bot = commands.Bot(command_prefix="!", intents=intents, tree_cls=GuildRoleGatedTree)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ============================================================
# ===================== ПРОВЕРКА ПРАВ =========================
# ============================================================

def role_required_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.CheckFailure("Эту команду можно использовать только на сервере.")
        m: discord.Member = interaction.user
        if m.guild_permissions.administrator or m == interaction.guild.owner:
            return True
        if REQUIRED_ROLE_ID and any(r.id == REQUIRED_ROLE_ID for r in m.roles):
            return True
        raise app_commands.CheckFailure("У вас нет необходимой роли.")
    return app_commands.check(predicate)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = "Произошла ошибка."
    if isinstance(error, app_commands.CheckFailure):
        msg = str(error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

# ============================================================
# ===================== БАЗА ДАННЫХ ===========================
# ============================================================

# ---- БАЗА ДАННЫХ ДЛЯ МАГАЗИНА И БАЛЛОВ ----
class ShopDB:
    def __init__(self, db_path="data/shop.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                points REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                voice_seconds INTEGER DEFAULT 0,
                last_voice_reward TIMESTAMP,
                daily_streak INTEGER DEFAULT 0,
                last_activity_date DATE
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS rewards_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                admin_id INTEGER,
                amount REAL,
                type TEXT,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT,
                emoji TEXT,
                position INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT,
                description TEXT,
                price REAL,
                stock INTEGER DEFAULT -1,
                role_id INTEGER DEFAULT 0,
                FOREIGN KEY (category_id) REFERENCES shop_categories(id)
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id INTEGER,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES shop_items(id)
            )
        ''')
        
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if not result:
            self.cursor.execute('''
                INSERT INTO users (user_id, last_voice_reward) 
                VALUES (?, ?)
            ''', (user_id, datetime.now()))
            self.conn.commit()
            return self.get_user(user_id)
        return result

    def update_points(self, user_id, amount):
        self.cursor.execute('''
            UPDATE users 
            SET points = points + ?,
                total_earned = total_earned + ?
            WHERE user_id = ?
        ''', (amount, max(0, amount), user_id))
        self.conn.commit()

    def add_voice_time(self, user_id, seconds):
        self.cursor.execute('''
            UPDATE users 
            SET voice_seconds = voice_seconds + ?,
                last_voice_reward = ?
            WHERE user_id = ?
        ''', (seconds, datetime.now(), user_id))
        self.conn.commit()

    def log_reward(self, user_id, admin_id, amount, reward_type, reason):
        self.cursor.execute('''
            INSERT INTO rewards_log (user_id, admin_id, amount, type, reason)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, admin_id, amount, reward_type, reason))
        self.conn.commit()

    def get_categories(self):
        self.cursor.execute('SELECT * FROM shop_categories ORDER BY position')
        return self.cursor.fetchall()

    def add_category(self, name, description, emoji, position=0):
        self.cursor.execute('''
            INSERT OR IGNORE INTO shop_categories (name, description, emoji, position)
            VALUES (?, ?, ?, ?)
        ''', (name, description, emoji, position))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_category(self, cat_id, name=None, description=None, emoji=None, position=None):
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if emoji is not None:
            updates.append("emoji = ?")
            params.append(emoji)
        if position is not None:
            updates.append("position = ?")
            params.append(position)
        
        if updates:
            params.append(cat_id)
            self.cursor.execute(f'''
                UPDATE shop_categories 
                SET {", ".join(updates)} 
                WHERE id = ?
            ''', params)
            self.conn.commit()

    def delete_category(self, cat_id):
        self.cursor.execute('DELETE FROM shop_items WHERE category_id = ?', (cat_id,))
        self.cursor.execute('DELETE FROM shop_categories WHERE id = ?', (cat_id,))
        self.conn.commit()

    def get_items_by_category(self, category_id):
        self.cursor.execute('SELECT * FROM shop_items WHERE category_id = ? ORDER BY id', (category_id,))
        return self.cursor.fetchall()

    def add_item(self, category_id, name, description, price, stock=-1, role_id=0):
        self.cursor.execute('''
            INSERT INTO shop_items (category_id, name, description, price, stock, role_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (category_id, name, description, price, stock, role_id))
        self.conn.commit()
        return self.cursor.lastrowid

    def update_item(self, item_id, name=None, description=None, price=None, stock=None, role_id=None):
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if price is not None:
            updates.append("price = ?")
            params.append(price)
        if stock is not None:
            updates.append("stock = ?")
            params.append(stock)
        if role_id is not None:
            updates.append("role_id = ?")
            params.append(role_id)
        
        if updates:
            params.append(item_id)
            self.cursor.execute(f'''
                UPDATE shop_items 
                SET {", ".join(updates)} 
                WHERE id = ?
            ''', params)
            self.conn.commit()

    def remove_item(self, item_id):
        self.cursor.execute('DELETE FROM shop_items WHERE id = ?', (item_id,))
        self.conn.commit()

    def purchase_item(self, user_id, item_id):
        self.cursor.execute('''
            INSERT INTO purchases (user_id, item_id)
            VALUES (?, ?)
        ''', (user_id, item_id))
        self.conn.commit()

    def get_user_purchases(self, user_id):
        self.cursor.execute('''
            SELECT item_id FROM purchases WHERE user_id = ?
        ''', (user_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def get_top_users(self, limit=10):
        self.cursor.execute('''
            SELECT user_id, points FROM users 
            ORDER BY points DESC LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()

    def update_streak(self, user_id):
        today = datetime.now().date()
        self.cursor.execute('''
            SELECT last_activity_date, daily_streak FROM users WHERE user_id = ?
        ''', (user_id,))
        result = self.cursor.fetchone()
        
        if result:
            last_date, streak = result
            if last_date:
                last_date = datetime.strptime(last_date, '%Y-%m-%d').date()
                if last_date == today:
                    return streak
                elif last_date == today - timedelta(days=1):
                    streak += 1
                    self.cursor.execute('''
                        UPDATE users SET daily_streak = ?, last_activity_date = ?
                        WHERE user_id = ?
                    ''', (streak, today, user_id))
                    self.conn.commit()
                    return streak
                else:
                    streak = 1
            else:
                streak = 1
            self.cursor.execute('''
                UPDATE users SET daily_streak = ?, last_activity_date = ?
                WHERE user_id = ?
            ''', (streak, today, user_id))
            self.conn.commit()
        return 1

shop_db = ShopDB()

# ---- БАЗА ДАННЫХ ДЛЯ ЗАЯВОК ----
class TicketsDB:
    def __init__(self, db_path="data/tickets.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    ticket_type TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    data TEXT,
                    channel_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ticket_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER,
                    action TEXT,
                    actor_id TEXT,
                    reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def create_ticket(self, user_id, ticket_type, data, channel_id=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO tickets (user_id, ticket_type, data, channel_id) VALUES (?, ?, ?, ?)",
                (str(user_id), ticket_type, json.dumps(data), channel_id)
            )
            return cursor.lastrowid

    def update_status(self, ticket_id, status, channel_id=None):
        with sqlite3.connect(self.db_path) as conn:
            if channel_id:
                conn.execute(
                    "UPDATE tickets SET status = ?, channel_id = ? WHERE id = ?",
                    (status, channel_id, ticket_id)
                )
            else:
                conn.execute(
                    "UPDATE tickets SET status = ? WHERE id = ?",
                    (status, ticket_id)
                )

    def get_ticket(self, ticket_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "user_id": row[1],
                    "ticket_type": row[2],
                    "status": row[3],
                    "data": json.loads(row[4]) if row[4] else {},
                    "channel_id": row[5],
                    "created_at": row[6]
                }
            return None

    def get_stats(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT ticket_type, status, COUNT(*) FROM tickets GROUP BY ticket_type, status"
            )
            stats = {}
            for row in cursor.fetchall():
                ticket_type, status, count = row
                if ticket_type not in stats:
                    stats[ticket_type] = {}
                stats[ticket_type][status] = count
            return stats

    def get_history(self, limit=10):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, user_id, ticket_type, status, created_at FROM tickets ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return cursor.fetchall()

tickets_db = TicketsDB()

# ===== Активные реестры =====
ACTIVE_CAPTS = {}

# ============================================================
# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==============
# ============================================================

# ===== ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ РОЛЕЙ С ПОДДЕРЖКОЙ ИМЕНИ =====
def get_role_by_name_or_id(guild: discord.Guild, role_identifier: str) -> discord.Role | None:
    """
    Получает роль по ID (если строка состоит только из цифр) или по имени.
    """
    if not role_identifier:
        return None
    
    # Пробуем как ID
    try:
        role_id = int(role_identifier)
        return guild.get_role(role_id)
    except ValueError:
        pass
    
    # Пробуем как имя
    return discord.utils.get(guild.roles, name=role_identifier)

def get_allowed_roles(guild: discord.Guild) -> list[discord.Role]:
    """
    Возвращает список ролей, которые должны иметь доступ к тикетам.
    """
    roles = []
    
    # Рекрутер
    recruiter_role = get_role_by_name_or_id(guild, ROLE_RECRUITER)
    if recruiter_role:
        roles.append(recruiter_role)
    
    # Владелец
    owner_role = get_role_by_name_or_id(guild, ROLE_OWNER)
    if owner_role:
        roles.append(owner_role)
    
    # Зам. владельца
    dep_owner_role = get_role_by_name_or_id(guild, ROLE_DEP_OWNER)
    if dep_owner_role:
        roles.append(dep_owner_role)
    
    return roles

async def send_log(guild: discord.Guild | None, actor: discord.abc.User, action: str, details: str = "", color: int = 0xFFFFFF):
    try:
        if not LOG_CHANNEL_ID:
            return
        ch = None
        if guild:
            ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch is None and bot.guilds:
            for g in bot.guilds:
                ch = ch or g.get_channel(LOG_CHANNEL_ID)
                if ch: break
        if not isinstance(ch, (discord.TextChannel, discord.Thread)):
            return
        
        desc = f"**Действие:** {action}\n**Пользователь:** {getattr(actor,'mention',str(actor))}\n"
        if details:
            desc += f"**Подробности:** {details}\n"
        emb = discord.Embed(title="Лог", description=desc, color=color)
        thumb = _thumb_url(guild or getattr(actor, 'guild', None))
        if thumb: emb.set_thumbnail(url=thumb)
        now_pl = datetime.now(tz=WARSAW) if WARSAW else datetime.now()
        emb.set_footer(text=now_pl.strftime("%d.%m.%Y %H:%M"))
        await ch.send(embed=emb)
    except Exception:
        pass

def _thumb_url(guild: discord.Guild) -> str | None:
    url = (LOGO_URL or "").strip()
    if url.lower().startswith("http"):
        return url
    try:
        if guild and guild.icon:
            return guild.icon.url
    except Exception:
        pass
    return None

def _channel_mention(guild: discord.Guild) -> str | None:
    if not CAPT_CHANNEL_ID:
        return None
    ch = guild.get_channel(CAPT_CHANNEL_ID)
    if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread)):
        return ch.mention
    return f"<#{CAPT_CHANNEL_ID}>"

def format_numbered_users(user_ids, guild: discord.Guild):
    lines = []
    for i, uid in enumerate(user_ids, start=1):
        m = guild.get_member(uid)
        lines.append(f"{i}. {m.mention} | {m.display_name}" if m else f"{i}. <@{uid}>")
    return lines

def chunk_lines(lines, max_chars: int = 1800):
    chunks, cur, cur_len = [], [], 0
    for line in lines:
        ln = len(line) + 1
        if cur_len + ln > max_chars and cur:
            chunks.append("\n".join(cur)); cur, cur_len = [line], ln
        else:
            cur.append(line); cur_len += ln
    if cur:
        chunks.append("\n".join(cur))
    return chunks

def parse_time_input(text: str):
    if not text:
        return None
    
    try:
        text = text.lower().strip()
        
        if re.match(r'^\d{1,2}:\d{2}$', text):
            h, m = map(int, text.split(':'))
            now = datetime.now()
            dt = datetime(now.year, now.month, now.day, h, m)
            if dt <= now:
                dt = dt + timedelta(days=1)
            return dt
        
        if re.match(r'^\d+$', text):
            minutes = int(text)
            return datetime.now() + timedelta(minutes=minutes)
        
        minutes_match = re.search(r'(\d+)\s*мин(ут)?(ы)?', text)
        if minutes_match:
            minutes = int(minutes_match.group(1))
            return datetime.now() + timedelta(minutes=minutes)
        
        hours_match = re.search(r'(\d+)\s*ч(ас)?(ов)?', text)
        if hours_match:
            hours = int(hours_match.group(1))
            return datetime.now() + timedelta(hours=hours)
        
        through = re.search(r'через\s*(\d+)\s*(мин|ч|час)', text)
        if through:
            num = int(through.group(1))
            unit = through.group(2)
            if unit in ['ч', 'час']:
                return datetime.now() + timedelta(hours=num)
            else:
                return datetime.now() + timedelta(minutes=num)
        
        numbers = re.findall(r'\d+', text)
        if numbers:
            num = int(numbers[0])
            if 'час' in text or 'ч ' in text:
                return datetime.now() + timedelta(hours=num)
            else:
                return datetime.now() + timedelta(minutes=num)
        
        return None
    except Exception:
        return None

def format_time_ago(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str)
        diff = datetime.now() - dt
        seconds = int(diff.total_seconds())
        
        if seconds < 60:
            return f"{seconds} секунд назад"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} минут назад"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours} час {minutes} мин назад"
            return f"{hours} часов назад"
        else:
            days = seconds // 86400
            return f"{days} дней назад"
    except Exception:
        return "неизвестно"

def format_time_until(dt_str: str) -> str:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        diff = dt - datetime.now()
        seconds = int(diff.total_seconds())
        
        if seconds < 0:
            return "уже должен вернуться"
        elif seconds < 60:
            return f"через {seconds} секунд"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"через {minutes} минут"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"через {hours} час {minutes} мин"
            return f"через {hours} часов"
        else:
            days = seconds // 86400
            return f"через {days} дней"
    except Exception:
        return None

# ============================================================
# ===================== ГЕНЕРАЦИЯ ТРАНСКРИПТА ==================
# ============================================================

async def generate_transcript(channel: discord.TextChannel, ticket_id: int) -> str:
    """Генерирует HTML транскрипт переписки в канале"""
    messages = []
    async for msg in channel.history(limit=200, oldest_first=True):
        if msg.author.bot:
            continue
        timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M")
        content = msg.content or "Вложение"
        messages.append(f'<div class="msg"><span class="time">{timestamp}</span> <span class="author">{msg.author.display_name}</span>: <span class="content">{content}</span></div>')
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Транскрипт заявки #{ticket_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }}
        .header {{ background: #16213e; padding: 15px; border-radius: 10px; margin-bottom: 20px; }}
        .msg {{ padding: 8px 12px; margin: 4px 0; background: #2a2a4a; border-radius: 6px; }}
        .time {{ color: #888; font-size: 12px; }}
        .author {{ color: #4fc3f7; font-weight: bold; }}
        .content {{ color: #eee; }}
        .footer {{ margin-top: 20px; text-align: center; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>📋 Транскрипт заявки #{ticket_id}</h2>
        <p>Канал: #{channel.name} • Создано: {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>
        <p>Всего сообщений: {len(messages)}</p>
    </div>
    {"".join(messages) if messages else '<p style="color:#888;">Нет сообщений в этом тикете.</p>'}
    <div class="footer">Транскрипт сгенерирован автоматически</div>
</body>
</html>'''
    return html

# ============================================================
# ===================== КНОПКИ ТИКЕТА ==========================
# ============================================================

class CloseTicketView(View):
    def __init__(self, ticket_id: int, channel_id: int):
        super().__init__(timeout=300)
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    @discord.ui.button(label="📄 Создать транскрипт", style=discord.ButtonStyle.primary)
    async def transcript_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.followup.send("❌ Канал не найден.", ephemeral=True)
            return
        
        html = await generate_transcript(channel, self.ticket_id)
        
        filename = f"transcript_ticket_{self.ticket_id}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)
        
        with open(filename, "rb") as f:
            file = discord.File(f, filename=filename)
            await interaction.followup.send("📄 Транскрипт создан:", file=file, ephemeral=True)
        
        os.remove(filename)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            html = await generate_transcript(channel, self.ticket_id)
            filename = f"transcript_ticket_{self.ticket_id}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html)
            
            log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                with open(filename, "rb") as f:
                    file = discord.File(f, filename=filename)
                    await log_channel.send(f"📄 Транскрипт заявки #{self.ticket_id}", file=file)
            
            os.remove(filename)
            await channel.delete(reason=f"Тикет #{self.ticket_id} закрыт")
        
        tickets_db.update_status(self.ticket_id, "closed")
        await interaction.followup.send("✅ Тикет закрыт!", ephemeral=True)

    @discord.ui.button(label="🗑️ Удалить канал", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        
        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.delete(reason=f"Канал тикета #{self.ticket_id} удалён")
        
        tickets_db.update_status(self.ticket_id, "deleted")
        await interaction.followup.send("🗑️ Канал удалён!", ephemeral=True)

# ============================================================
# ===================== CAPT С КАТЕГОРИЯМИ =====================
# ============================================================

def make_main_embed(starts_at: datetime, users: dict, guild: discord.Guild,
                    author: discord.Member, image_url: str) -> discord.Embed:
    ts = int(starts_at.timestamp())
    chan = _channel_mention(guild)
    desc = (
        "Нажмите кнопку, чтобы записаться!\n\n"
        "**Время начала:**\n"
        f"<t:{ts}:t>  •  <t:{ts}:R>\n"
    )
    if chan:
        desc += f"**Канал:** {chan}\n"
    
    total = sum(len(v) for v in users.values())
    desc += f"\n**Список ({total})**\n"

    emb = discord.Embed(title="CAPTURES!", description=desc, color=0xFFFFFF)

    for category_name, user_ids in users.items():
        if user_ids:
            user_list = []
            for i, uid in enumerate(user_ids, start=1):
                m = guild.get_member(uid)
                if m:
                    user_list.append(f"{i}. {m.mention}")
                else:
                    user_list.append(f"{i}. <@{uid}>")
            emb.add_field(name=f"{category_name} [{len(user_ids)}]", value="\n".join(user_list), inline=False)
    
    if not any(users.values()):
        emb.add_field(name="📭", value="Пока никто не записался", inline=False)

    thumb = _thumb_url(guild)
    if thumb: emb.set_thumbnail(url=thumb)
    if image_url: emb.set_image(url=image_url)

    emb.set_footer(text=f"Создано {author.display_name}")
    return emb

def make_pick_embed(selected_ids, total_count: int, guild: discord.Guild,
                    picker: discord.Member) -> discord.Embed:
    lines = []
    for i, uid in enumerate(selected_ids, start=1):
        m = guild.get_member(uid)
        lines.append(f"{i}. {m.mention} | {m.display_name}" if m else f"{i}. <@{uid}>")
    now_pl = datetime.now(tz=WARSAW) if WARSAW else datetime.now()
    desc = f"Выбрано {len(selected_ids)}/{total_count} человек:\n\n**Выбранные игроки:**\n" + ("\n".join(lines) if lines else "-")
    emb = discord.Embed(title="Список людей на captures!", description=desc, color=0xFFFFFF)
    thumb = _thumb_url(guild)
    if thumb: emb.set_thumbnail(url=thumb)
    emb.set_footer(text=f"Создано {picker.display_name} • {now_pl.strftime('%d.%m.%Y %H:%M')}")
    return emb

class CaptPagedPickView(discord.ui.View):
    PAGE_SIZE = 25
    MAX_PICK = 25

    def __init__(self, capt: "CaptView", picker: discord.Member, category: str = "Основы"):
        super().__init__(timeout=300)
        self.capt = capt
        self.picker = picker
        self.category = category
        self.page = 0
        self.page_selections: dict[int, set[int]] = {}
        users = self.capt.users.get(category, [])
        self.option_rows: list[tuple[int, str, str]] = []
        for uid in users:
            m = self.capt.guild.get_member(uid)
            label = m.display_name if m else f"Пользователь {uid}"
            desc = f"@{m.name}" if m else f"ID {uid}"
            self.option_rows.append((uid, label, desc))
        self._rebuild_select()

    def _rebuild_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
        start = self.page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        slice_rows = self.option_rows[start:end]
        options = []
        for idx, (uid, label, desc) in enumerate(slice_rows, start=1):
            options.append(discord.SelectOption(label=f"{idx}. {label}"[:100], value=str(uid), description=(desc or f"ID {uid}")[:100]))

        current_total = sum(len(s) for s in self.page_selections.values())
        remaining = max(0, self.MAX_PICK - current_total)
        total_pages = (len(self.option_rows) - 1) // self.PAGE_SIZE + 1 if self.option_rows else 1

        if not options or remaining == 0:
            max_values = 0
        else:
            max_values = min(len(options), remaining)

        sel = discord.ui.Select(
            placeholder=f"Выберите игроков (страница {self.page+1}/{total_pages})",
            min_values=0,
            max_values=max_values,
            options=options,
            disabled=(max_values == 0 and bool(options)),
        )

        async def _on_select(inter: discord.Interaction):
            chosen = {int(v) for v in (sel.values or [])}
            self.page_selections[self.page] = chosen
            current_total = sum(len(s) for s in self.page_selections.values())
            names = []
            for s in self.page_selections.values():
                for uid in s:
                    m = self.capt.guild.get_member(uid)
                    names.append(m.display_name if m else f"ID {uid}")
            txt = f"Выбрано {current_total}/{self.MAX_PICK}: " + (", ".join(names) if names else "-")
            self._rebuild_select()
            try:
                await inter.response.edit_message(content=txt, view=self)
            except Exception:
                try:
                    await inter.response.defer(ephemeral=True, thinking=False)
                    await inter.followup.send(txt, ephemeral=True, view=self)
                except Exception:
                    pass

        sel.callback = _on_select
        self.add_item(sel)

    @discord.ui.button(label="◀︎", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            self._rebuild_select()
        try:
            await interaction.response.edit_message(content=None, view=self)
        except Exception:
            await interaction.followup.send("◀︎", ephemeral=True, view=self)

    @discord.ui.button(label="▶︎", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        max_page = (len(self.option_rows) - 1) // self.PAGE_SIZE if self.option_rows else 0
        if self.page < max_page:
            self.page += 1
            self._rebuild_select()
        try:
            await interaction.response.edit_message(content=None, view=self)
        except Exception:
            await interaction.followup.send("▶︎", ephemeral=True, view=self)

    @discord.ui.button(label="Очистить выбор", style=discord.ButtonStyle.danger)
    async def clear_sel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page_selections.clear()
        self._rebuild_select()
        try:
            await interaction.response.edit_message(content="Выбор очищен.", view=self)
        except Exception:
            await interaction.followup.send("Выбор очищен.", ephemeral=True, view=self)

    @discord.ui.button(label="➡️ Оставить в записи", style=discord.ButtonStyle.success)
    async def keep_in_signup(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._move_users(interaction, "Основы")

    @discord.ui.button(label="🔄 Переместить в замену", style=discord.ButtonStyle.primary)
    async def move_to_backup(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._move_users(interaction, "Замена")

    async def _move_users(self, interaction: discord.Interaction, target_category: str):
        try:
            await interaction.response.send_message("Перемещаю...", ephemeral=True)
        except Exception:
            pass
        
        chosen: list[int] = []
        for s in self.page_selections.values():
            chosen.extend(list(s))
        chosen = list(dict.fromkeys(chosen))[:self.MAX_PICK]
        
        if not chosen:
            return await interaction.followup.send("Вы не выбрали никого.", ephemeral=True)
        
        if target_category == "Замена" and "Замена" not in self.capt.users:
            self.capt.users["Замена"] = []
        
        moved_count = 0
        mention_list = []
        
        for uid in chosen:
            for cat, user_list in self.capt.users.items():
                if uid in user_list:
                    user_list.remove(uid)
                    break
            
            if target_category not in self.capt.users:
                self.capt.users[target_category] = []
            self.capt.users[target_category].append(uid)
            moved_count += 1
            
            m = self.capt.guild.get_member(uid)
            mention_list.append(m.mention if m else f"<@{uid}>")
        
        await self.capt.refresh_announce()
        
        await interaction.followup.send(
            f"✅ **{moved_count}** человек перемещены в **{target_category}**: {', '.join(mention_list[:10])}",
            ephemeral=True
        )
        
        await send_log(self.capt.guild, interaction.user, f"CAPT: Перемещение в {target_category}", f"количество: {moved_count}")


class CaptView(discord.ui.View):
    def __init__(self, starts_at: datetime, guild: discord.Guild, author: discord.Member, image_url: str):
        try:
            remain = int((starts_at - datetime.now(tz=WARSAW)).total_seconds())
        except Exception:
            remain = 0
        timeout_seconds = max(60, remain + 3600)
        super().__init__(timeout=timeout_seconds)
        self.starts_at = starts_at
        self.users: dict[str, list[int]] = {
            "Основы": [],
            "Замена": []
        }
        self.picked_list = []
        self.confirmed = set()
        self.guild = guild
        self.author = author
        self.event_name = "CAPT"
        self.image_url = image_url
        self.message: discord.Message | None = None
        self.pick_message: discord.Message | None = None
        self._lock = asyncio.Lock()

    async def refresh_announce(self):
        if not self.message:
            return
        emb = make_main_embed(self.starts_at, self.users, self.guild, self.author, self.image_url)
        try:
            await self.message.edit(embed=emb, view=self)
        except Exception:
            try:
                ch = self.message.channel
                self.message = await ch.send(embed=emb, view=self)
            except Exception:
                pass

    async def refresh_pick_embed(self, channel: discord.abc.Messageable, picker: discord.Member):
        if not self.picked_list:
            if self.pick_message:
                try:
                    emb = make_pick_embed([], len(self.users), self.guild, picker)
                    await self.pick_message.edit(embed=emb)
                except Exception:
                    self.pick_message = None
            return
        lines = []
        for i, uid in enumerate(self.picked_list, start=1):
            m = self.guild.get_member(uid)
            emoji = '🟢' if uid in self.confirmed else '⚪'
            nm = (f"{m.mention} | {m.display_name}" if m else f"<@{uid}>")
            lines.append(f"{i}. {emoji} {nm}")
        desc = "**Список людей на captures!**\n" + ("\n".join(lines) if lines else "-")
        emb = discord.Embed(title="Список людей на captures!", description=desc, color=0xFFFFFF)
        thumb = _thumb_url(self.guild)
        if thumb: emb.set_thumbnail(url=thumb)
        if self.pick_message:
            try:
                await self.pick_message.edit(embed=emb, view=CaptPickedControlsView(self))
                return
            except Exception:
                self.pick_message = None
        try:
            msg = await channel.send(embed=emb, view=CaptPickedControlsView(self))
            self.pick_message = msg
        except Exception:
            pass

    @discord.ui.button(label="Записаться", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        async with self._lock:
            uid = interaction.user.id
            found = False
            for category, user_list in self.users.items():
                if uid in user_list:
                    found = True
                    break
            
            if not found:
                self.users["Основы"].append(uid)
        
        await interaction.response.send_message("✅ Вы записались!", ephemeral=True)
        await send_log(self.guild, interaction.user, f"{self.event_name}: Записаться", "")
        await self.refresh_announce()

    @discord.ui.button(label="Покинуть", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button):
        async with self._lock:
            uid = interaction.user.id
            changed = False
            for category, user_list in self.users.items():
                if uid in user_list:
                    user_list.remove(uid)
                    changed = True
            
            if uid in self.picked_list:
                self.picked_list.remove(uid)
                changed = True
            if uid in self.confirmed:
                self.confirmed.discard(uid)
                changed = True
        
        await interaction.response.send_message("✅ Вы покинули список.", ephemeral=True)
        if changed:
            await send_log(self.guild, interaction.user, f"{self.event_name}: Покинуть", "")
            await self.refresh_announce()
            await self.refresh_pick_embed(interaction.channel, interaction.user)

    @discord.ui.button(label="ВЫБОР", style=discord.ButtonStyle.primary)
    async def pick(self, interaction: discord.Interaction, _: discord.ui.Button):
        mem: discord.Member = interaction.user
        if not (mem.guild_permissions.administrator or mem == self.author or (REQUIRED_ROLE_ID and any(r.id == REQUIRED_ROLE_ID for r in mem.roles))):
            await interaction.response.send_message("❌ Только создатель / администратор / уполномоченная роль могут выбирать людей.", ephemeral=True)
            return
        
        total_users = sum(len(v) for v in self.users.values())
        if total_users == 0:
            await interaction.response.send_message("❌ Никто еще не записался.", ephemeral=True)
            return
        
        view = CategoryChoiceView(self)
        await interaction.response.send_message(
            "Выберите категорию, из которой хотите выбрать людей:",
            view=view,
            ephemeral=True
        )


class CategoryChoiceView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=120)
        self.capt = capt
        
        for category in capt.users.keys():
            if capt.users.get(category, []):
                self.add_item(discord.ui.Button(
                    label=category,
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"pick_category_{category}"
                ))
        
        if not self.children:
            self.add_item(discord.ui.Button(
                label="Все категории пусты",
                style=discord.ButtonStyle.secondary,
                disabled=True
            ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        for category in self.capt.users.keys():
            if interaction.data.get("custom_id") == f"pick_category_{category}":
                if not self.capt.users.get(category, []):
                    await interaction.response.send_message(f"❌ В категории **{category}** нет пользователей.", ephemeral=True)
                    return False
                
                view = CaptPagedPickView(self.capt, interaction.user, category)
                await interaction.response.send_message(
                    f"Выберите игроков из категории **{category}**.\n"
                    f"Используйте **➡️ Оставить в записи** или **🔄 Переместить в замену**.",
                    view=view,
                    ephemeral=True
                )
                return False
        return True


class CaptPickedControlsView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=300)
        self.capt = capt

    @discord.ui.button(label="ПАНЕЛЬ", style=discord.ButtonStyle.primary)
    async def open_panel(self, interaction: discord.Interaction, _: discord.ui.Button):
        mem: discord.Member = interaction.user
        if mem.guild_permissions.administrator or mem == self.capt.author or (REQUIRED_ROLE_ID and any(r.id == REQUIRED_ROLE_ID for r in mem.roles)):
            await interaction.response.send_message("Панель CAPT", view=PanelView(self.capt, mem), ephemeral=True)
        else:
            await interaction.response.send_message("Недостаточно прав для панели CAPT.", ephemeral=True)

    @discord.ui.button(label="Буду100%", style=discord.ButtonStyle.success)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.capt.picked_list:
            return await interaction.response.send_message("Вы не в списке выбранных.", ephemeral=True)
        self.capt.confirmed.add(uid)
        await self.capt.refresh_pick_embed(interaction.channel, interaction.user)
        await send_log(self.capt.guild, interaction.user, "Подтверждение CAPT", "Пользователь подтвердил 100%")
        await interaction.response.send_message("✅ Присутствие подтверждено.", ephemeral=True)

    @discord.ui.button(label="Покинуть", style=discord.ButtonStyle.danger)
    async def leave_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        uid = interaction.user.id
        changed = False
        if uid in self.capt.picked_list:
            self.capt.picked_list.remove(uid); changed = True
        if uid in self.capt.confirmed:
            self.capt.confirmed.discard(uid); changed = True
        if changed:
            await self.capt.refresh_pick_embed(interaction.channel, interaction.user)
            await send_log(self.capt.guild, interaction.user, "Покинуть CAPT", "Пользователь покинул список выбранных")
            try:
                await interaction.response.send_message("Удалено из выбранных.", ephemeral=True)
            except Exception:
                pass
        else:
            await interaction.response.send_message("Вас не было в списке выбранных.", ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self, capt: "CaptView", opener: discord.Member):
        super().__init__(timeout=600)
        self.capt = capt
        self.opener = opener

    async def _check_perms(self, interaction: discord.Interaction) -> bool:
        mem: discord.Member = interaction.user
        if mem.guild_permissions.administrator or mem == self.capt.author:
            return True
        if REQUIRED_ROLE_ID and any(r.id == REQUIRED_ROLE_ID for r in mem.roles):
            return True
        await interaction.response.send_message("Недостаточно прав для панели CAPT.", ephemeral=True)
        return False

    @discord.ui.button(label="➕ Добавить в категорию", style=discord.ButtonStyle.success)
    async def add_users(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_perms(interaction):
            return
        await interaction.response.send_message(
            "Выберите категорию для добавления людей:",
            view=CategoryAddView(self.capt),
            ephemeral=True
        )

    @discord.ui.button(label="✏️ Редактировать категории", style=discord.ButtonStyle.secondary)
    async def edit_categories(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_perms(interaction):
            return
        
        embed = discord.Embed(
            title="📂 Управление категориями",
            description="Нажмите на кнопку категории, чтобы переименовать или удалить её",
            color=0x5865F2
        )
        
        for category in self.capt.users.keys():
            count = len(self.capt.users[category])
            embed.add_field(
                name=category,
                value=f"Пользователей: {count}",
                inline=True
            )
        
        view = CategoryEditView(self.capt)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🗑️ Очистить категорию", style=discord.ButtonStyle.danger)
    async def clear_category(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_perms(interaction):
            return
        await interaction.response.send_message(
            "Выберите категорию для очистки:",
            view=CategoryClearView(self.capt),
            ephemeral=True
        )

    @discord.ui.button(label="🔙 Назад", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Панель CAPT закрыта.", view=None)


class CategoryAddView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=120)
        self.capt = capt
        
        for category in capt.users.keys():
            self.add_item(discord.ui.Button(
                label=category,
                style=discord.ButtonStyle.secondary,
                custom_id=f"add_category_{category}"
            ))
        self.add_item(discord.ui.Button(label="❌ Отмена", style=discord.ButtonStyle.danger, custom_id="add_cancel"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id") == "add_cancel":
            await interaction.response.send_message("❌ Отменено.", ephemeral=True)
            return False
        
        for category in self.capt.users.keys():
            if interaction.data.get("custom_id") == f"add_category_{category}":
                view = UserAddView(self.capt, category)
                await interaction.response.send_message(
                    f"Выберите пользователей для добавления в категорию **{category}**:",
                    view=view,
                    ephemeral=True
                )
                return False
        return True


class UserAddView(discord.ui.View):
    def __init__(self, capt: "CaptView", category: str):
        super().__init__(timeout=120)
        self.capt = capt
        self.category = category
        
        self.user_select = discord.ui.UserSelect(
            placeholder="Выберите пользователей для добавления",
            min_values=1,
            max_values=25
        )
        self.add_item(self.user_select)

    @discord.ui.button(label="✅ Добавить", style=discord.ButtonStyle.success)
    async def add_users(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.user_select.values:
            await interaction.response.send_message("❌ Вы не выбрали ни одного пользователя.", ephemeral=True)
            return
        
        added = 0
        mention_list = []
        
        for user in self.user_select.values:
            uid = user.id
            found = False
            for cat, user_list in self.capt.users.items():
                if uid in user_list:
                    found = True
                    break
            
            if not found:
                self.capt.users[self.category].append(uid)
                added += 1
                mention_list.append(user.mention)
        
        if added > 0:
            await self.capt.refresh_announce()
            await interaction.response.send_message(
                f"✅ Добавлено {added} пользователей в категорию **{self.category}**: {', '.join(mention_list[:10])}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ Все выбранные пользователи уже находятся в других категориях.", ephemeral=True)


class CategoryEditView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=120)
        self.capt = capt

    @discord.ui.button(label="✏️ Переименовать", style=discord.ButtonStyle.primary)
    async def rename_category(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Выберите категорию для переименования:",
            view=CategoryRenameSelectView(self.capt),
            ephemeral=True
        )

    @discord.ui.button(label="🗑️ Удалить категорию", style=discord.ButtonStyle.danger)
    async def delete_category(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Выберите категорию для удаления:",
            view=CategoryDeleteSelectView(self.capt),
            ephemeral=True
        )

    @discord.ui.button(label="➕ Новая категория", style=discord.ButtonStyle.success)
    async def new_category(self, interaction: discord.Interaction, _: discord.ui.Button):
        modal = NewCategoryModal(self.capt)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔙 Назад", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(content="Панель CAPT", view=PanelView(self.capt, interaction.user))


class CategoryRenameSelectView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=120)
        self.capt = capt
        
        for category in capt.users.keys():
            self.add_item(discord.ui.Button(
                label=category,
                style=discord.ButtonStyle.secondary,
                custom_id=f"rename_{category}"
            ))
        self.add_item(discord.ui.Button(label="❌ Отмена", style=discord.ButtonStyle.danger, custom_id="rename_cancel"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id") == "rename_cancel":
            await interaction.response.send_message("❌ Отменено.", ephemeral=True)
            return False
        
        for category in self.capt.users.keys():
            if interaction.data.get("custom_id") == f"rename_{category}":
                modal = RenameCategoryModal(self.capt, category)
                await interaction.response.send_modal(modal)
                return False
        return True


class RenameCategoryModal(discord.ui.Modal, title="Переименовать категорию"):
    def __init__(self, capt: "CaptView", old_name: str):
        super().__init__()
        self.capt = capt
        self.old_name = old_name
        
        self.new_name = discord.ui.TextInput(
            label="Новое название категории",
            placeholder="Введите новое название",
            required=True,
            max_length=50
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.new_name.value.strip()
        
        if not new_name:
            await interaction.response.send_message("❌ Название не может быть пустым.", ephemeral=True)
            return
        
        if new_name in self.capt.users and new_name != self.old_name:
            await interaction.response.send_message(f"❌ Категория **{new_name}** уже существует.", ephemeral=True)
            return
        
        users = self.capt.users.pop(self.old_name)
        self.capt.users[new_name] = users
        
        await self.capt.refresh_announce()
        await interaction.response.send_message(f"✅ Категория **{self.old_name}** переименована в **{new_name}**.", ephemeral=True)


class CategoryDeleteSelectView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=120)
        self.capt = capt
        
        for category in capt.users.keys():
            self.add_item(discord.ui.Button(
                label=category,
                style=discord.ButtonStyle.danger,
                custom_id=f"delete_{category}"
            ))
        self.add_item(discord.ui.Button(label="❌ Отмена", style=discord.ButtonStyle.secondary, custom_id="delete_cancel"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id") == "delete_cancel":
            await interaction.response.send_message("❌ Отменено.", ephemeral=True)
            return False
        
        for category in self.capt.users.keys():
            if interaction.data.get("custom_id") == f"delete_{category}":
                view = ConfirmDeleteView(self.capt, category)
                await interaction.response.send_message(
                    f"⚠️ Вы уверены, что хотите удалить категорию **{category}**?\n"
                    f"В ней {len(self.capt.users[category])} пользователей.",
                    view=view,
                    ephemeral=True
                )
                return False
        return True


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, capt: "CaptView", category: str):
        super().__init__(timeout=60)
        self.capt = capt
        self.category = category

    @discord.ui.button(label="✅ Да, удалить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.category in self.capt.users:
            del self.capt.users[self.category]
            await self.capt.refresh_announce()
            await interaction.response.send_message(f"✅ Категория **{self.category}** удалена.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Категория **{self.category}** не найдена.", ephemeral=True)

    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message("❌ Отменено.", ephemeral=True)


class NewCategoryModal(discord.ui.Modal, title="Создать новую категорию"):
    def __init__(self, capt: "CaptView"):
        super().__init__()
        self.capt = capt
        
        self.category_name = discord.ui.TextInput(
            label="Название категории",
            placeholder="Введите название новой категории",
            required=True,
            max_length=50
        )
        self.add_item(self.category_name)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.category_name.value.strip()
        
        if not name:
            await interaction.response.send_message("❌ Название не может быть пустым.", ephemeral=True)
            return
        
        if name in self.capt.users:
            await interaction.response.send_message(f"❌ Категория **{name}** уже существует.", ephemeral=True)
            return
        
        self.capt.users[name] = []
        await self.capt.refresh_announce()
        await interaction.response.send_message(f"✅ Категория **{name}** создана.", ephemeral=True)


class CategoryClearView(discord.ui.View):
    def __init__(self, capt: "CaptView"):
        super().__init__(timeout=120)
        self.capt = capt
        
        for category, user_list in capt.users.items():
            if user_list:
                self.add_item(discord.ui.Button(
                    label=f"{category} ({len(user_list)})",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"clear_{category}"
                ))
        
        if not any(capt.users.values()):
            self.add_item(discord.ui.Button(
                label="Все категории пусты",
                style=discord.ButtonStyle.secondary,
                disabled=True
            ))
        
        self.add_item(discord.ui.Button(label="❌ Отмена", style=discord.ButtonStyle.secondary, custom_id="clear_cancel"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id") == "clear_cancel":
            await interaction.response.send_message("❌ Отменено.", ephemeral=True)
            return False
        
        for category in self.capt.users.keys():
            if interaction.data.get("custom_id") == f"clear_{category}":
                self.capt.users[category] = []
                await self.capt.refresh_announce()
                await interaction.response.send_message(f"✅ Категория **{category}** очищена.", ephemeral=True)
                return False
        return True

# ============================================================
# ===================== MCL / ZoneWars (ОБНОВЛЕН) =============
# ============================================================

class MclView(discord.ui.View):
    def __init__(self, title_text: str, voice: discord.VoiceChannel, start_at: datetime, tp_at: datetime, guild: discord.Guild, author: discord.Member, event_name: str = "MCL", max_pick: int = 20):
        remain = int((tp_at - datetime.now(tz=WARSAW)).total_seconds()) if WARSAW else 0
        super().__init__(timeout=max(60, remain + 3600))
        self.title_text = title_text
        self.voice = voice
        self.start_at = start_at
        self.tp_at = tp_at
        self.guild = guild
        self.author = author
        self.event_name = event_name
        self.message: discord.Message | None = None
        self.max_pick = int(max(1, max_pick))
        # Структура как у CAPT - категории
        self.users: dict[str, list[int]] = {
            "Основы": [],
            "Замена": []
        }
        self.selected_ids: list[int] = []
        self.confirmed: set[int] = set()
        self.extra_labels: dict[int, str] = {}
        self._lock = asyncio.Lock()

    async def refresh_main(self):
        if not self.message:
            return
        emb = self.make_embed()
        try:
            await self.message.edit(embed=emb, view=self)
        except Exception:
            try:
                ch = self.message.channel
                self.message = await ch.send(embed=emb, view=self)
            except Exception:
                pass

    def make_embed(self):
        ts_start = int(self.start_at.timestamp())
        ts_tp = int(self.tp_at.timestamp())
        
        total = sum(len(v) for v in self.users.values())
        
        desc = (
            f"**Начало:** <t:{ts_start}:t> • <t:{ts_start}:R>\n"
            f"**Телепортация:** <t:{ts_tp}:t> • <t:{ts_tp}:R>\n"
            f"**Голосовой канал:** {self.voice.mention}\n\n"
            f"**Список ({total})**\n"
        )
        
        # Добавляем категории
        for category_name, user_ids in self.users.items():
            if user_ids:
                user_list = []
                for i, uid in enumerate(user_ids, start=1):
                    m = self.guild.get_member(uid)
                    if m:
                        user_list.append(f"{i}. {m.mention}")
                    else:
                        user_list.append(f"{i}. <@{uid}>")
                desc += f"\n**{category_name} [{len(user_ids)}]**\n" + "\n".join(user_list)
        
        if total == 0:
            desc += "\n📭 Пока никто не записался"
        
        emb = discord.Embed(title=self.title_text, description=desc, color=0xFFFFFF)
        thumb = _thumb_url(self.guild)
        if thumb:
            emb.set_thumbnail(url=thumb)
        emb.set_footer(text=f"Создано {self.author.display_name}")
        return emb

    def make_selected_embed(self, picker: discord.Member):
        now_pl = datetime.now(tz=WARSAW) if WARSAW else datetime.now()
        lines = []
        for i, uid in enumerate(self.selected_ids, start=1):
            m = self.guild.get_member(uid)
            extra = self.extra_labels.get(uid, "").strip()
            emoji = '🟢' if uid in self.confirmed else '⚪'
            if m:
                row = f"{i}. {emoji} {m.mention}"
                if extra:
                    row += f" | {extra}"
            else:
                row = f"{i}. {emoji} <@{uid}>"
                if extra:
                    row += f" | {extra}"
            lines.append(row)
        desc = f"**Выбранные на {self.event_name}!**\n" + ("\n".join(lines) if lines else "-")
        emb = discord.Embed(title=f"Выбранные на {self.event_name}!", description=desc, color=0xFFFFFF)
        thumb = _thumb_url(self.guild)
        if thumb:
            emb.set_thumbnail(url=thumb)
        emb.set_footer(text=f"Выбрал: {picker.display_name} • {now_pl.strftime('%d.%m.%Y %H:%M')}")
        return emb

    @discord.ui.button(label="Записаться", style=discord.ButtonStyle.success)
    async def join_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        async with self._lock:
            uid = interaction.user.id
            found = False
            for category, user_list in self.users.items():
                if uid in user_list:
                    found = True
                    break
            
            if not found:
                self.users["Основы"].append(uid)
        
        await interaction.response.send_message("✅ Вы записались!", ephemeral=True)
        await send_log(self.guild, interaction.user, f"{self.event_name}: Записаться", "")
        await self.refresh_main()

    @discord.ui.button(label="Покинуть", style=discord.ButtonStyle.danger)
    async def leave_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        async with self._lock:
            uid = interaction.user.id
            changed = False
            for category, user_list in self.users.items():
                if uid in user_list:
                    user_list.remove(uid)
                    changed = True
            
            if uid in self.selected_ids:
                self.selected_ids.remove(uid)
                changed = True
            if uid in self.confirmed:
                self.confirmed.discard(uid)
                changed = True
        
        await interaction.response.send_message("✅ Вы покинули список.", ephemeral=True)
        if changed:
            await send_log(self.guild, interaction.user, f"{self.event_name}: Покинуть", "")
            await self.refresh_main()

    @discord.ui.button(label="ВЫБОР", style=discord.ButtonStyle.primary)
    async def pick_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        mem: discord.Member = interaction.user
        if not (mem.guild_permissions.administrator or mem == self.author or (REQUIRED_ROLE_ID and any(r.id == REQUIRED_ROLE_ID for r in mem.roles))):
            await interaction.response.send_message("❌ Только создатель / администратор / уполномоченная роль могут выбирать людей.", ephemeral=True)
            return
        
        total_users = sum(len(v) for v in self.users.values())
        if total_users == 0:
            await interaction.response.send_message("❌ Никто еще не записался.", ephemeral=True)
            return
        
        # Показываем выбор категории
        view = MclCategoryChoiceView(self)
        await interaction.response.send_message(
            "Выберите категорию, из которой хотите выбрать людей:",
            view=view,
            ephemeral=True
        )


class MclCategoryChoiceView(discord.ui.View):
    def __init__(self, mcl: "MclView"):
        super().__init__(timeout=120)
        self.mcl = mcl
        
        for category in mcl.users.keys():
            if mcl.users.get(category, []):
                self.add_item(discord.ui.Button(
                    label=category,
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"mcl_pick_category_{category}"
                ))
        
        if not self.children:
            self.add_item(discord.ui.Button(
                label="Все категории пусты",
                style=discord.ButtonStyle.secondary,
                disabled=True
            ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        for category in self.mcl.users.keys():
            if interaction.data.get("custom_id") == f"mcl_pick_category_{category}":
                if not self.mcl.users.get(category, []):
                    await interaction.response.send_message(f"❌ В категории **{category}** нет пользователей.", ephemeral=True)
                    return False
                
                view = MclPagedPickView(self.mcl, interaction.user, category)
                await interaction.response.send_message(
                    f"Выберите игроков из категории **{category}**.\n"
                    f"Используйте **➡️ Оставить в записи** или **🔄 Переместить в замену**.",
                    view=view,
                    ephemeral=True
                )
                return False
        return True


class MclPagedPickView(discord.ui.View):
    PAGE_SIZE = 25

    def __init__(self, mcl: "MclView", picker: discord.Member, category: str = "Основы"):
        super().__init__(timeout=300)
        self.mcl = mcl
        self.picker = picker
        self.category = category
        self.page = 0
        self.page_selections: dict[int, set[int]] = {}
        users = self.mcl.users.get(category, [])
        self.option_rows: list[tuple[int, str, str]] = []
        for uid in users:
            m = self.mcl.guild.get_member(uid)
            label = m.display_name if m else f"Пользователь {uid}"
            desc = f"@{m.name}" if m else f"ID {uid}"
            self.option_rows.append((uid, label, desc))
        self._rebuild_select()

    def _rebuild_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
        start = self.page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        slice_rows = self.option_rows[start:end]
        options = []
        for idx, (uid, label, desc) in enumerate(slice_rows, start=1):
            options.append(discord.SelectOption(label=f"{idx}. {label}"[:100], value=str(uid), description=(desc or f"ID {uid}")[:100]))

        current_total = sum(len(s) for s in self.page_selections.values())
        max_pick = getattr(self.mcl, "max_pick", 20)
        remaining = max(0, max_pick - current_total)
        total_pages = (len(self.option_rows) - 1) // self.PAGE_SIZE + 1 if self.option_rows else 1

        if not options or remaining == 0:
            max_values = 0
        else:
            max_values = min(len(options), remaining)

        sel = discord.ui.Select(
            placeholder=f"Выберите игроков (страница {self.page+1}/{total_pages})",
            min_values=0,
            max_values=max_values,
            options=options,
            disabled=(max_values == 0 and bool(options)),
        )

        async def _on_select(inter: discord.Interaction):
            chosen = {int(v) for v in (sel.values or [])}
            self.page_selections[self.page] = chosen
            current_total = sum(len(s) for s in self.page_selections.values())
            names = []
            for s in self.page_selections.values():
                for uid in s:
                    try:
                        m = self.mcl.guild.get_member(uid)
                        names.append(m.display_name if m else f"ID {uid}")
                    except Exception:
                        names.append(f"ID {uid}")
            txt = f"Выбрано {current_total}/{getattr(self.mcl, 'max_pick', 20)}:\n" + (", ".join(names) if names else "-")
            self._rebuild_select()
            try:
                await inter.response.edit_message(content=txt, view=self)
            except Exception:
                try:
                    await inter.response.defer(ephemeral=True, thinking=False)
                except Exception:
                    pass

        sel.callback = _on_select
        self.add_item(sel)

    @discord.ui.button(label="◀︎", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            self._rebuild_select()
        try:
            await interaction.response.edit_message(content=None, view=self)
        except Exception:
            await interaction.followup.send("◀︎", ephemeral=True, view=self)

    @discord.ui.button(label="▶︎", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        max_page = (len(self.option_rows) - 1) // self.PAGE_SIZE if self.option_rows else 0
        if self.page < max_page:
            self.page += 1
            self._rebuild_select()
        try:
            await interaction.response.edit_message(content=None, view=self)
        except Exception:
            await interaction.followup.send("▶︎", ephemeral=True, view=self)

    @discord.ui.button(label="Очистить выбор", style=discord.ButtonStyle.danger)
    async def clear_sel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page_selections.clear()
        self._rebuild_select()
        try:
            await interaction.response.edit_message(content="Выбор очищен.", view=self)
        except Exception:
            await interaction.followup.send("Выбор очищен.", ephemeral=True, view=self)

    @discord.ui.button(label="➡️ Оставить в записи", style=discord.ButtonStyle.success)
    async def keep_in_signup(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._move_users(interaction, "Основы")

    @discord.ui.button(label="🔄 Переместить в замену", style=discord.ButtonStyle.primary)
    async def move_to_backup(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._move_users(interaction, "Замена")

    async def _move_users(self, interaction: discord.Interaction, target_category: str):
        try:
            await interaction.response.send_message("Перемещаю...", ephemeral=True)
        except Exception:
            pass
        
        chosen: list[int] = []
        for s in self.page_selections.values():
            chosen.extend(list(s))
        chosen = list(dict.fromkeys(chosen))[:getattr(self.mcl, 'max_pick', 20)]
        
        if not chosen:
            return await interaction.followup.send("Вы не выбрали никого.", ephemeral=True)
        
        if target_category == "Замена" and "Замена" not in self.mcl.users:
            self.mcl.users["Замена"] = []
        
        moved_count = 0
        mention_list = []
        
        for uid in chosen:
            for cat, user_list in self.mcl.users.items():
                if uid in user_list:
                    user_list.remove(uid)
                    break
            
            if target_category not in self.mcl.users:
                self.mcl.users[target_category] = []
            self.mcl.users[target_category].append(uid)
            moved_count += 1
            
            m = self.mcl.guild.get_member(uid)
            mention_list.append(m.mention if m else f"<@{uid}>")
        
        await self.mcl.refresh_main()
        
        await interaction.followup.send(
            f"✅ **{moved_count}** человек перемещены в **{target_category}**: {', '.join(mention_list[:10])}",
            ephemeral=True
        )
        
        await send_log(self.mcl.guild, interaction.user, f"{self.mcl.event_name}: Перемещение в {target_category}", f"количество: {moved_count}")

# ============================================================
# ===================== REGENT FAMQ ===========================
# ============================================================

REGENT_INFO = """
**Путь в семью начинается здесь!**

> • Заявки в семью принимаются только на сервер **Phoenix**. Уведомление о приглашении на обзвон отправляется в ЛС (или в канал, если ЛС закрыты).

> • **Внимательно прочитайте ВСЕ ВОПРОСЫ** при подаче заявки, как основные, так и дополнительные внутри поля для ответа. Если не ответили на все вопросы — **ЗАЯВКА ОТКЛОНЯЕТСЯ.**

---

**⏳ Срок рассмотрения заявки:** от **2 до 7 дней.**

**⚠️ Важно:** если у вас нет скилов / подходящих откатов — заявка будет **ОТКЛОНЕНА.**

---

**📋 Дополнительные правила к подаче заявки:**

> • Откаты с GG — не более 1 недели назад (не менее 5 минут).
> • Откаты с МП (B33, MCL, Capt) — не более 60 дней назад.
> • Откаты не в виде мувика/нарезки.
> • Откаты должны быть с сайта и со спешим/тяжким (минимум 2 отката).
> • Любое нарушение условий — заявка **ОТКЛОНЕНА.**

---

"""

@bot.command(name="regent")
async def regent_command(ctx: commands.Context):
    icon_url = ctx.guild.icon.url if ctx.guild.icon else None
    
    embed = discord.Embed(
        title="🎫 **Подать заявку в Семью**",
        description=REGENT_INFO,
        color=0x2B2D31
    )
    
    embed.set_author(
        name="Talentless Clxn",
        icon_url=icon_url
    )
    
    embed.set_footer(
        text=f"Нажмите на кнопку ниже • {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        icon_url=icon_url
    )
    
    if REGENT_GIF_URL:
        embed.set_image(url=REGENT_GIF_URL)
    
    view = View()
    view.add_item(Button(
        label="📝 Подать заявку",
        style=discord.ButtonStyle.primary,
        custom_id="rp_ticket"
    ))
    
    await ctx.send(embed=embed, view=view)

class RegentTicketModal(Modal):
    def __init__(self, ticket_type: str):
        super().__init__(title=f"📝 Подача {ticket_type} заявки")
        self.ticket_type = ticket_type
        fields = RP_FIELDS if ticket_type == "RP" else CAPT_FIELDS
        for label, placeholder, required, max_length in fields:
            self.add_item(TextInput(
                label=label,
                placeholder=placeholder,
                required=required,
                max_length=max_length,
                style=discord.TextStyle.paragraph if max_length > 100 else discord.TextStyle.short
            ))

    async def on_submit(self, interaction: discord.Interaction):
        data = {child.label: child.value for child in self.children}
        user_id = str(interaction.user.id)

        ticket_id = tickets_db.create_ticket(user_id, self.ticket_type, data)

        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=TICKETS_CATEGORY_NAME)
        if not category:
            category = await guild.create_category(TICKETS_CATEGORY_NAME)

        # ИСПРАВЛЕНО: получаем все роли с поддержкой имени через get_allowed_roles
        allowed_roles = get_allowed_roles(guild)
        recruiter_role = get_role_by_name_or_id(guild, ROLE_RECRUITER)
        owner_role = get_role_by_name_or_id(guild, ROLE_OWNER)
        dep_owner_role = get_role_by_name_or_id(guild, ROLE_DEP_OWNER)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
        }
        
        # Добавляем все роли, которые имеют доступ
        for role in allowed_roles:
            overwrites[role] = discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True,
                attach_files=True,
                embed_links=True
            )

        channel = await guild.create_text_channel(
            f"заявка-{ticket_id}",
            category=category,
            overwrites=overwrites
        )

        tickets_db.update_status(ticket_id, "pending", str(channel.id))

        applicant_role = get_role_by_name_or_id(guild, ROLE_APPLICANT)
        if applicant_role:
            try:
                await interaction.user.add_roles(applicant_role)
            except Exception:
                pass

        icon_url = guild.icon.url if guild.icon else None
        
        embed = discord.Embed(
            title=f"📋 Заявка #{ticket_id}",
            color=0x2B2D31,
            timestamp=datetime.now()
        )
        
        embed.set_author(
            name="Talentless Clxn",
            icon_url=icon_url
        )
        
        field_mapping = {
            "Ваш игровой ник": "🎮 Ваш ник в игре",
            "Ваш Discord ник": "💬 Статик #",
            "Возраст": "📅 Возраст",
            "Опыт в GTA RP": "📈 Опыт в GTA RP",
            "Почему хотите в семью?": "💭 Почему хотите в семью?",
            "Готовность к PvP": "⚔️ Готовность к PvP",
            "Опыт в каптах": "🎯 Опыт в каптах"
        }
        
        for key, value in data.items():
            if value and value.strip():
                display_name = field_mapping.get(key, key)
                embed.add_field(
                    name=display_name,
                    value=f"```{value}```",
                    inline=False
                )
        
        embed.add_field(
            name="👤 Пользователь",
            value=interaction.user.mention,
            inline=True
        )
        embed.add_field(
            name="🔹 Username",
            value=interaction.user.name,
            inline=True
        )
        embed.add_field(
            name="🆔 ID",
            value=interaction.user.id,
            inline=True
        )
        
        embed.add_field(
            name="📌 Кого",
            value=interaction.user.mention,
            inline=False
        )
        
        embed.set_footer(
            text=f"ID: {ticket_id} • {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            icon_url=icon_url
        )

        view = TicketActionsView(ticket_id, channel.id)

        ping_msg = ""
        if recruiter_role:
            ping_msg = recruiter_role.mention
        await channel.send(content=f"{ping_msg}", embed=embed, view=view)

        try:
            dm_embed = discord.Embed(
                title="✅ Заявка подана!",
                description=f"Ваша {self.ticket_type} заявка #{ticket_id} успешно создана.",
                color=0x00FF00
            )
            dm_embed.add_field(name="Канал", value=f"{channel.mention}", inline=False)
            await interaction.user.send(embed=dm_embed)
        except Exception:
            pass

        await interaction.response.send_message(
            f"✅ Заявка #{ticket_id} создана! Канал: {channel.mention}",
            ephemeral=True
        )

        await send_log(guild, interaction.user, f"Заявка", f"Новая {self.ticket_type} заявка | ID: {ticket_id}")

class TicketActionsView(View):
    def __init__(self, ticket_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    @discord.ui.button(label="📝 Взять на рассмотрение", style=discord.ButtonStyle.primary)
    async def review_ticket(self, interaction: discord.Interaction, button: Button):
        ticket = tickets_db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
            return

        tickets_db.update_status(self.ticket_id, "review")

        embed = discord.Embed(
            title=f"🟡 Заявка #{self.ticket_id}",
            description=f"Заявка взята на рассмотрение {interaction.user.mention}",
            color=0xFFFF00,
            timestamp=datetime.now()
        )
        embed.add_field(name="Статус", value="🟡 На рассмотрении", inline=False)

        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.send(embed=embed)

        embed = discord.Embed(
            title=f"Заявка #{ticket['id']}",
            color=0xFFFF00,
            timestamp=datetime.now()
        )
        
        field_mapping = {
            "Ваш игровой ник": "🎮 Ваш ник в игре",
            "Ваш Discord ник": "💬 Статик #",
            "Возраст": "📅 Возраст",
            "Опыт в GTA RP": "📈 Опыт в GTA RP",
            "Почему хотите в семью?": "💭 Почему хотите в семью?",
            "Готовность к PvP": "⚔️ Готовность к PvP",
            "Опыт в каптах": "🎯 Опыт в каптах"
        }
        
        for key, value in ticket['data'].items():
            if value and value.strip():
                display_name = field_mapping.get(key, key)
                embed.add_field(
                    name=display_name,
                    value=f"```{value}```",
                    inline=False
                )
        
        try:
            user = await bot.fetch_user(int(ticket['user_id']))
            embed.add_field(name="👤 Пользователь", value=user.mention, inline=True)
            embed.add_field(name="🔹 Username", value=user.name, inline=True)
            embed.add_field(name="🆔 ID", value=user.id, inline=True)
            embed.add_field(name="📌 Кого", value=user.mention, inline=False)
        except Exception:
            embed.add_field(name="👤 Пользователь", value=f"<@{ticket['user_id']}>", inline=True)
            embed.add_field(name="📌 Кого", value=f"<@{ticket['user_id']}>", inline=False)
        
        embed.add_field(name="📌 Статус", value="🟡 На рассмотрении", inline=False)
        embed.set_footer(text=f"ID: {ticket['id']}")

        view = TicketReviewView(self.ticket_id, self.channel_id)
        await interaction.response.edit_message(embed=embed, view=view)
        
        await send_log(interaction.guild, interaction.user, "Заявка", f"Взята на рассмотрение | ID: {self.ticket_id}", color=0xFFFF00)

class TicketReviewView(View):
    def __init__(self, ticket_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.success)
    async def accept_ticket(self, interaction: discord.Interaction, button: Button):
        await self._handle_action(interaction, "accepted", "✅ Заявка принята!", 0x00FF00)
        ticket = tickets_db.get_ticket(self.ticket_id)
        if ticket:
            user_id = int(ticket['user_id'])
            shop_db.update_points(user_id, 1.0)
            shop_db.log_reward(user_id, interaction.user.id, 1.0, "TICKET", f"Заявка #{self.ticket_id} принята")
        await self._close_ticket(interaction)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger)
    async def deny_ticket(self, interaction: discord.Interaction, button: Button):
        modal = DenyReasonModal(self.ticket_id, self.channel_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔊 Обзвон", style=discord.ButtonStyle.primary)
    async def call_voice(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        voice_channels = []
        for vc_name in VOICE_CHANNELS:
            vc = discord.utils.get(guild.voice_channels, name=vc_name.strip())
            if vc:
                voice_channels.append(vc)

        if not voice_channels:
            await interaction.response.send_message("❌ Нет доступных голосовых каналов для обзвона.", ephemeral=True)
            return

        view = VoiceCallView(self.ticket_id, voice_channels)
        await interaction.response.send_message("Выберите канал для обзвона:", view=view, ephemeral=True)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary)
    async def refresh_ticket(self, interaction: discord.Interaction, button: Button):
        ticket = tickets_db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Заявка #{ticket['id']}",
            color=0xFFFF00 if ticket['status'] == "review" else 0x2B2D31,
            timestamp=datetime.now()
        )
        
        field_mapping = {
            "Ваш игровой ник": "🎮 Ваш ник в игре",
            "Ваш Discord ник": "💬 Статик #",
            "Возраст": "📅 Возраст",
            "Опыт в GTA RP": "📈 Опыт в GTA RP",
            "Почему хотите в семью?": "💭 Почему хотите в семью?",
            "Готовность к PvP": "⚔️ Готовность к PvP",
            "Опыт в каптах": "🎯 Опыт в каптах"
        }
        
        for key, value in ticket['data'].items():
            if value and value.strip():
                display_name = field_mapping.get(key, key)
                embed.add_field(
                    name=display_name,
                    value=f"```{value}```",
                    inline=False
                )
        
        try:
            user = await bot.fetch_user(int(ticket['user_id']))
            embed.add_field(name="👤 Пользователь", value=user.mention, inline=True)
            embed.add_field(name="🔹 Username", value=user.name, inline=True)
            embed.add_field(name="🆔 ID", value=user.id, inline=True)
            embed.add_field(name="📌 Кого", value=user.mention, inline=False)
        except Exception:
            embed.add_field(name="👤 Пользователь", value=f"<@{ticket['user_id']}>", inline=True)
            embed.add_field(name="📌 Кого", value=f"<@{ticket['user_id']}>", inline=False)
        
        status_text = "🟡 На рассмотрении" if ticket['status'] == "review" else "📋 Ожидает"
        embed.add_field(name="📌 Статус", value=status_text, inline=False)
        embed.set_footer(text=f"ID: {ticket['id']}")

        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger)
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        view = CloseTicketView(self.ticket_id, self.channel_id)
        await interaction.response.send_message(
            "Выберите действие с тикетом:",
            view=view,
            ephemeral=True
        )

    async def _send_dm(self, user_id: int, title: str, description: str, color: int):
        try:
            user = await bot.fetch_user(user_id)
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.now()
            )
            await user.send(embed=embed)
        except Exception:
            pass

    async def _close_ticket(self, interaction: discord.Interaction):
        ticket = tickets_db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.delete(reason=f"Тикет #{self.ticket_id} закрыт")

        tickets_db.update_status(self.ticket_id, "closed")

        applicant_role = get_role_by_name_or_id(interaction.guild, ROLE_APPLICANT)
        if applicant_role:
            try:
                member = interaction.guild.get_member(int(ticket['user_id']))
                if member:
                    await member.remove_roles(applicant_role)
            except Exception:
                pass

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("✅ Заявка закрыта.", ephemeral=True)
            else:
                await interaction.followup.send("✅ Заявка закрыта.", ephemeral=True)
        except Exception:
            pass
            
        await send_log(interaction.guild, interaction.user, "Заявка", f"Закрыта | ID: {self.ticket_id}", color=0x808080)

    async def _handle_action(self, interaction: discord.Interaction, status: str, message: str, color: int):
        ticket = tickets_db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
            return

        tickets_db.update_status(self.ticket_id, status)

        embed = discord.Embed(
            title=message,
            description=f"Заявка #{self.ticket_id} обработана {interaction.user.mention}",
            color=color,
            timestamp=datetime.now()
        )

        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.send(embed=embed)
            
        await send_log(interaction.guild, interaction.user, "Заявка", f"{'Принята' if status == 'accepted' else 'Отклонена'} | ID: {self.ticket_id}", color=color)
        
        status_text = "принята ✅" if status == "accepted" else "отклонена ❌"
        await self._send_dm(
            int(ticket['user_id']),
            f"📋 Результат рассмотрения заявки #{self.ticket_id}",
            f"Ваша заявка была **{status_text}**!\n\n"
            f"**Статус:** {status_text}\n"
            f"**Обработал:** {interaction.user.mention}\n"
            f"**Заявка:** #{self.ticket_id}",
            color
        )

class DenyReasonModal(Modal, title="Причина отклонения"):
    def __init__(self, ticket_id: int, channel_id: int):
        super().__init__()
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    reason = TextInput(
        label="Причина отклонения",
        placeholder="Укажите причину...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        ticket = tickets_db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
            return

        tickets_db.update_status(self.ticket_id, "denied")

        embed = discord.Embed(
            title="❌ Заявка отклонена",
            description=f"Заявка #{self.ticket_id} отклонена {interaction.user.mention}",
            color=0xFF0000,
            timestamp=datetime.now()
        )
        embed.add_field(name="Причина", value=self.reason.value, inline=False)

        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.send(embed=embed)

        await self._close_ticket(interaction)

        try:
            await interaction.response.send_message("✅ Заявка отклонена.", ephemeral=True)
        except Exception:
            pass

        await send_log(interaction.guild, interaction.user, "Заявка", f"Отклонена | ID: {self.ticket_id}", color=0xFF0000)
        
        await self._send_dm(
            int(ticket['user_id']),
            f"📋 Результат рассмотрения заявки #{self.ticket_id}",
            f"Ваша заявка была **отклонена ❌**!\n\n"
            f"**Причина:** {self.reason.value}\n"
            f"**Обработал:** {interaction.user.mention}\n"
            f"**Заявка:** #{self.ticket_id}",
            0xFF0000
        )

    async def _send_dm(self, user_id: int, title: str, description: str, color: int):
        try:
            user = await bot.fetch_user(user_id)
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.now()
            )
            await user.send(embed=embed)
        except Exception:
            pass

    async def _close_ticket(self, interaction: discord.Interaction):
        ticket = tickets_db.get_ticket(self.ticket_id)
        if not ticket:
            return

        channel = interaction.guild.get_channel(self.channel_id)
        if channel:
            await channel.delete(reason=f"Тикет #{self.ticket_id} закрыт")

        tickets_db.update_status(self.ticket_id, "closed")

        applicant_role = get_role_by_name_or_id(interaction.guild, ROLE_APPLICANT)
        if applicant_role:
            try:
                member = interaction.guild.get_member(int(ticket['user_id']))
                if member:
                    await member.remove_roles(applicant_role)
            except Exception:
                pass

        await send_log(interaction.guild, interaction.user, "Заявка", f"Закрыта | ID: {self.ticket_id}", color=0x808080)

class VoiceCallView(View):
    def __init__(self, ticket_id: int, voice_channels: list):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.voice_channels = voice_channels
        self.add_voice_buttons()

    def add_voice_buttons(self):
        for vc in self.voice_channels:
            self.add_item(discord.ui.Button(
                label=f"🔊 {vc.name}",
                style=discord.ButtonStyle.primary,
                custom_id=f"voice_{vc.id}"
            ))
        self.add_item(discord.ui.Button(label="❌ Отмена", style=discord.ButtonStyle.secondary, custom_id="cancel_voice"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id") == "cancel_voice":
            await interaction.response.edit_message(content="❌ Обзвон отменен.", view=None)
            return False

        for vc in self.voice_channels:
            if interaction.data.get("custom_id") == f"voice_{vc.id}":
                ticket = tickets_db.get_ticket(self.ticket_id)
                if not ticket:
                    await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
                    return False
                
                user_id = int(ticket['user_id'])
                member = interaction.guild.get_member(user_id)
                
                if not member:
                    await interaction.response.send_message("❌ Пользователь не найден на сервере.", ephemeral=True)
                    return False
                
                if not member.voice or not member.voice.channel:
                    embed = discord.Embed(
                        title="🔊 Вас вызывают на обзвон!",
                        description=f"{member.mention}, рекрутер {interaction.user.mention} вызывает вас на обзвон!\n\n"
                                    f"**Пожалуйста, зайдите в любой голосовой канал,**\n"
                                    f"чтобы вас могли переместить в канал для обзвона.",
                        color=0x5865F2,
                        timestamp=datetime.now()
                    )
                    embed.add_field(
                        name="Заявка",
                        value=f"#{self.ticket_id}",
                        inline=True
                    )
                    embed.add_field(
                        name="Рекрутер",
                        value=interaction.user.mention,
                        inline=True
                    )
                    embed.add_field(
                        name="Канал для обзвона",
                        value=vc.mention,
                        inline=True
                    )
                    
                    channel = interaction.guild.get_channel(self.channel_id)
                    if channel:
                        await channel.send(content=f"{member.mention}", embed=embed)
                    
                    await interaction.response.send_message(
                        f"✅ {member.mention} был вызван на обзвон!\n"
                        f"Сообщение с приглашением отправлено в тикет.",
                        ephemeral=True
                    )
                    return False
                
                try:
                    await member.move_to(vc)
                    await interaction.response.send_message(
                        f"✅ {member.mention} вызван в {vc.mention}",
                        ephemeral=True
                    )
                    await send_log(interaction.guild, interaction.user, "Обзвон", f"Вызван {member.name} в {vc.name}")
                    
                    channel = interaction.guild.get_channel(self.channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="🔊 Обзвон",
                            description=f"{member.mention} вызван в {vc.mention} рекрутером {interaction.user.mention}",
                            color=0x00FF00,
                            timestamp=datetime.now()
                        )
                        await channel.send(embed=embed)
                        
                except Exception as e:
                    await interaction.response.send_message(
                        f"❌ Не удалось вызвать: {str(e)}",
                        ephemeral=True
                    )
                return False
        return True

@bot.command(name="stats")
@commands.has_permissions(administrator=True)
async def stats_command(ctx: commands.Context):
    stats = tickets_db.get_stats()
    if not stats:
        await ctx.send("📊 Нет данных по заявкам.")
        return

    embed = discord.Embed(title="📊 Статистика заявок", color=0x5865F2)
    for ticket_type, statuses in stats.items():
        desc = "\n".join([f"{status}: {count}" for status, count in statuses.items()])
        embed.add_field(name=ticket_type, value=desc or "Нет данных", inline=True)

    await ctx.send(embed=embed)

@bot.command(name="history")
@commands.has_permissions(administrator=True)
async def history_command(ctx: commands.Context, limit: int = 10):
    history = tickets_db.get_history(limit)
    if not history:
        await ctx.send("📭 Нет истории заявок.")
        return

    embed = discord.Embed(title=f"📜 История заявок (последние {len(history)})", color=0x5865F2)
    for row in history:
        status_emoji = {
            "pending": "📋",
            "review": "🟡",
            "accepted": "✅",
            "denied": "❌",
            "closed": "🔒"
        }.get(row[3], "📋")
        
        embed.add_field(
            name=f"#{row[0]} {status_emoji} - {row[2]}",
            value=f"Пользователь: <@{row[1]}>\nСтатус: {row[3]}\nДата: {row[4]}",
            inline=False
        )

    await ctx.send(embed=embed)

# ============================================================
# ===================== СИСТЕМА БАЛЛОВ ========================
# ============================================================

@tasks.loop(seconds=60)
async def check_voice_rewards():
    for guild in bot.guilds:
        for member in guild.members:
            if not member.voice or not member.voice.channel:
                continue
                
            if member.voice.channel.id == ROLE_AFK_ID:
                continue
                
            if member.voice.afk:
                continue
                
            if member.voice.self_deaf or member.voice.self_mute:
                continue
                
            channel_members = [m for m in member.voice.channel.members if not m.bot]
            if len(channel_members) < MIN_USERS_IN_VOICE:
                continue
                
            user_data = shop_db.get_user(member.id)
            last_reward = datetime.strptime(user_data[4], '%Y-%m-%d %H:%M:%S.%f') if user_data[4] else datetime.now()
            time_diff = (datetime.now() - last_reward).total_seconds()
            
            multiplier = 1
            if member.guild.get_role(ROLE_DONOR_ID) in member.roles:
                multiplier = 2
            elif member.guild.get_role(ROLE_BOOSTER_ID) in member.roles:
                multiplier = 1.5
                
            if time_diff >= INTERVAL_SECONDS:
                amount = AP_PER_INTERVAL * multiplier
                shop_db.update_points(member.id, amount)
                shop_db.add_voice_time(member.id, int(time_diff))
                
                streak = shop_db.update_streak(member.id)
                if streak >= 7:
                    shop_db.update_points(member.id, 5)
                    try:
                        await member.send(f"🎉 Ты получил 5 баллов за недельный стрик! (7 дней в войсе)")
                    except:
                        pass

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel is not None:
        shop_db.update_streak(member.id)
    
    elif before.channel is not None and after.channel is None:
        user_data = shop_db.get_user(member.id)
        last_reward = datetime.strptime(user_data[4], '%Y-%m-%d %H:%M:%S.%f') if user_data[4] else datetime.now()
        time_diff = (datetime.now() - last_reward).total_seconds()
        
        if time_diff > 60 and before.channel.id != ROLE_AFK_ID:
            multiplier = 1
            if member.guild.get_role(ROLE_DONOR_ID) in member.roles:
                multiplier = 2
            elif member.guild.get_role(ROLE_BOOSTER_ID) in member.roles:
                multiplier = 1.5
                
            amount = (time_diff / INTERVAL_SECONDS) * AP_PER_INTERVAL * multiplier
            if amount > 0:
                shop_db.update_points(member.id, amount)

# ============================================================
# ===================== НАГРАДЫ ЗА СОБЫТИЯ =====================
# ============================================================

async def reward_capt_participants(capt_view: CaptView, reward_amount: float = CAPT_REWARD):
    guild = capt_view.guild
    total_users = 0
    for category, user_ids in capt_view.users.items():
        for uid in user_ids:
            shop_db.update_points(uid, reward_amount)
            shop_db.log_reward(uid, 0, reward_amount, "CAPT", f"Участие в CAPT {capt_view.starts_at.strftime('%d.%m.%Y %H:%M')}")
            total_users += 1
    
    if total_users > 0 and capt_view.message:
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🎯 Награды за CAPT",
                description=f"**{total_users}** участников получили по **{reward_amount}** баллов",
                color=0x00FF00,
                timestamp=datetime.now()
            )
            await log_channel.send(embed=embed)

async def reward_mcl_participants(mcl_view: MclView, reward_amount: float = MCL_REWARD):
    guild = mcl_view.guild
    total_users = 0
    for category, user_ids in mcl_view.users.items():
        for uid in user_ids:
            shop_db.update_points(uid, reward_amount)
            shop_db.log_reward(uid, 0, reward_amount, "MCL", f"Участие в MCL {mcl_view.start_at.strftime('%d.%m.%Y %H:%M')}")
            total_users += 1
    
    if total_users > 0 and mcl_view.message:
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="🏆 Награды за MCL",
                description=f"**{total_users}** участников получили по **{reward_amount}** баллов",
                color=0x00FF00,
                timestamp=datetime.now()
            )
            await log_channel.send(embed=embed)

async def reward_zonewars_participants(mcl_view: MclView, reward_amount: float = ZONEWARS_REWARD):
    guild = mcl_view.guild
    total_users = 0
    for category, user_ids in mcl_view.users.items():
        for uid in user_ids:
            shop_db.update_points(uid, reward_amount)
            shop_db.log_reward(uid, 0, reward_amount, "ZONEWARS", f"Участие в ZoneWars {mcl_view.start_at.strftime('%d.%m.%Y %H:%M')}")
            total_users += 1
    
    if total_users > 0 and mcl_view.message:
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="⚔️ Награды за ZoneWars",
                description=f"**{total_users}** участников получили по **{reward_amount}** баллов",
                color=0x00FF00,
                timestamp=datetime.now()
            )
            await log_channel.send(embed=embed)

# ============================================================
# ===================== МАГАЗИН ================================
# ============================================================

class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_category_buttons()

    def add_category_buttons(self):
        for child in list(self.children):
            self.remove_item(child)
            
        categories = shop_db.get_categories()
        for cat in categories:
            cat_id, name, desc, emoji, pos = cat
            self.add_item(Button(
                label=f"{emoji} {name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"shop_cat_{cat_id}"
            ))
        
        self.add_item(Button(
            label="🏪 Главная",
            style=discord.ButtonStyle.primary,
            custom_id="shop_main"
        ))

class ShopItemView(discord.ui.View):
    def __init__(self, category_id: int):
        super().__init__(timeout=120)
        self.category_id = category_id
        self.items = shop_db.get_items_by_category(category_id)
        
        for item in self.items:
            item_id, cat_id, name, desc, price, stock, role_id = item
            stock_text = "∞" if stock == -1 else f"{stock} шт."
            self.add_item(Button(
                label=f"{name} — {price}💰 ({stock_text})",
                style=discord.ButtonStyle.primary,
                custom_id=f"shop_buy_{item_id}"
            ))
        
        self.add_item(Button(
            label="⚙️ Управление",
            style=discord.ButtonStyle.secondary,
            custom_id=f"shop_manage_items_{category_id}"
        ))
        self.add_item(Button(
            label="🔙 Назад",
            style=discord.ButtonStyle.secondary,
            custom_id="shop_back"
        ))

class ShopManageCategoriesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        categories = shop_db.get_categories()
        for cat in categories:
            cat_id, name, desc, emoji, pos = cat
            self.add_item(Button(
                label=f"✏️ {emoji} {name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"shop_edit_cat_{cat_id}"
            ))
            self.add_item(Button(
                label=f"🗑️ {emoji} {name}",
                style=discord.ButtonStyle.danger,
                custom_id=f"shop_delete_cat_{cat_id}"
            ))
        
        self.add_item(Button(
            label="➕ Новая категория",
            style=discord.ButtonStyle.success,
            custom_id="shop_new_category"
        ))
        self.add_item(Button(
            label="🔙 Назад",
            style=discord.ButtonStyle.secondary,
            custom_id="shop_back"
        ))

class ShopManageItemsView(discord.ui.View):
    def __init__(self, category_id: int):
        super().__init__(timeout=120)
        self.category_id = category_id
        items = shop_db.get_items_by_category(category_id)
        
        for item in items:
            item_id, cat_id, name, desc, price, stock, role_id = item
            self.add_item(Button(
                label=f"✏️ {name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"shop_edit_item_{item_id}"
            ))
            self.add_item(Button(
                label=f"🗑️ {name}",
                style=discord.ButtonStyle.danger,
                custom_id=f"shop_delete_item_{item_id}"
            ))
        
        self.add_item(Button(
            label="➕ Новый товар",
            style=discord.ButtonStyle.success,
            custom_id=f"shop_new_item_{category_id}"
        ))
        self.add_item(Button(
            label="🔙 Назад",
            style=discord.ButtonStyle.secondary,
            custom_id=f"shop_back_cat_{category_id}"
        ))

# ---- МОДАЛЬНЫЕ ОКНА ДЛЯ МАГАЗИНА ----
class NewCategoryModal(Modal, title="Создать категорию"):
    def __init__(self):
        super().__init__()
        self.name = TextInput(label="Название категории", placeholder="Например: Discord", required=True, max_length=50)
        self.add_item(self.name)
        self.description = TextInput(label="Описание", placeholder="Краткое описание категории", required=True, max_length=200)
        self.add_item(self.description)
        self.emoji = TextInput(label="Эмодзи", placeholder="Например: 💬", required=False, max_length=10)
        self.add_item(self.emoji)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip()
        description = self.description.value.strip()
        emoji = self.emoji.value.strip() or "📦"
        
        shop_db.add_category(name, description, emoji)
        await interaction.response.send_message(f"✅ Категория **{name}** создана!", ephemeral=True)
        await show_shop(interaction)

class EditCategoryModal(Modal, title="Редактировать категорию"):
    def __init__(self, cat_id: int, name: str, description: str, emoji: str):
        super().__init__()
        self.cat_id = cat_id
        self.name = TextInput(label="Название категории", default=name, required=True, max_length=50)
        self.add_item(self.name)
        self.description = TextInput(label="Описание", default=description, required=True, max_length=200)
        self.add_item(self.description)
        self.emoji = TextInput(label="Эмодзи", default=emoji, required=False, max_length=10)
        self.add_item(self.emoji)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name.value.strip()
        description = self.description.value.strip()
        emoji = self.emoji.value.strip() or "📦"
        
        shop_db.update_category(self.cat_id, name=name, description=description, emoji=emoji)
        await interaction.response.send_message(f"✅ Категория обновлена!", ephemeral=True)
        await show_shop(interaction)

class NewItemModal(Modal, title="Создать товар"):
    def __init__(self, category_id: int):
        super().__init__()
        self.category_id = category_id
        self.name = TextInput(label="Название товара", placeholder="Например: Роль Boost", required=True, max_length=50)
        self.add_item(self.name)
        self.description = TextInput(label="Описание", placeholder="Что даёт товар", required=True, max_length=200)
        self.add_item(self.description)
        self.price = TextInput(label="Цена", placeholder="0.5", required=True)
        self.add_item(self.price)
        self.stock = TextInput(label="Количество (-1 = ∞)", placeholder="-1", required=False)
        self.add_item(self.stock)
        self.role_id = TextInput(label="ID роли (0 = без роли)", placeholder="0", required=False)
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.strip())
            stock = int(self.stock.value.strip()) if self.stock.value.strip() else -1
            role_id = int(self.role_id.value.strip()) if self.role_id.value.strip() else 0
        except ValueError:
            await interaction.response.send_message("❌ Неверный формат цены или количества!", ephemeral=True)
            return
        
        shop_db.add_item(self.category_id, self.name.value.strip(), self.description.value.strip(), price, stock, role_id)
        await interaction.response.send_message(f"✅ Товар **{self.name.value}** создан!", ephemeral=True)
        await show_shop(interaction)

class EditItemModal(Modal, title="Редактировать товар"):
    def __init__(self, item_id: int, name: str, description: str, price: float, stock: int, role_id: int):
        super().__init__()
        self.item_id = item_id
        self.name = TextInput(label="Название товара", default=name, required=True, max_length=50)
        self.add_item(self.name)
        self.description = TextInput(label="Описание", default=description, required=True, max_length=200)
        self.add_item(self.description)
        self.price = TextInput(label="Цена", default=str(price), required=True)
        self.add_item(self.price)
        self.stock = TextInput(label="Количество", default=str(stock), required=False)
        self.add_item(self.stock)
        self.role_id = TextInput(label="ID роли", default=str(role_id), required=False)
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.strip())
            stock = int(self.stock.value.strip()) if self.stock.value.strip() else -1
            role_id = int(self.role_id.value.strip()) if self.role_id.value.strip() else 0
        except ValueError:
            await interaction.response.send_message("❌ Неверный формат цены или количества!", ephemeral=True)
            return
        
        shop_db.update_item(self.item_id, name=self.name.value.strip(), description=self.description.value.strip(), 
                           price=price, stock=stock, role_id=role_id)
        await interaction.response.send_message(f"✅ Товар **{self.name.value}** обновлен!", ephemeral=True)
        await show_shop(interaction)

async def show_shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 МАГАЗИН",
        description="**Приветствуем в [ZBS]**\n\n"
                    "Выберите интересующую вас категорию и воспользуйтесь **интерактивной кнопкой**, "
                    "чтобы ознакомиться с информацией.\n\n"
                    "Ниже вы можете ознакомиться с кратким описанием к каждой категории.",
        color=0x2B2D31
    )
    
    categories = shop_db.get_categories()
    for cat in categories:
        cat_id, name, desc, emoji, pos = cat
        embed.add_field(
            name=f"{emoji} **{name}**",
            value=f"📝 {desc}",
            inline=False
        )
    
    embed.set_footer(
        text=f"Баланс: {shop_db.get_user(interaction.user.id)[1]:.1f} баллов"
    )
    
    view = ShopView()
    await interaction.edit_original_response(embed=embed, view=view)

@bot.tree.command(name="shop", description="Открыть магазин")
async def shop_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 МАГАЗИН",
        description="**Приветствуем в [ZBS]**\n\n"
                    "Выберите интересующую вас категорию и воспользуйтесь **интерактивной кнопкой**, "
                    "чтобы ознакомиться с информацией.\n\n"
                    "Ниже вы можете ознакомиться с кратким описанием к каждой категории.",
        color=0x2B2D31
    )
    
    categories = shop_db.get_categories()
    for cat in categories:
        cat_id, name, desc, emoji, pos = cat
        embed.add_field(
            name=f"{emoji} **{name}**",
            value=f"📝 {desc}",
            inline=False
        )
    
    embed.set_footer(
        text=f"Баланс: {shop_db.get_user(interaction.user.id)[1]:.1f} баллов"
    )
    
    view = ShopView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="add_points", description="Выдать баллы пользователю (админ)")
@app_commands.describe(
    user="Пользователь",
    amount="Количество баллов",
    reason="Причина выдачи"
)
async def add_points(interaction: discord.Interaction, user: discord.Member, amount: float, reason: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ У вас нет прав администратора!", ephemeral=True)
        return
    
    shop_db.update_points(user.id, amount)
    shop_db.log_reward(user.id, interaction.user.id, amount, "ADMIN", reason)
    
    embed = discord.Embed(
        title="✅ Баллы выданы!",
        description=f"{user.mention} получил **{amount} баллов**",
        color=0x00ff00
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.add_field(name="Админ", value=interaction.user.mention)
    
    await interaction.response.send_message(embed=embed)
    
    try:
        await user.send(f"🎉 Вы получили **{amount} баллов** от {interaction.user.name}\nПричина: {reason}")
    except:
        pass

@bot.tree.command(name="reward_capt", description="Начислить баллы участникам CAPT (админ)")
@app_commands.describe(
    reward_amount="Количество баллов за участие"
)
async def reward_capt_command(interaction: discord.Interaction, reward_amount: float = CAPT_REWARD):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ У вас нет прав администратора!", ephemeral=True)
        return
    
    capt_key = (interaction.guild.id, interaction.channel.id)
    if capt_key not in ACTIVE_CAPTS or not ACTIVE_CAPTS[capt_key]:
        await interaction.response.send_message("❌ Нет активного CAPT в этом канале!", ephemeral=True)
        return
    
    capt_view = ACTIVE_CAPTS[capt_key][-1]
    await reward_capt_participants(capt_view, reward_amount)
    await interaction.response.send_message(f"✅ Начислено {reward_amount} баллов участникам CAPT!", ephemeral=True)

# ============================================================
# ===================== SLASH КОМАНДЫ ========================
# ============================================================

@bot.tree.command(name="create-mcl", description="Создать объявление MCL: описание, канал, старт, телепортация.")
@role_required_check()
@app_commands.describe(
    opis="Заголовок/название embed (например MCL).",
    voice="Голосовой канал для входа.",
    start_time="Время начала 24ч, например 19:00.",
    tp_time="Время телепортации 24ч, например 20:00."
)
async def create_mcl(interaction: discord.Interaction, opis: str, voice: discord.VoiceChannel, start_time: str, tp_time: str):
    def _p(hhmm: str) -> datetime:
        raw = hhmm.strip()
        parts = re.findall(r"\d+", raw)
        if len(parts) >= 2:
            hh, mm = int(parts[0]), int(parts[1])
        elif len(parts) == 1 and len(parts[0]) in (3, 4):
            hh = int(parts[0][:-2])
            mm = int(parts[0][-2:])
        else:
            raise ValueError("неверное время")
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("диапазон")
        try:
            now_pl = datetime.now(tz=WARSAW)
            t = datetime(now_pl.year, now_pl.month, now_pl.day, hh, mm, tzinfo=WARSAW)
            return t if t > now_pl else t + timedelta(days=1)
        except Exception:
            now_local = datetime.now()
            t = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
            return t if t > now_local else t + timedelta(days=1)

    try:
        start_at = _p(start_time)
        tp_at = _p(tp_time)
    except Exception:
        return await interaction.response.send_message("Укажите время в формате **ЧЧ:ММ** (например 19:00).", ephemeral=True)

    author = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
    view = MclView(opis, voice, start_at, tp_at, interaction.guild, author, event_name="MCL", max_pick=20)
    embed = view.make_embed()
    embed.set_footer(text=f"Создано {author.display_name}")
    allowed = discord.AllowedMentions(everyone=True)
    try:
        await interaction.response.send_message("✅ Объявление отправлено.", ephemeral=True)
    except Exception:
        pass
    msg = await interaction.channel.send(content="@everyone", embed=embed, view=view, allowed_mentions=allowed)
    view.message = msg

@bot.tree.command(name="create-zonewars", description="Создать объявление ZoneWars: описание, канал, старт, телепортация.")
@role_required_check()
@app_commands.describe(
    opis="Заголовок/название embed (например ZoneWars).",
    voice="Голосовой канал для входа.",
    start_time="Время начала 24ч, например 19:00.",
    tp_time="Время телепортации 24ч, например 20:00."
)
async def create_zonewars(interaction: discord.Interaction, opis: str, voice: discord.VoiceChannel, start_time: str, tp_time: str):
    def _p(hhmm: str) -> datetime:
        raw = hhmm.strip()
        parts = re.findall(r"\d+", raw)
        if len(parts) >= 2:
            hh, mm = int(parts[0]), int(parts[1])
        elif len(parts) == 1 and len(parts[0]) in (3, 4):
            hh = int(parts[0][:-2])
            mm = int(parts[0][-2:])
        else:
            raise ValueError("неверное время")
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("диапазон")
        try:
            now_pl = datetime.now(tz=WARSAW)
            t = datetime(now_pl.year, now_pl.month, now_pl.day, hh, mm, tzinfo=WARSAW)
            return t if t > now_pl else t + timedelta(days=1)
        except Exception:
            now_local = datetime.now()
            t = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
            return t if t > now_local else t + timedelta(days=1)

    try:
        start_at = _p(start_time)
        tp_at = _p(tp_time)
    except Exception:
        return await interaction.response.send_message("Укажите время в формате **ЧЧ:ММ** (например 19:00).", ephemeral=True)

    author = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
    view = MclView(opis, voice, start_at, tp_at, interaction.guild, author, event_name="ZoneWars", max_pick=25)
    embed = view.make_embed()
    embed.set_footer(text=f"Создано {author.display_name}")
    allowed = discord.AllowedMentions(everyone=True)
    try:
        await interaction.response.send_message("✅ Объявление отправлено.", ephemeral=True)
    except Exception:
        pass
    msg = await interaction.channel.send(content="@everyone", embed=embed, view=view, allowed_mentions=allowed)
    view.message = msg

@bot.tree.command(name="create-capt", description="Создать CAPT с таймером, картинкой и пингом @everyone.")
@role_required_check()
@app_commands.describe(start_time="Время начала 24ч, например 15:40 (польское время).",
                       image_url="Ссылка на большое изображение (покажется в embed).")
async def create_capt(interaction: discord.Interaction, start_time: str, image_url: str):
    try:
        hh, mm = (int(x) for x in start_time.strip().split(":"))
        assert 0 <= hh <= 23 and 0 <= mm <= 59
    except Exception:
        return await interaction.response.send_message("Укажите время **ЧЧ:ММ** (например 15:40).", ephemeral=True)
    try:
        now_pl = datetime.now(tz=WARSAW)
        today_start = datetime(now_pl.year, now_pl.month, now_pl.day, hh, mm, tzinfo=WARSAW)
        starts_at = today_start if today_start > now_pl else today_start + timedelta(days=1)
    except Exception:
        now_local = datetime.now()
        today_start = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
        starts_at = today_start if today_start > now_local else today_start + timedelta(days=1)
    author = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
    view = CaptView(starts_at, interaction.guild, author, image_url)
    embed = make_main_embed(starts_at, view.users, interaction.guild, author, image_url)
    allowed = discord.AllowedMentions(everyone=True)
    try:
        await interaction.response.send_message("✅ Объявление отправлено.", ephemeral=True)
    except Exception:
        pass
    msg = await interaction.channel.send(content="@everyone", embed=embed, view=view, allowed_mentions=allowed)
    view.message = msg
    ACTIVE_CAPTS.setdefault((interaction.guild.id, interaction.channel.id), []).append(view)

    async def ticker():
        try:
            while True:
                await asyncio.sleep(15)
                try:
                    if datetime.now(tz=WARSAW) >= starts_at:
                        final = make_main_embed(starts_at, view.users, interaction.guild, author, image_url)
                        final.description += "\n**CAPT начался.**"
                        await msg.edit(embed=final, view=view)
                        break
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
    interaction.client.loop.create_task(ticker())

@bot.tree.command(name="spect", description="Добавляет префикс !SPECT к вашему нику.")
async def spect(interaction: discord.Interaction):
    member = interaction.user
    old_nick = member.display_name or member.name

    if old_nick.startswith("!SPECT "):
        await interaction.response.send_message("У вас уже есть префикс !SPECT в нике.", ephemeral=True)
        return

    new_nick = f"!SPECT {old_nick}"

    if len(new_nick) > 32:
        await interaction.response.send_message("❌ Ваш ник слишком длинный, чтобы добавить префикс !SPECT.", ephemeral=True)
        return

    try:
        await member.edit(nick=new_nick, reason="Использовано /spect")
        await interaction.response.send_message(f"✅ Ваш ник изменен на **{new_nick}**.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ У бота нет прав на изменение вашего ника (требуется: Manage Nicknames).", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Произошла ошибка: {e}", ephemeral=True)

@bot.tree.command(name="unspect", description="Удаляет префикс !SPECT из вашего ника.")
async def unspect(interaction: discord.Interaction):
    member = interaction.user
    old_nick = member.display_name or member.name

    if not old_nick.startswith("!SPECT "):
        await interaction.response.send_message("У вас нет префикса !SPECT в нике.", ephemeral=True)
        return

    new_nick = re.sub(r"^!SPECT\s+", "", old_nick, count=1)

    try:
        await member.edit(nick=new_nick, reason="Использовано /unspect")
        await interaction.response.send_message(f"✅ Префикс !SPECT удален. Ваш ник теперь **{new_nick}**.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ У бота нет прав на изменение вашего ника (требуется: Manage Nicknames).", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Произошла ошибка: {e}", ephemeral=True)

@bot.tree.command(name="purge-commands", description="(АДМИН) Удалить глобальные команды бота и загрузить актуальные только на эту гильдию.")
@role_required_check()
async def purge_commands(interaction: discord.Interaction):
    try:
        guild = discord.Object(id=interaction.guild.id)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)

        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()

        await interaction.response.send_message("✅ Старые команды очищены и актуальные загружены на эту гильдию.", ephemeral=True)
    except Exception as e:
        try:
            await interaction.response.send_message(f"❌ Ошибка очистки: {e}", ephemeral=True)
        except Exception:
            pass

# ============================================================
# ===================== ОБРАБОТЧИКИ КНОПОК ===================
# ============================================================

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")

        if custom_id == "rp_ticket":
            await interaction.response.send_modal(RegentTicketModal("RP"))
            return
        elif custom_id == "capt_ticket":
            await interaction.response.send_modal(RegentTicketModal("CAPT"))
            return
        
        # === ОБРАБОТКА МАГАЗИНА ===
        if custom_id == "shop_main":
            await show_shop(interaction)
            return
        
        if custom_id == "shop_back":
            await show_shop(interaction)
            return
        
        if custom_id == "shop_manage_categories":
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут управлять категориями!", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="⚙️ Управление категориями",
                description="Выберите действие:",
                color=0x2B2D31
            )
            view = ShopManageCategoriesView()
            await interaction.response.edit_message(embed=embed, view=view)
            return
        
        if custom_id == "shop_new_category":
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут создавать категории!", ephemeral=True)
                return
            await interaction.response.send_modal(NewCategoryModal())
            return
        
        if custom_id.startswith("shop_edit_cat_"):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут редактировать категории!", ephemeral=True)
                return
            cat_id = int(custom_id.split("_")[-1])
            cat = None
            for c in shop_db.get_categories():
                if c[0] == cat_id:
                    cat = c
                    break
            if cat:
                cat_id, name, desc, emoji, pos = cat
                await interaction.response.send_modal(EditCategoryModal(cat_id, name, desc, emoji))
            return
        
        if custom_id.startswith("shop_delete_cat_"):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут удалять категории!", ephemeral=True)
                return
            cat_id = int(custom_id.split("_")[-1])
            shop_db.delete_category(cat_id)
            await interaction.response.send_message(f"✅ Категория удалена!", ephemeral=True)
            await show_shop(interaction)
            return
        
        if custom_id.startswith("shop_cat_"):
            cat_id = int(custom_id.split("_")[-1])
            cat = None
            for c in shop_db.get_categories():
                if c[0] == cat_id:
                    cat = c
                    break
            if cat:
                cat_id, name, desc, emoji, pos = cat
                items = shop_db.get_items_by_category(cat_id)
                
                embed = discord.Embed(
                    title=f"{emoji} {name}",
                    description=f"📝 {desc}\n\n**Товары в категории:**",
                    color=0x2B2D31
                )
                
                if items:
                    for item in items:
                        item_id, cat_id2, item_name, item_desc, price, stock, role_id = item
                        stock_text = "∞" if stock == -1 else f"{stock} шт."
                        embed.add_field(
                            name=f"**{item_name}**",
                            value=f"📝 {item_desc}\n💰 {price} баллов\n📦 В наличии: {stock_text}",
                            inline=False
                        )
                else:
                    embed.add_field(name="📭", value="В этой категории пока нет товаров", inline=False)
                
                embed.set_footer(
                    text=f"Баланс: {shop_db.get_user(interaction.user.id)[1]:.1f} баллов"
                )
                
                view = ShopItemView(cat_id)
                await interaction.response.edit_message(embed=embed, view=view)
            return
        
        if custom_id.startswith("shop_manage_items_"):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут управлять товарами!", ephemeral=True)
                return
            cat_id = int(custom_id.split("_")[-1])
            cat = None
            for c in shop_db.get_categories():
                if c[0] == cat_id:
                    cat = c
                    break
            if cat:
                cat_id, name, desc, emoji, pos = cat
                embed = discord.Embed(
                    title=f"⚙️ Управление товарами в {emoji} {name}",
                    description="Выберите действие:",
                    color=0x2B2D31
                )
                view = ShopManageItemsView(cat_id)
                await interaction.response.edit_message(embed=embed, view=view)
            return
        
        if custom_id.startswith("shop_new_item_"):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут создавать товары!", ephemeral=True)
                return
            cat_id = int(custom_id.split("_")[-1])
            await interaction.response.send_modal(NewItemModal(cat_id))
            return
        
        if custom_id.startswith("shop_edit_item_"):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут редактировать товары!", ephemeral=True)
                return
            item_id = int(custom_id.split("_")[-1])
            shop_db.cursor.execute('SELECT * FROM shop_items WHERE id = ?', (item_id,))
            item = shop_db.cursor.fetchone()
            if item:
                item_id, cat_id, name, desc, price, stock, role_id = item
                await interaction.response.send_modal(EditItemModal(item_id, name, desc, price, stock, role_id))
            return
        
        if custom_id.startswith("shop_delete_item_"):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Только администраторы могут удалять товары!", ephemeral=True)
                return
            item_id = int(custom_id.split("_")[-1])
            shop_db.remove_item(item_id)
            await interaction.response.send_message(f"✅ Товар удален!", ephemeral=True)
            shop_db.cursor.execute('SELECT category_id FROM shop_items WHERE id = ?', (item_id,))
            result = shop_db.cursor.fetchone()
            if result:
                cat_id = result[0]
                cat = None
                for c in shop_db.get_categories():
                    if c[0] == cat_id:
                        cat = c
                        break
                if cat:
                    cat_id, name, desc, emoji, pos = cat
                    items = shop_db.get_items_by_category(cat_id)
                    embed = discord.Embed(
                        title=f"{emoji} {name}",
                        description=f"📝 {desc}\n\n**Товары в категории:**",
                        color=0x2B2D31
                    )
                    if items:
                        for item in items:
                            item_id2, cat_id2, item_name, item_desc, price, stock, role_id = item
                            stock_text = "∞" if stock == -1 else f"{stock} шт."
                            embed.add_field(
                                name=f"**{item_name}**",
                                value=f"📝 {item_desc}\n💰 {price} баллов\n📦 В наличии: {stock_text}",
                                inline=False
                            )
                    else:
                        embed.add_field(name="📭", value="В этой категории пока нет товаров", inline=False)
                    embed.set_footer(
                        text=f"Баланс: {shop_db.get_user(interaction.user.id)[1]:.1f} баллов"
                    )
                    view = ShopItemView(cat_id)
                    await interaction.response.edit_message(embed=embed, view=view)
            return
        
        if custom_id.startswith("shop_back_cat_"):
            cat_id = int(custom_id.split("_")[-1])
            cat = None
            for c in shop_db.get_categories():
                if c[0] == cat_id:
                    cat = c
                    break
            if cat:
                cat_id, name, desc, emoji, pos = cat
                items = shop_db.get_items_by_category(cat_id)
                embed = discord.Embed(
                    title=f"{emoji} {name}",
                    description=f"📝 {desc}\n\n**Товары в категории:**",
                    color=0x2B2D31
                )
                if items:
                    for item in items:
                        item_id, cat_id2, item_name, item_desc, price, stock, role_id = item
                        stock_text = "∞" if stock == -1 else f"{stock} шт."
                        embed.add_field(
                            name=f"**{item_name}**",
                            value=f"📝 {item_desc}\n💰 {price} баллов\n📦 В наличии: {stock_text}",
                            inline=False
                        )
                else:
                    embed.add_field(name="📭", value="В этой категории пока нет товаров", inline=False)
                embed.set_footer(
                    text=f"Баланс: {shop_db.get_user(interaction.user.id)[1]:.1f} баллов"
                )
                view = ShopItemView(cat_id)
                await interaction.response.edit_message(embed=embed, view=view)
            return
        
        if custom_id.startswith("shop_buy_"):
            item_id = int(custom_id.split("_")[-1])
            
            shop_db.cursor.execute('SELECT * FROM shop_items WHERE id = ?', (item_id,))
            item = shop_db.cursor.fetchone()
            
            if not item:
                await interaction.response.send_message("❌ Товар не найден!", ephemeral=True)
                return
            
            item_id, cat_id, name, desc, price, stock, role_id = item
            
            if stock == 0:
                await interaction.response.send_message("❌ Товар закончился!", ephemeral=True)
                return
            
            user_data = shop_db.get_user(interaction.user.id)
            
            if user_data[1] < price:
                await interaction.response.send_message(f"❌ Не хватает баллов! Нужно: {price}, у тебя: {user_data[1]:.1f}", ephemeral=True)
                return
            
            shop_db.update_points(interaction.user.id, -price)
            shop_db.purchase_item(interaction.user.id, item_id)
            
            if stock > 0:
                shop_db.cursor.execute('UPDATE shop_items SET stock = stock - 1 WHERE id = ?', (item_id,))
                shop_db.conn.commit()
            
            if role_id:
                role = interaction.guild.get_role(role_id)
                if role:
                    await interaction.user.add_roles(role)
                    role_text = f" и выдана роль {role.mention}"
                else:
                    role_text = ""
            
            embed = discord.Embed(
                title="✅ Покупка успешна!",
                description=f"Ты купил **{name}**{role_text}",
                color=0x00ff00
            )
            embed.add_field(name="💰 Потрачено", value=f"-{price} баллов", inline=True)
            embed.add_field(name="Остаток", value=f"{user_data[1] - price:.1f} баллов", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

# ============================================================
# ===================== ЗАПУСК ================================
# ============================================================

@bot.event
async def on_ready():
    log.info(f"Вошли как {bot.user} (id={bot.user.id})")
    try:
        asyncio.create_task(_setup_http())
    except Exception:
        pass

    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            log.info(f"/ Синхронизировано {len(synced)} команд с гильдией {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            log.info(f"/ Синхронизировано {len(synced)} команд глобально")
    except Exception as e:
        log.exception(f"Синхронизация команд не удалась: {e}")

    check_voice_rewards.start()

def _check_env():
    if not TOKEN:
        raise RuntimeError("Отсутствует DISCORD_TOKEN в .env")

def _create_web_app():
    app = web.Application()
    async def root(_):
        return web.Response(text="OK", content_type="text/plain")
    async def health(_):
        return web.Response(text="HEALTHY", content_type="text/plain")
    app.router.add_get("/", root)
    app.router.add_get("/health", health)
    return app

if __name__ == "__main__":
    import os, asyncio, signal

    def _check_env():
        token = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
        if not token:
            raise RuntimeError("Отсутствует DISCORD_TOKEN в .env")
        return token

    async def _main():
        token = _check_env()
        app = _create_web_app()
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", "8080"))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        bot_task = asyncio.create_task(bot.start(token))

        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass

        await stop.wait()
        await bot.close()
        await runner.cleanup()

    asyncio.run(_main())
