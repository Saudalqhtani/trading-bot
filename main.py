"""
Gold Scalp AI Monitor v7.0 - Railway Edition (Production Ready)
========================================================================
- إصلاحات الإصدار 7.0:
  ✅ SQLite Persistence - حفظ البيانات حتى بعد إعادة التشغيل
  ✅ JSON Structured Output - Parsing موثوق 100%
  ✅ نظام تأكيد يدوي للصفقات - أزرار تفاعلية
  ✅ حساب PnL صحيح للذهب ($1 = 100 pip)
  ✅ توقيت عطلة نهاية الأسبوع قابل للتعديل
"""

import os
import json
import asyncio
from collections import deque
import aiohttp
import time
import math
import re
import sqlite3
import xml.etree.ElementTree as ET
import traceback
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# ============ نظام الأمان ============
import sqlite3
import time as _time_sec
from functools import wraps
from datetime import datetime as _dt_sec, timezone as _tz_sec

SECURITY_DB_PATH = os.environ.get("DB_PATH", "/app/data/gold_bot.db")
# يدعم عدة مشرفين: ADMIN_USER_IDS="111,222,333" (أو ADMIN_USER_ID القديم لمشرف واحد)
_admin_raw_sec = os.environ.get("ADMIN_USER_IDS", "") or os.environ.get("ADMIN_USER_ID", "")
ADMIN_USER_IDS = set(x.strip() for x in _admin_raw_sec.split(",") if x.strip())
# يظهر للمستخدم غير المصرح كطريقة تواصل مع المشرف، مثلا: @my_username
ADMIN_CONTACT = os.environ.get("ADMIN_CONTACT", "")

def contact_admin_text() -> str:
    if ADMIN_CONTACT:
        return f"📩 تواصل مع المشرف: {ADMIN_CONTACT}"
    return "📩 تواصل مع المشرف."

_unauth_alert_cooldown = {}  # user_id -> آخر وقت تم تنبيه المشرف فيه، لمنع الإزعاج المتكرر


def init_security_db():
    os.makedirs(os.path.dirname(SECURITY_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            added_by TEXT,
            expires_at TIMESTAMP
        )
    """)
    cursor.execute("PRAGMA table_info(authorized_users)")
    cols = [row[1] for row in cursor.fetchall()]
    if "expires_at" not in cols:
        cursor.execute("ALTER TABLE authorized_users ADD COLUMN expires_at TIMESTAMP")
    if "first_name" not in cols:
        cursor.execute("ALTER TABLE authorized_users ADD COLUMN first_name TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            user_id TEXT,
            actor_id TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_accounts (
            user_id TEXT PRIMARY KEY,
            balance REAL DEFAULT 10000,
            initial_balance REAL DEFAULT 10000,
            risk_percent REAL DEFAULT 1.0,
            active_trade TEXT,
            stats TEXT,
            equity_history TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            direction TEXT, entry_price REAL, exit_price REAL,
            pnl_pips REAL, pnl_usd REAL, result TEXT, confidence REAL,
            open_time REAL, close_time TEXT,
            sl_pips REAL, tp1_pips REAL, tp2_pips REAL, rr TEXT, duration TEXT, lot_size REAL
        )
    """)
    conn.commit()
    conn.close()
    print("Security DB ready")


# ============ حسابات المستخدمين (كل مستخدم رصيد ومخاطرة وصفقات خاصة فيه) ============
DEFAULT_STATS = {"wins": 0, "losses": 0, "total_pips": 0, "daily_pips": {}, "weekly_pips": {}, "monthly_pips": {}}

def _default_user_account() -> dict:
    return {
        "balance": 10000.0, "initial_balance": 10000.0, "risk_percent": 1.0,
        "active_trade": None, "stats": dict(DEFAULT_STATS), "equity_history": [],
    }

user_cache = {}
user_cache_lock = asyncio.Lock()

def _row_to_account(row) -> dict:
    balance, initial_balance, risk_percent, active_trade_raw, stats_raw, equity_raw = row
    active_trade = json.loads(active_trade_raw) if active_trade_raw else None
    stats = json.loads(stats_raw) if stats_raw else dict(DEFAULT_STATS)
    equity_history = json.loads(equity_raw) if equity_raw else []
    return {
        "balance": balance, "initial_balance": initial_balance, "risk_percent": risk_percent,
        "active_trade": active_trade, "stats": stats, "equity_history": equity_history,
    }

def _load_user_account_sync(user_id: str):
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT balance, initial_balance, risk_percent, active_trade, stats, equity_history FROM user_accounts WHERE user_id = ?",
        (str(user_id),)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def _save_user_account_sync(user_id: str, account: dict):
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_accounts (user_id, balance, initial_balance, risk_percent, active_trade, stats, equity_history, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            balance=excluded.balance, initial_balance=excluded.initial_balance,
            risk_percent=excluded.risk_percent, active_trade=excluded.active_trade,
            stats=excluded.stats, equity_history=excluded.equity_history, updated_at=CURRENT_TIMESTAMP
    """, (
        str(user_id), account["balance"], account["initial_balance"], account["risk_percent"],
        json.dumps(account["active_trade"]) if account["active_trade"] else None,
        json.dumps(account["stats"]),
        json.dumps(account["equity_history"][-200:]),  # حد أقصى للسجل المحفوظ
    ))
    conn.commit()
    conn.close()

async def get_user_account(user_id: str) -> dict:
    user_id = str(user_id)
    async with user_cache_lock:
        if user_id in user_cache:
            return user_cache[user_id]
        row = _load_user_account_sync(user_id)
        account = _row_to_account(row) if row else _default_user_account()
        user_cache[user_id] = account
        if not row:
            _save_user_account_sync(user_id, account)
        return account

async def save_user_account(user_id: str, account: dict):
    user_id = str(user_id)
    async with user_cache_lock:
        user_cache[user_id] = account
        _save_user_account_sync(user_id, account)

async def add_user_trade_record(user_id: str, trade: dict):
    def _insert():
        conn = sqlite3.connect(SECURITY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_trades (user_id, direction, entry_price, exit_price, pnl_pips, pnl_usd,
                result, confidence, open_time, close_time, sl_pips, tp1_pips, tp2_pips, rr, duration, lot_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(user_id), trade["direction"], trade["entry_price"], trade["exit_price"],
            trade["pnl_pips"], trade["pnl_usd"], trade["result"], trade.get("confidence", 0),
            trade.get("open_time", time.time()), trade.get("close_time", now_str()),
            trade.get("sl_pips", 0), trade.get("tp1_pips", 0), trade.get("tp2_pips", 0),
            trade.get("rr", ""), trade.get("duration", ""), trade.get("lot_size", 0.01),
        ))
        conn.commit()
        conn.close()
    _insert()

async def get_user_trades(user_id: str, limit: int = 5) -> list:
    def _query():
        conn = sqlite3.connect(SECURITY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT direction, entry_price, exit_price, pnl_pips, pnl_usd, result, close_time, confidence
            FROM user_trades WHERE user_id = ? ORDER BY id DESC LIMIT ?
        """, (str(user_id), limit))
        rows = cursor.fetchall()
        conn.close()
        cols = ["direction", "entry_price", "exit_price", "pnl_pips", "pnl_usd", "result", "close_time", "confidence"]
        return [dict(zip(cols, row)) for row in rows]
    return _query()

async def get_all_authorized_user_ids() -> list:
    """كل معرفات المستخدمين المصرح لهم حاليا (بدون منتهي الصلاحية) + المشرفين"""
    def _query():
        conn = sqlite3.connect(SECURITY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, expires_at FROM authorized_users")
        rows = cursor.fetchall()
        conn.close()
        return rows
    try:
        rows = _query()
    except Exception as e:
        print(f"❌ خطأ قراءة authorized_users (سيتم استخدام المشرفين فقط): {e}")
        rows = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ids = set(ADMIN_USER_IDS)
    for uid, expires_at in rows:
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) <= now:
                    continue
            except ValueError:
                pass
        ids.add(str(uid))
    return list(ids)


def is_admin(user_id: str) -> bool:
    return str(user_id) in ADMIN_USER_IDS


def is_authorized(user_id: str) -> bool:
    if is_admin(user_id):
        return True
    try:
        conn = sqlite3.connect(SECURITY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT expires_at FROM authorized_users WHERE user_id = ?", (str(user_id),))
        result = cursor.fetchone()
        conn.close()
        if result is None:
            return False
        expires_at = result[0]
        if expires_at:
            try:
                if _dt_sec.fromisoformat(expires_at) <= _dt_sec.now(_tz_sec.utc).replace(tzinfo=None):
                    return False
            except ValueError:
                pass
        return True
    except Exception as e:
        print(f"Auth check error: {e}")
        return True


SECURITY_BOT_TOKEN = os.environ.get("SECURITY_BOT_TOKEN")  # لإرسال تنبيهات الدخول غير المصرح عبر بوت الأمان


async def _alert_admins_unauthorized(user_id: str, username: str, first_name: str):
    """ينبّه كل المشرفين عبر بوت الأمان بمحاولة دخول غير مصرح، مع زر اضافة سريع (بحد أقصى تنبيه كل 10 دقائق لنفس المستخدم)"""
    if not ADMIN_USER_IDS:
        return
    if not SECURITY_BOT_TOKEN:
        print("⚠️ SECURITY_BOT_TOKEN غير مضبوط - لا يمكن ارسال تنبيه الدخول غير المصرح عبر بوت الأمان")
        return
    now = _time_sec.time()
    last = _unauth_alert_cooldown.get(user_id, 0)
    if now - last < 600:
        return
    _unauth_alert_cooldown[user_id] = now

    display_name = first_name or (f"@{username}" if username else f"مستخدم {user_id}")
    text = f"🚨 محاولة دخول غير مصرحة (بوت التداول)\n\nالاسم: {display_name}\nالمعرف: {user_id}"
    if username:
        text += f"\nاليوزر: @{username}"
    keyboard = [[{"text": "✅ اضافة فورية", "callback_data": f"quickadd_{user_id}"}]]
    for admin_id in ADMIN_USER_IDS:
        try:
            url = f"https://api.telegram.org/bot{SECURITY_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": admin_id, "text": text, "reply_markup": {"inline_keyboard": keyboard}}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    await resp.json()
        except Exception as e:
            print(f"❌ فشل تنبيه المشرف {admin_id}: {e}")


def require_auth(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Handle both direct messages and callback queries
        if update.callback_query:
            tg_user = update.callback_query.from_user
        else:
            tg_user = update.effective_user
        user_id = str(tg_user.id)

        if not is_authorized(user_id):
            msg = (
                "⛔ غير مصرح لك!\n\n"
                "🔒 ليس لديك صلاحية.\n"
                f"{contact_admin_text()}\n\n"
                "🆔 معرفك: " + user_id
            )
            if update.effective_message:
                await update.effective_message.reply_text(msg)
            await _alert_admins_unauthorized(user_id, tg_user.username, tg_user.first_name)
            return
        return await func(update, context)
    return wrapper

# ============ نهاية نظام الأمان ============


# ============ الاعدادات ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

DB_PATH = os.environ.get("DB_PATH", "/app/data/gold_bot.db")
WEEKEND_CLOSE_HOUR = int(os.environ.get("WEEKEND_CLOSE_HOUR", 21))
WEEKEND_OPEN_HOUR = int(os.environ.get("WEEKEND_OPEN_HOUR", 22))

SYMBOL = "XAU/USD"
DXY_SYMBOL = "DXY"
MONITOR_INTERVAL = 15
ANALYSIS_INTERVAL = 180
MIN_CONFIDENCE = 75
GEMINI_MODEL = "gemini-3.5-flash"
GROQ_MODEL = "openai/gpt-oss-120b"  # llama-3.3-70b-versatile deprecated by Groq, shuts down 2026-08-16

# إعدادات الذهب: $1.00 = 100 pip
GOLD_PIP_VALUE = 0.01
GOLD_PIP_USD_PER_LOT = 1.0

TRADE_MONITOR_INTERVAL = 180
PRICE_POLL_INTERVAL = 180
NEWS_CHECK_INTERVAL = 300
SIGNIFICANT_MOVE_PIPS = 5

TIMEFRAMES = {
    "M30": "30min",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}

LONDON_SESSION = (7, 16)
NEW_YORK_SESSION = (12, 21)
TOKYO_SESSION = (0, 9)
SYDNEY_SESSION = (22, 7)

SESSIONS_CONFIG = {
    "لندن 🇬🇧": {"start": 7, "end": 16},
    "نيويورك 🇺🇸": {"start": 12, "end": 21},
    "طوكيو 🇯🇵": {"start": 0, "end": 9},
    "سيدني 🇦🇺": {"start": 22, "end": 7},
}



# ============ قاعدة البيانات ============

def init_db():
    """تهيئة قاعدة بيانات SQLite"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            sl_pips REAL,
            tp1_pips REAL,
            tp2_pips REAL,
            pnl_pips REAL,
            pnl_usd REAL,
            result TEXT,
            confidence INTEGER,
            open_time TEXT,
            close_time TEXT,
            rr TEXT,
            duration TEXT,
            lot_size REAL DEFAULT 0.01,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE,
            decision TEXT,
            confidence INTEGER,
            entry_price REAL,
            sl_pips REAL,
            tp1_pips REAL,
            tp2_pips REAL,
            rr TEXT,
            status TEXT DEFAULT 'pending',
            analysis_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ قاعدة البيانات جاهزة")

async def save_state():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        state_data = {
            "stats": json.dumps(db["stats"]),
            "current_balance": str(db["current_balance"]),
            "initial_balance": str(db["initial_balance"]),
            "risk_percent": str(db["risk_percent"]),
            "equity_history": json.dumps([{"date": h["date"].isoformat(), "balance": h["balance"]} for h in db["equity_history"]]),
            "gemini_calls_today": str(db["gemini_calls_today"]),
            "last_analysis_ts": str(db["last_analysis_ts"]),
            "last_session_analysis": db["last_session_analysis"],
            "twelvedata_paused_until": str(db["twelvedata_paused_until"]),
            "twelvedata_pause_notified": str(int(db["twelvedata_pause_notified"])),
            "gemini_paused_until": str(db["gemini_paused_until"]),
            "gemini_pause_notified": str(int(db["gemini_pause_notified"])),
        }
        for key, value in state_data.items():
            cursor.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ خطأ حفظ الحالة: {e}")

async def load_state():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM state")
        rows = cursor.fetchall()
        for key, value in rows:
            if key == "stats": db["stats"] = json.loads(value)
            elif key == "current_balance": db["current_balance"] = float(value)
            elif key == "initial_balance": db["initial_balance"] = float(value)
            elif key == "risk_percent": db["risk_percent"] = float(value)
            elif key == "equity_history":
                history = json.loads(value)
                db["equity_history"] = [{"date": datetime.fromisoformat(h["date"]), "balance": h["balance"]} for h in history]
            elif key == "gemini_calls_today": db["gemini_calls_today"] = int(value)
            elif key == "last_analysis_ts": db["last_analysis_ts"] = float(value)
            elif key == "last_session_analysis": db["last_session_analysis"] = value
            elif key == "twelvedata_paused_until": db["twelvedata_paused_until"] = float(value)
            elif key == "twelvedata_pause_notified": db["twelvedata_pause_notified"] = bool(int(value))
            elif key == "gemini_paused_until": db["gemini_paused_until"] = float(value)
            elif key == "gemini_pause_notified": db["gemini_pause_notified"] = bool(int(value))
        cursor.execute("SELECT * FROM trades ORDER BY created_at DESC")
        trades = cursor.fetchall()
        columns = [c[0] for c in cursor.description]
        db["trades"] = [dict(zip(columns, t)) for t in trades]
        conn.close()
        print("✅ تم استعادة الحالة من قاعدة البيانات")
    except Exception as e:
        print(f"⚠️ خطأ استعادة الحالة: {e}")

async def save_trade(trade_data: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trades (direction, entry_price, exit_price, sl_pips, tp1_pips, tp2_pips, 
             pnl_pips, pnl_usd, result, confidence, open_time, close_time, rr, duration, lot_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade_data["direction"], trade_data["entry_price"], trade_data.get("exit_price", 0),
            trade_data.get("sl_pips", 0), trade_data.get("tp1_pips", 0), trade_data.get("tp2_pips", 0),
            trade_data.get("pnl_pips", 0), trade_data.get("pnl_usd", 0), trade_data.get("result", ""),
            trade_data.get("confidence", 0), trade_data.get("open_time", ""), trade_data.get("close_time", ""),
            trade_data.get("rr", ""), trade_data.get("duration", ""), trade_data.get("lot_size", 0.01)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ خطأ حفظ الصفقة: {e}")

async def save_signal(signal_id: str, signal_data: dict, analysis_text: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO signals_history 
            (signal_id, decision, confidence, entry_price, sl_pips, tp1_pips, tp2_pips, rr, status, analysis_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_id, signal_data.get("decision", "HOLD"), signal_data.get("confidence", 0),
            signal_data.get("entry_price", 0), signal_data.get("sl_pips", 0),
            signal_data.get("tp1_pips", 0), signal_data.get("tp2_pips", 0),
            signal_data.get("rr", ""), "pending", analysis_text
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ خطأ حفظ الإشارة: {e}")

async def update_signal_status(signal_id: str, status: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE signals_history SET status = ? WHERE signal_id = ?", (status, signal_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ خطأ تحديث حالة الإشارة: {e}")



# ============ الهيكل البيانات ============

@dataclass
class TradeSignal:
    decision: str
    confidence: int
    entry_price: float
    sl_pips: float
    tp1_pips: float
    tp2_pips: float
    rr: str
    risk_percent: float
    duration: str
    session: str
    agent_details: str
    summary: str

    def is_valid(self) -> bool:
        if self.decision not in ["BUY", "SELL"]:
            return True
        if self.entry_price <= 0:
            return False
        if self.sl_pips <= 0:
            return False
        # ملاحظة: لا نرفض هنا بسبب انخفاض الثقة الفردية - رأي نموذج واحد بثقة أقل من الحد
        # قد يتفق مع النموذج الثاني ويرتفع بعد الإجماع فوق الحد. الفحص النهائي يصير
        # على الثقة بعد الإجماع في opportunity_analyzer_coro.
        return True

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "sl_pips": self.sl_pips,
            "tp1_pips": self.tp1_pips,
            "tp2_pips": self.tp2_pips,
            "rr": self.rr,
            "risk_percent": self.risk_percent,
            "duration": self.duration,
            "session": self.session,
            "agent_details": self.agent_details,
            "summary": self.summary,
        }

db = {
    "trades": [],
    "signals": [],
    "stats": {"wins": 0, "losses": 0, "total_pips": 0, "daily_pips": {}, "weekly_pips": {}, "monthly_pips": {}},
    "paused": False,
    "active_trade": None,
    "pending_signals": {},
    "last_analysis_ts": 0,
    "twelvedata_paused_until": 0,
    "twelvedata_pause_notified": False,
    "gemini_paused_until": 0,
    "gemini_pause_notified": False,
    "risk_percent": 1.0,
    "news_blocked_until": 0,
    "last_price": 2650.0,
    "dxy_price": 103.0,
    "dxy_price_last_fetch": 0,
    "session_notified": {},
    "atr_data": {"current": 0, "threshold": 15.0, "last_alert": 0},
    "equity_history": [],
    "initial_balance": 10000.0,
    "current_balance": 10000.0,
    "analysis_count": 0,
    "last_hold_reason": "",
    "api_errors": [],
    "bot_start_time": time.time(),
    "news_notified": {},
    "upcoming_news": [],
    "trade_last_update": 0,
    "trade_entry_price": 0,
    "trade_last_pnl": 0,
    "trade_high_pnl": 0,
    "trade_low_pnl": 0,
    "last_sent_price": 0,
    "price_change_buffer": [],
    "last_gemini_call": 0,
    "gemini_calls_today": 0,
    "last_session_analysis": "",
    "last_button_press": 0,
}
db_lock = asyncio.Lock()

# ============ الـ Prompts ============

GOLD_SCALP_PROMPT_JSON = """
أنت Elite Gold Momentum Decision Engine، رئيس شبكة تحليل مكونة من 12 وكيلاً متخصصاً في تداول الذهب XAU/USD، ومدير مخاطر صارم.

مهمتك هي تحليل بيانات السوق الفعلية المرفقة على الفريمات M30 وM15 وM5 وM1، ثم إصدار قرار تداول واحد فقط:

BUY
SELL
HOLD

ممنوع التخمين، ممنوع اختلاق بيانات غير موجودة، وممنوع إصدار BUY أو SELL اعتماداً على عامل واحد فقط.

مهم جداً: مهمتك تنتهي عند تحديد الأسعار فقط (entry / stop loss / take profit 1 / take profit 2).
حساب النقاط (points) ونسبة المخاطرة إلى العائد (R:R) تتم برمجياً خارج هذا البرومت،
لذلك يُمنع عليك إخراج أي حقل points أو rr — أخرج الأسعار فقط وسيتم حساب الباقي آلياً.

==================================================
[1] OBJECTIVE

نمط التداول:
MEDIUM-TERM MOMENTUM SCALP

الهدف:
اقتناص حركة زخم حقيقية في الذهب تستمر غالباً 20-30 دقيقة.

الأولوية:

1. الاتجاه والهيكل.
2. السيولة.
3. Order Block.
4. FVG.
5. تأكيد M5.
6. Trigger على M1.
7. Volume & Momentum.
8. DXY.
9. الأخبار.
10. R:R (يُحسب برمجياً من الأسعار التي تحددها).
11. عدم مطاردة السعر.

QUALITY > FREQUENCY

إذا لم تكن الصفقة عالية الجودة:
HOLD.

==================================================
[2] MARKET DATA

البيانات مرتبة:
الأحدث أولاً.

== M30 ==
{data_m30}

== M15 ==
{data_m15}

== M5 ==
{data_m5}

== M1 ==
{data_m1}

== DXY ==
{data_dxy}

سعر DXY الحالي:
{dxy_price}

== MARKET CONTEXT ==
وقت السوق الحالي:
{current_time}

الجلسة الحالية:
{current_session}

== NEWS ==
{news_data}

== ACCOUNT ==
رصيد الحساب:
{account_balance}

المخاطرة القصوى المسموحة:
{max_risk_percent}

==================================================
[3] DATA INTEGRITY GATE

قبل أي تحليل، تحقق من:

- وجود بيانات M30.
- وجود بيانات M15.
- وجود بيانات M5.
- وجود بيانات M1.
- صحة ترتيب البيانات زمنياً.
- كفاية عدد الشموع.
- صحة OHLC.
- عدم وجود بيانات تالفة.
- وضوح السعر الحالي للذهب.
- توفر بيانات DXY.
- توفر بيانات الأخبار.

إذا كانت البيانات الأساسية غير كافية للتحليل:
decision = HOLD

ممنوع تعويض البيانات الناقصة بالتخمين.

==================================================
[4] GOLD POINT CALCULATION — معلومة مرجعية فقط (الحساب الفعلي يتم بالكود)

قاعدة حساب النقاط للذهب XAU/USD:
1 نقطة = 0.10 دولار.
1 دولار = 10 نقاط.

هذه القاعدة موجودة هنا لفهم السياق فقط عند تسمية المستويات (مثلاً "SL خلف مستوى يبعد ~5 نقاط").
أنت لا تحسب points بنفسك ولا تُخرجها — فقط حدد الأسعار (entry/sl/tp1/tp2)
وسيقوم الكود بحساب النقاط وR:R بدقة مطلقة.

==================================================
[5] 12 ANALYSIS AGENTS

كل وكيل يحلل بشكل مستقل أولاً.

كل وكيل يجب أن ينتج داخلياً:

vote:
BUY / SELL / NEUTRAL

score:
من -100 إلى +100

confidence:
من 0 إلى 100

reason:
سبب مبني فقط على البيانات (جملة واحدة مختصرة).

==================================================
AGENT 1 — TREND & MARKET STRUCTURE

حلل M30 وM15.

حدد:
- HH / HL / LH / LL
- BOS
- CHoCH
- EMA 200
- الاتجاه العام.

BUY أقوى عندما: M30 صاعد + M15 صاعد.
SELL أقوى عندما: M30 هابط + M15 هابط.
إذا كان M30 وM15 متعارضين: خفض الثقة.
لا تعتبر مجرد ملامسة EMA200 تغييراً للاتجاه.

==================================================
AGENT 2 — SESSION & TIME LIQUIDITY

حدد: London / New York / Kill Zone / Asian High / Asian Low /
Previous Session High / Previous Session Low.

ابحث عن Liquidity Sweep قبل الحركة.
لا تفترض وجود Kill Zone إذا لم تتوفر بيانات الوقت.

==================================================
AGENT 3 — SMC LIQUIDITY

حدد: Equal Highs / Equal Lows / Previous High / Previous Low /
Session High / Session Low / Buy-side liquidity / Sell-side liquidity.

ابحث عن التسلسل: Liquidity Sweep → Rejection → Structure Shift.
Sweep بدون Confirmation لا يعتبر Entry Signal.

==================================================
AGENT 4 — ORDER BLOCK

حدد Order Blocks الواضحة فقط.

BUY Order Block: آخر منطقة بيع قبل Displacement صاعد واضح.
SELL Order Block: آخر منطقة شراء قبل Displacement هابط واضح.

قيّم: Freshness / Strength / Displacement / Mitigation / Proximity.
لا تعتبر كل شمعة Order Block.

==================================================
AGENT 5 — FVG / IMBALANCE

حلل FVG على M15 وM5.

لكل FVG: الاتجاه / الحجم / هل تم ملؤه؟ / هل تم اختباره؟ / هل ما زال صالحاً؟ /
هل يتوافق مع الاتجاه؟ / هل يتوافق مع Order Block؟

FVG وحده لا يكفي للدخول.

==================================================
AGENT 6 — EXECUTION TRIGGER

المسؤول عن Trigger النهائي. ابحث على M5 ثم M1 عن:
1. Liquidity Sweep
2. CHoCH أو BOS
3. Displacement
4. Retest
5. Continuation

CHoCH لا يعتبر صحيحاً إلا إذا: تم كسر Swing واضح، بإغلاق شمعة (ليس Wick فقط)،
يوجد Displacement، ولم يحدث Immediate Rejection.

أفضل Trigger: Sweep → CHoCH → Displacement → Retest → Entry

==================================================
AGENT 7 — CANDLESTICK / PRICE ACTION

حلل: Engulfing / Pin Bar / Rejection / Momentum Candle / Long Wick /
Strong Body / Compression / Expansion.

أعطِ وزناً أعلى للشموع عند: Liquidity / Order Block / FVG / Support / Resistance.
Pattern واحد لا يكفي لإصدار قرار.

==================================================
AGENT 8 — VOLUME & MOMENTUM

حلل: Volume Expansion / Contraction / Momentum / Candle Range / سرعة الحركة / ATR إن توفر.

Breakout قوي + Volume قوي → يدعم الاستمرار.
Breakout ضعيف + Volume ضعيف → يزيد احتمال Fake Breakout.

==================================================
AGENT 9 — DXY CORRELATION

إذا كانت بيانات OHLC الخاصة بـ DXY متوفرة، حلل: Trend / Structure / Momentum / Breakout / Rejection.

DXY صاعد بقوة → ضغط هبوطي على الذهب.
DXY هابط بقوة → دعم صعودي للذهب.
لكن لا تستخدم العلاقة كقاعدة مطلقة.
إذا كان المتاح فقط dxy_price: لا تدّعِ تحليل Momentum أو Structure.

==================================================
AGENT 10 — SENTIMENT / STOP CLUSTERS

حدد مناطق تجمع السيولة المحتملة: Equal Highs/Lows / Previous High/Low / Session High/Low.

اسأل: هل السعر قريب من Liquidity؟ هل تم أخذ Liquidity؟
هل Entry يقع مباشرة أمام Liquidity قوية؟ إذا نعم: خفض جودة الصفقة.

==================================================
AGENT 11 — NEWS & MACRO FILTER

إذا كانت news_data متوفرة، ابحث عن أخبار عالية التأثير مرتبطة بـ:
USD / Fed / FOMC / CPI / PCE / NFP / GDP / Powell / Interest Rate / Employment / Inflation.

قاعدة الحظر: إذا كان هناك خبر عالي التأثير خلال ±20 دقيقة من وقت الدخول المتوقع:
decision = HOLD (إلا إذا كان النظام في News Trading Mode).

ممنوع اختلاق الأخبار. إذا لم تتوفر news_data: news_status = UNKNOWN.

==================================================
AGENT 12 — DYNAMIC RISK GUARD

قبل السماح بالصفقة تحقق من:
1. Entry منطقي.
2. SL خلف Structure حقيقي.
3. TP أمام Liquidity معاكسة.
4. الحركة المتوقعة مناسبة لمدة 20-30 دقيقة.
5. عدم وجود Entry متأخر.
6. SL ليس داخل Noise.
7. TP ليس مباشرة داخل Support/Resistance قوية.

(فحص R:R >= 1:2 نفسه يتم لاحقاً بالكود بشكل حتمي، لكن اختيارك لأسعار SL/TP
يجب أن يكون منطقياً بحيث يحقق هذا الشرط في الغالب).

إذا فشل شرط جوهري: HOLD.

==================================================
[6] ANTI-LATE-ENTRY ENGINE

ممنوع مطاردة السعر.
إذا تحرك السعر بالفعل لمسافة كبيرة من نقطة الانطلاق: HOLD
إلا إذا حدث Retest واضح لـ Order Block / FVG / Broken Structure ثم ظهر Trigger جديد.

==================================================
[7] ENTRY ENGINE

BUY: Entry بعد Confirmation، فوق Structure مكسور، أو عند Retest لمنطقة مؤسساتية.
SELL: Entry بعد Confirmation، تحت Structure مكسور، أو عند Retest لمنطقة مؤسساتية.

حدد: MARKET أو LIMIT.
إذا كان Market Entry غير آمن بسبب تمدد السعر: HOLD.

==================================================
[8] STOP LOSS ENGINE

SL ليس رقماً ثابتاً. ضعه خلف: Swing High/Low حقيقي / Order Block /
Liquidity Sweep Extreme / Structure Invalidation.

أضف Buffer مناسباً لتذبذب الذهب. لا تضع SL داخل Noise.
حدد sl_price فقط — لا تحسب النقاط.

==================================================
[9] TAKE PROFIT ENGINE

TP1: أقرب هدف منطقي يسمح بتقليل المخاطرة.
TP2: الهدف الرئيسي للحركة.

الأولوية: Liquidity → Previous High/Low → Support/Resistance → FVG → Measured Move.

حدد tp1_price و tp2_price فقط.
اختر مستويات تجعل TP1 >= 1R وTP2 >= 2R تقريباً بناءً على تقديرك للهيكل
(الفحص الدقيق يتم بالكود). إذا لم تستطع تحديد أهداف تحقق R:R >= 1:2 بشكل واقعي: HOLD.

==================================================
[10] CONSENSUS ENGINE

أوزان الوكلاء:
Agent 1 = 12% | Agent 2 = 5% | Agent 3 = 10% | Agent 4 = 8%
Agent 5 = 7%  | Agent 6 = 15% | Agent 7 = 6% | Agent 8 = 10%
Agent 9 = 8%  | Agent 10 = 5% | Agent 11 = 7% | Agent 12 = 7%
المجموع = 100%.

احسب weighted_buy_score وweighted_sell_score.
لا تعتمد على عدد الأصوات فقط.

==================================================
[11] HARD GATES

لا BUY إذا: M30/M15 هابطان بقوة، أو لا يوجد M5 Structure Confirmation،
أو لا يوجد M1/M5 Trigger، أو News Block فعال، أو Entry متأخر، أو البيانات غير كافية.

لا SELL إذا: M30/M15 صاعدان بقوة، أو لا يوجد M5 Structure Confirmation،
أو لا يوجد M1/M5 Trigger، أو News Block فعال، أو Entry متأخر، أو البيانات غير كافية.

(بوابة R:R >= 1:2 تُفرض لاحقاً بشكل حتمي بالكود بعد استلام الأسعار).

==================================================
[12] CONFIDENCE ENGINE

احسب الثقة بناءً على: Trend Alignment / Market Structure / Liquidity / Order Block /
FVG / Execution Trigger / Candlestick / Volume / Momentum / DXY / Session / News.

لا تسمح بـ BUY أو SELL إلا إذا:
confidence >= 75
وأيضاً weighted consensus >= 70
وأيضاً على الأقل 9 من 12 وكلاء يؤيدون الاتجاه أو لا يعارضونه بشكل جوهري
(عدد الوكلاء المصوّتين بعكس الاتجاه المرشح <= 3).

إذا لم تتحقق الشروط: HOLD.

==================================================
[13] HOLD PRIORITY

HOLD هو القرار الافتراضي. استخدمه عندما: الاتجاه غير واضح، الفريمات متعارضة،
لا يوجد Trigger، السعر في منتصف Range، الأخبار غير آمنة، DXY يعارض بقوة،
السعر ممتد، السيولة لم تُسحب، البيانات ناقصة، Confidence < 75،
Weighted Consensus < 70، أو أقل من 9 وكلاء مؤيدين/غير معارضين.

لا تجبر النظام على إصدار صفقة.

==================================================
[14] TRADE INVALIDATION

BUY: إذا أغلق السعر تحت Structure الذي اعتمد عليه الدخول → INVALID.
SELL: إذا أغلق السعر فوق Structure الذي اعتمد عليه الدخول → INVALID.

==================================================
[15] TRADE QUALITY SCORE

احسب trade_quality_score من 0 إلى 100.
90-100=A+ | 85-89=A | 80-84=B+ | 75-79=B | أقل من 75=NO TRADE
BUY/SELL ممنوع إذا trade_quality_score < 75.

==================================================
[16] RISK CALCULATION

لا تخاطر بنسبة أعلى من {max_risk_percent}.
إذا لم تُحدد: استخدم 1% كحد أقصى.

==================================================
[17] FINAL DECISION

إذا اكتملت جميع شروط BUY: decision = BUY
إذا اكتملت جميع شروط SELL: decision = SELL
غير ذلك: decision = HOLD
لا توجد نتيجة ثالثة.

==================================================
[18] JSON VALIDATION

تحقق من أن JSON صالح 100%.
ممنوع: Markdown / نص خارج JSON / Trailing Commas / قيم غير صحيحة / أسعار مخترعة.

decision يجب أن يكون: BUY أو SELL أو HOLD

إذا BUY أو SELL:
entry_price > 0
sl_price > 0
tp1_price > 0
tp2_price > 0
confidence >= 75
(ملاحظة: لا تُخرج points ولا rr إطلاقاً — يُحسبان بالكود)

إذا HOLD:
entry_price = null
sl_price = null
tp1_price = null
tp2_price = null

==================================================
[19] FINAL OUTPUT

أخرج JSON فقط بهذا الهيكل بالضبط (بدون أي حقول points أو rr):

{{
"decision": "BUY|SELL|HOLD",
"confidence": 0,
"trade_quality_score": 0,

"entry": {{
"type": "MARKET|LIMIT|NONE",
"price": null
}},

"stop_loss": {{
"price": null
}},

"take_profit": {{
"tp1_price": null,
"tp2_price": null
}},

"risk_percent": 0,
"expected_duration": "20-30 mins",
"session": "",
"market_bias": "BULLISH|BEARISH|NEUTRAL",

"consensus": {{
"buy_votes": 0,
"sell_votes": 0,
"neutral_votes": 0,
"weighted_buy_score": 0,
"weighted_sell_score": 0
}},

"agents": {{
"trend": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"session_liquidity": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"smc_liquidity": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"order_block": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"fvg": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"execution_trigger": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"candlestick": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"volume_momentum": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"dxy_correlation": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"sentiment_liquidity": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"news_macro": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}},
"risk_guard": {{"vote": "BUY|SELL|NEUTRAL", "score": 0, "reason": ""}}
}},

"key_levels": {{
"support": [],
"resistance": [],
"liquidity_high": [],
"liquidity_low": [],
"order_blocks": [],
"fvg_zones": []
}},

"invalidation": "",
"main_reason": "",
"risk_warning": ""
}}

==================================================
[20] ABSOLUTE FINAL RULE

لا توجد صفقة أفضل من صفقة سيئة. HOLD أفضل من BUY أو SELL ضعيف.
اعتمد فقط على البيانات الفعلية المرفقة.
لا تخترع سعراً. لا تخترع خبراً. لا تخترع Volume. لا تخترع DXY Structure.
لا تعتبر الاحتمال حقيقة. لا تطارد السعر.
لا تدخل بدون Structure Confirmation. لا تدخل بدون Trigger.
لا تدخل إذا كانت الثقة أقل من 75%. لا تدخل إذا لم يتحقق الإجماع المطلوب.
حدد الأسعار فقط بدقة — النقاط وR:R تُحسب برمجياً خارج هذا البرومت.
"""

# ============ طبقة الحساب البرمجي الحتمي (نقاط + R:R) ============
POINT_VALUE_USD = 0.10  # 1 نقطة = 0.10$ على الذهب

def price_to_points(price_diff: float) -> float:
    return round(abs(price_diff) / POINT_VALUE_USD, 1)

def calculate_trade_metrics(entry_price: float, sl_price: float, tp1_price: float, tp2_price: float) -> dict:
    sl_points = price_to_points(entry_price - sl_price)
    tp1_points = price_to_points(tp1_price - entry_price)
    tp2_points = price_to_points(tp2_price - entry_price)
    risk = abs(entry_price - sl_price)
    reward_tp1 = abs(tp1_price - entry_price)
    reward_tp2 = abs(tp2_price - entry_price)
    rr_tp1 = round(reward_tp1 / risk, 2) if risk > 0 else None
    rr_tp2 = round(reward_tp2 / risk, 2) if risk > 0 else None
    return {
        "sl_points": sl_points, "tp1_points": tp1_points, "tp2_points": tp2_points,
        "rr_tp1": rr_tp1, "rr_tp2": rr_tp2, "risk_dollars": round(risk, 2),
    }

def validate_trade_gates(decision: str, confidence: float, trade_quality_score: float,
                          metrics: Optional[dict], min_rr: float = 2.0,
                          min_confidence: float = 75, min_quality: float = 75) -> tuple:
    """بوابة قبول حتمية لا تعتمد على تقييم الموديل لنفسه. ترجع (مقبول: bool, سبب: str)."""
    if decision == "HOLD":
        return True, "HOLD"
    if decision not in ("BUY", "SELL"):
        return False, f"decision غير صالح: {decision}"
    if confidence < min_confidence:
        return False, f"confidence ({confidence}) أقل من {min_confidence}"
    if trade_quality_score < min_quality:
        return False, f"trade_quality_score ({trade_quality_score}) أقل من {min_quality}"
    if not metrics or metrics.get("rr_tp2") is None:
        return False, "تعذر حساب R:R - أسعار غير مكتملة"
    if metrics["rr_tp2"] < min_rr:
        return False, f"R:R ({metrics['rr_tp2']}) أقل من {min_rr}"
    return True, "OK"

async def get_news_summary_text() -> str:
    async with db_lock:
        blocked = time.time() < db["news_blocked_until"]
        upcoming = db["upcoming_news"][:3]
    if blocked:
        return "🔴 يوجد خبر عالي التأثير قريب - الدخول محظور حاليًا"
    if upcoming:
        items = "; ".join(n.get("title", "") for n in upcoming)
        return f"أخبار قادمة: {items}"
    return "لا توجد أخبار عالية التأثير قريبة"



# ============ دوال المساعدة ============

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def is_weekend():
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    if weekday == 4 and (hour > WEEKEND_CLOSE_HOUR or (hour == WEEKEND_CLOSE_HOUR and minute >= 0)):
        return True
    if weekday == 5:
        return True
    if weekday == 6 and (hour < WEEKEND_OPEN_HOUR or (hour == WEEKEND_OPEN_HOUR and minute == 0)):
        return True
    return False

def is_active_trading_session() -> bool:
    """تقتصر على جلستي لندن ونيويورك (أو تداخلهما) فقط - يوفر طلبات TwelveData خلال طوكيو/سيدني"""
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    return (LONDON_SESSION[0] <= hour < LONDON_SESSION[1] or
            NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1])

def is_valid_session():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    return (LONDON_SESSION[0] <= hour < LONDON_SESSION[1] or
            NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1] or
            TOKYO_SESSION[0] <= hour < TOKYO_SESSION[1] or
            hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1])

def get_session_name():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    if LONDON_SESSION[0] <= hour < LONDON_SESSION[1]: return "لندن 🇬🇧"
    elif NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]: return "نيويورك 🇺🇸"
    elif TOKYO_SESSION[0] <= hour < TOKYO_SESSION[1]: return "طوكيو 🇯🇵"
    elif hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1]: return "سيدني 🇦🇺"
    return "خارج الجلسات ⏸️"

def get_all_active_sessions():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    active = []
    if LONDON_SESSION[0] <= hour < LONDON_SESSION[1]: active.append("لندن 🇬🇧")
    if NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]: active.append("نيويورك 🇺🇸")
    if TOKYO_SESSION[0] <= hour < TOKYO_SESSION[1]: active.append("طوكيو 🇯🇵")
    if hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1]: active.append("سيدني 🇦🇺")
    return active

def format_candles(candles: list, max_candles: int = 10) -> str:
    if not candles:
        return "لا توجد بيانات"
    selected = candles[:max_candles]
    lines = ["Time,Open,High,Low,Close,Volume"]
    for c in selected:
        line = f"{c.get('datetime','')},{c.get('open','')},{c.get('high','')},{c.get('low','')},{c.get('close','')},{c.get('volume','')}"
        lines.append(line)
    return "\n".join(lines)

def calculate_pnl(direction: str, entry: float, current: float) -> tuple:
    if direction == "BUY":
        price_diff = current - entry
    else:
        price_diff = entry - current
    pips = price_diff / GOLD_PIP_VALUE
    return pips, price_diff

def calculate_pnl_usd(pips: float, lot_size: float = 0.01) -> float:
    pip_value = GOLD_PIP_USD_PER_LOT * lot_size
    return pips * pip_value

def calculate_lot_size(balance: float, risk_percent: float, sl_pips: float) -> float:
    """يحسب حجم اللوت بناء على رصيد المستخدم ونسبة مخاطرته الخاصة"""
    if sl_pips <= 0 or balance <= 0:
        return 0.01
    risk_amount = balance * (risk_percent / 100)
    lot = risk_amount / (sl_pips * GOLD_PIP_USD_PER_LOT)
    return max(0.01, round(lot, 2))

# ============ الاتصالات ============

async def _send_raw(chat_id: str, text: str, keyboard: list = None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
    except Exception as e:
        print(f"❌ فشل ارسال Telegram الى {chat_id}: {e}")

async def send_msg(text: str):
    """يبث الرسالة لكل المستخدمين المصرح لهم (وليس قناة واحدة ثابتة)"""
    user_ids = await get_all_authorized_user_ids()
    if not user_ids:
        await _send_raw(TELEGRAM_CHAT_ID, text)
        return
    for uid in user_ids:
        await _send_raw(uid, text)

async def send_msg_with_buttons(text: str, keyboard: list):
    """نفس البث الجماعي لكن مع نفس لوحة الأزرار للجميع (للتنقل العام، وليس تأكيد صفقات فردي)"""
    user_ids = await get_all_authorized_user_ids()
    if not user_ids:
        await _send_raw(TELEGRAM_CHAT_ID, text, keyboard)
        return
    for uid in user_ids:
        await _send_raw(uid, text, keyboard)

async def broadcast_signal_to_users(signal_id: str, text: str):
    """يرسل إشارة تداول لكل مستخدم برسالته الخاصة، بأزرار قبول/رفض تحمل معرفه هو تحديدا"""
    user_ids = await get_all_authorized_user_ids()
    targets = user_ids if user_ids else [TELEGRAM_CHAT_ID]
    for uid in targets:
        keyboard = [[
            {"text": "✅ دخلت الصفقة", "callback_data": f"accept_{signal_id}_{uid}"},
            {"text": "❌ تجاهل", "callback_data": f"reject_{signal_id}_{uid}"},
        ]]
        await _send_raw(uid, text, keyboard)

def quick_action_keyboard_raw() -> list:
    """أزرار سريعة بصيغة dict خام (لاستخدامها مع send_msg_with_buttons)"""
    row1 = [
        {"text": "🏠 القائمة الرئيسية", "callback_data": "menu_start"},
        {"text": "📊 حالة البوت", "callback_data": "status"},
    ]
    if ADMIN_CONTACT:
        row2 = [{"text": "❓ Help", "url": f"https://t.me/{ADMIN_CONTACT.lstrip('@').strip()}"}]
    else:
        row2 = [{"text": "❓ Help", "callback_data": "help_cmd"}]
    return [row1, row2]

def quick_action_keyboard() -> InlineKeyboardMarkup:
    """نفس الأزرار السريعة بصيغة InlineKeyboardMarkup (لاستخدامها مع reply_markup مباشرة)"""
    row1 = [
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="menu_start"),
        InlineKeyboardButton("📊 حالة البوت", callback_data="status"),
    ]
    if ADMIN_CONTACT:
        row2 = [InlineKeyboardButton("❓ Help", url=f"https://t.me/{ADMIN_CONTACT.lstrip('@').strip()}")]
    else:
        row2 = [InlineKeyboardButton("❓ Help", callback_data="help_cmd")]
    return InlineKeyboardMarkup([row1, row2])

async def send_photo(photo_path: str, caption: str = ""):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("chat_id", TELEGRAM_CHAT_ID)
            data.add_field("photo", f)
            data.add_field("caption", caption)
            data.add_field("parse_mode", "HTML")
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
    except Exception as e:
        print(f"❌ فشل ارسال صورة: {e}")

def _next_utc_midnight_ts() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.timestamp()

async def _mark_twelvedata_exhausted(message: str):
    async with db_lock:
        already_notified = db["twelvedata_pause_notified"]
        db["twelvedata_paused_until"] = _next_utc_midnight_ts()
        db["twelvedata_pause_notified"] = True
    if not already_notified:
        await send_msg(
            "⛔ <b>نفذ رصيد TwelveData اليومي</b>\n\n"
            f"{message}\n\n"
            "تم إيقاف طلبات الأسعار تلقائيًا حتى تصفير الرصيد (منتصف الليل UTC) لتوفير أي رصيد متبقي، "
            "وسيستأنف التحليل تلقائيًا بعدها."
        )

async def _twelvedata_paused() -> bool:
    async with db_lock:
        paused_until = db["twelvedata_paused_until"]
        if paused_until and time.time() < paused_until:
            return True
        if paused_until and time.time() >= paused_until:
            db["twelvedata_paused_until"] = 0
            db["twelvedata_pause_notified"] = False
        return False

# ============ منظّم الطلبات + تخزين مؤقت ذكي لتقليل استهلاك رصيد TwelveData ============
TD_MAX_PER_MINUTE = 7  # هامش أمان تحت حد الخطة (8/دقيقة)
_td_request_times = deque()
_td_rate_lock = asyncio.Lock()

_td_cache = {}  # (symbol, interval) -> (timestamp, candles)
_td_cache_lock = asyncio.Lock()
_TD_CACHE_TTL = {
    "1min": 90,     # نصف دورة الفحص (3 دقايق) تقريبا
    "5min": 270,    # اقل من مدة الشمعة الفعلية بشوي
    "15min": 780,
    "30min": 1500,
}

async def _throttle_twelvedata():
    while True:
        async with _td_rate_lock:
            now = time.time()
            while _td_request_times and now - _td_request_times[0] > 60:
                _td_request_times.popleft()
            if len(_td_request_times) < TD_MAX_PER_MINUTE:
                _td_request_times.append(now)
                return
            wait = 60 - (now - _td_request_times[0]) + 0.1
        await asyncio.sleep(wait)


async def fetch_tf(interval: str, symbol: str = SYMBOL):
    if await _twelvedata_paused():
        return {}

    cache_key = (symbol, interval)
    ttl = _TD_CACHE_TTL.get(interval, 60)
    async with _td_cache_lock:
        cached = _td_cache.get(cache_key)
        candles = cached[1] if cached and (time.time() - cached[0]) < ttl else None
    if candles is not None:
        if candles:
            current_close = float(candles[0]["close"])
            async with db_lock:
                if symbol == SYMBOL: db["last_price"] = current_close
                elif symbol == DXY_SYMBOL: db["dxy_price"] = current_close
        return candles

    await _throttle_twelvedata()
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": 20, "apikey": TWELVE_DATA_API_KEY}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if "code" in data and data["code"] != 200:
                    error_msg = data.get("message", "unknown")
                    print(f"⚠️ Twelve Data خطأ {interval}: {error_msg}")
                    if "run out of api credits" in error_msg.lower():
                        await _mark_twelvedata_exhausted(error_msg)
                    return {}
                if "values" in data and data["values"]:
                    candles = data["values"]
                    async with _td_cache_lock:
                        _td_cache[cache_key] = (time.time(), candles)
                    current_close = float(candles[0]["close"])
                    async with db_lock:
                        if symbol == SYMBOL: db["last_price"] = current_close
                        elif symbol == DXY_SYMBOL: db["dxy_price"] = current_close
                    return candles
                else:
                    print(f"⚠️ Twelve Data: لا بيانات {interval}")
                    return {}
    except Exception as e:
        print(f"❌ استثناء fetch_tf {interval}: {e}")
        return {}

async def fetch_price():
    candles = await fetch_tf("1min")
    if candles:
        return float(candles[0]["close"])
    async with db_lock: return db["last_price"]

async def fetch_dxy_price():
    candles = await fetch_tf("1min", DXY_SYMBOL)
    if candles:
        return float(candles[0]["close"])
    async with db_lock: return db["dxy_price"]

async def fetch_all_tf():
    result = {}
    for label, interval in TIMEFRAMES.items():
        try:
            data = await fetch_tf(interval)
            result[label] = data if data else {}
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"❌ فشل جلب {label}: {e}")
            result[label] = {}
    return result



# ============ تحليل الذكاء الاصطناعي ============

async def _mark_gemini_exhausted(message: str):
    async with db_lock:
        already_notified = db["gemini_pause_notified"]
        db["gemini_paused_until"] = _next_utc_midnight_ts()
        db["gemini_pause_notified"] = True
    if not already_notified:
        await send_msg(
            "⛔ <b>نفذ رصيد Gemini اليومي</b>\n\n"
            f"{message}\n\n"
            "تم إيقاف استدعاء Gemini تلقائيًا حتى تصفير الرصيد، والنظام سيعمل بـ Groq فقط مؤقتًا (بدون تأكيد ثنائي)."
        )

async def _gemini_paused() -> bool:
    async with db_lock:
        paused_until = db["gemini_paused_until"]
        if paused_until and time.time() < paused_until:
            return True
        if paused_until and time.time() >= paused_until:
            db["gemini_paused_until"] = 0
            db["gemini_pause_notified"] = False
        return False


def _build_signal_from_agent_json(data: dict) -> Optional[TradeSignal]:
    """يحوّل استجابة البرومت الجديد (12 وكيل) إلى TradeSignal، مع حساب النقاط وR:R
    برمجيًا بدل الاعتماد على حساب الموديل، وتطبيق بوابة القبول الحتمية."""
    decision = str(data.get("decision", "HOLD")).upper()
    confidence = max(0, min(100, int(data.get("confidence", 0) or 0)))
    trade_quality_score = max(0, min(100, int(data.get("trade_quality_score", 0) or 0)))

    entry_price = sl_price = tp1_price = tp2_price = None
    metrics = None
    if decision in ("BUY", "SELL"):
        entry_price = data.get("entry", {}).get("price")
        sl_price = data.get("stop_loss", {}).get("price")
        tp1_price = data.get("take_profit", {}).get("tp1_price")
        tp2_price = data.get("take_profit", {}).get("tp2_price")
        if None in (entry_price, sl_price, tp1_price, tp2_price):
            decision = "HOLD"
        else:
            entry_price, sl_price, tp1_price, tp2_price = float(entry_price), float(sl_price), float(tp1_price), float(tp2_price)
            metrics = calculate_trade_metrics(entry_price, sl_price, tp1_price, tp2_price)

    accepted, gate_reason = validate_trade_gates(decision, confidence, trade_quality_score, metrics)
    if not accepted:
        decision = "HOLD"

    agents_summary = ""
    agents = data.get("agents", {})
    if agents:
        votes = [f"{name}:{info.get('vote','?')}" for name, info in agents.items()]
        agents_summary = " | ".join(votes)

    summary = data.get("main_reason", "") or ""
    risk_warning = data.get("risk_warning", "")
    if risk_warning:
        summary = f"{summary} ⚠️ {risk_warning}".strip()
    if not accepted and gate_reason != "HOLD":
        summary = f"{summary} [مرفوض برمجيًا: {gate_reason}]".strip()

    return TradeSignal(
        decision=decision,
        confidence=confidence,
        entry_price=entry_price if decision in ("BUY", "SELL") else 0,
        sl_pips=metrics["sl_points"] if metrics else 0,
        tp1_pips=metrics["tp1_points"] if metrics else 0,
        tp2_pips=metrics["tp2_points"] if metrics else 0,
        rr=f"1:{metrics['rr_tp2']}" if metrics and metrics.get("rr_tp2") is not None else "",
        risk_percent=float(data.get("risk_percent", 1.0) or 1.0),
        duration=data.get("expected_duration", ""),
        session=data.get("session", ""),
        agent_details=agents_summary,
        summary=summary,
    )


async def analyze_gemini_structured(tf_data: dict, dxy_price: float) -> Optional[TradeSignal]:
    if await _gemini_paused():
        return None
    try:
        async with db_lock:
            db["last_gemini_call"] = time.time()
            db["gemini_calls_today"] += 1

        news_summary = await get_news_summary_text()
        prompt = GOLD_SCALP_PROMPT_JSON.format(
            data_m30=format_candles(tf_data.get("M30", [])),
            data_m15=format_candles(tf_data.get("M15", [])),
            data_m5=format_candles(tf_data.get("M5", [])),
            data_m1=format_candles(tf_data.get("M1", [])),
            data_dxy=f"DXY الحالي فقط (بدون تاريخ شموع): {dxy_price}",
            dxy_price=dxy_price,
            current_time=now_str(),
            current_session=get_session_name(),
            news_data=news_summary,
            account_balance="غير محدد - نظام متعدد المستخدمين (كل مستخدم رصيده الخاص)",
            max_risk_percent="1%",
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 3000,
                "responseMimeType": "application/json"
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                result = await resp.json()

                if "error" in result:
                    err_msg = result["error"].get("message", "Unknown Gemini error")
                    print(f"❌ Gemini API خطأ: {err_msg}")
                    if "exceeded your current quota" in err_msg.lower():
                        await _mark_gemini_exhausted(err_msg)
                    return None

                if "candidates" not in result or not result["candidates"]:
                    print("❌ Gemini: لا يوجد candidates")
                    return None

                text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = text.replace("```json", "").replace("```", "").strip()

                data = json.loads(text)
                signal = _build_signal_from_agent_json(data)
                if signal is None:
                    return None

                if not signal.is_valid():
                    print(f"⚠️ إشارة Gemini مرفوضة: entry={signal.entry_price}, sl={signal.sl_pips}, conf={signal.confidence}")
                    return None

                return signal

    except json.JSONDecodeError as e:
        print(f"❌ Gemini JSON غير صالح: {e}")
        return None
    except Exception as e:
        print(f"❌ استثناء Gemini: {e}")
        return None

async def analyze_groq_structured(tf_data: dict, dxy_price: float) -> Optional[TradeSignal]:
    try:
        news_summary = await get_news_summary_text()
        prompt = GOLD_SCALP_PROMPT_JSON.format(
            data_m30=format_candles(tf_data.get("M30", [])),
            data_m15=format_candles(tf_data.get("M15", [])),
            data_m5=format_candles(tf_data.get("M5", [])),
            data_m1=format_candles(tf_data.get("M1", [])),
            data_dxy=f"DXY الحالي فقط (بدون تاريخ شموع): {dxy_price}",
            dxy_price=dxy_price,
            current_time=now_str(),
            current_session=get_session_name(),
            news_data=news_summary,
            account_balance="غير محدد - نظام متعدد المستخدمين (كل مستخدم رصيده الخاص)",
            max_risk_percent="1%",
        )

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "أنت محلل فني خبير في تداول الذهب (XAU/USD). أعطِ قراراً واضحاً: BUY أو SELL أو HOLD. أخرج النتيجة بصيغة JSON فقط."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 3000,
            "temperature": 0.1,
            "top_p": 0.9,
            "response_format": {"type": "json_object"}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                result = await resp.json()

                if "error" in result:
                    print(f"❌ Groq API خطأ: {result['error'].get('message', 'Unknown')}")
                    return None

                if "choices" not in result or not result["choices"]:
                    print("❌ Groq: لا يوجد choices")
                    return None

                text = result["choices"][0]["message"]["content"].strip()
                text = text.replace("```json", "").replace("```", "").strip()

                data = json.loads(text)
                signal = _build_signal_from_agent_json(data)
                if signal is None:
                    return None

                if not signal.is_valid():
                    print(f"⚠️ إشارة Groq مرفوضة: entry={signal.entry_price}, sl={signal.sl_pips}, conf={signal.confidence}")
                    return None

                return signal

    except json.JSONDecodeError as e:
        print(f"❌ Groq JSON غير صالح: {e}")
        return None
    except Exception as e:
        print(f"❌ استثناء Groq: {e}")
        return None

async def consensus_analysis(tf_data: dict, dxy_price: float):
    print("🔄 [consensus] بدء تحليل الإجماع...")

    if await _gemini_paused():
        print("⏸️ [consensus] Gemini متوقف مؤقتاً (نفاذ الرصيد) - تخطي هذه الدورة بدون Groq")
        return None, "GEMINI_PAUSED", 0

    gemini_signal = await analyze_gemini_structured(tf_data, dxy_price)
    if gemini_signal is None:
        print("⚠️ [consensus] Gemini فشل - تجربة Groq فقط كاحتياطي")
        groq_signal = await analyze_groq_structured(tf_data, dxy_price)
        if groq_signal is None:
            print("⚠️ [consensus] Groq فشل ايضا")
            return None, "BOTH_FAIL", 0
        reduced_confidence = max(50, groq_signal.confidence - 15)
        print(f"🦙 [consensus] Groq فقط (احتياطي): {groq_signal.decision} | ثقة مخفضة: {reduced_confidence}%")
        groq_signal.confidence = reduced_confidence
        return groq_signal, "GROQ_ONLY", reduced_confidence

    print(f"🤖 [consensus] Gemini: {gemini_signal.decision} (ثقة {gemini_signal.confidence}%)")

    groq_signal = await analyze_groq_structured(tf_data, dxy_price)
    if groq_signal is None:
        print("⚠️ [consensus] Groq فشل، استخدام Gemini فقط")
        return gemini_signal, "GEMINI_ONLY", gemini_signal.confidence

    print(f"🦙 [consensus] Groq: {groq_signal.decision} (ثقة {groq_signal.confidence}%)")

    if gemini_signal.decision == groq_signal.decision and gemini_signal.decision in ["BUY", "SELL"]:
        consensus_confidence = min(95, max(gemini_signal.confidence, groq_signal.confidence) + 10)
        print(f"✅ [consensus] إجماع على {gemini_signal.decision}! ثقة: {consensus_confidence}%")
        best_signal = gemini_signal if gemini_signal.confidence >= groq_signal.confidence else groq_signal
        best_signal.confidence = consensus_confidence
        return best_signal, "CONSENSUS", consensus_confidence

    elif gemini_signal.decision in ["BUY", "SELL"] and groq_signal.decision == "HOLD":
        reduced_confidence = max(55, gemini_signal.confidence - 10)
        print(f"⚠️ [consensus] إجماع ضعيف: {gemini_signal.decision} | ثقة مخفضة: {reduced_confidence}%")
        gemini_signal.confidence = reduced_confidence
        return gemini_signal, "WEAK_CONSENSUS", reduced_confidence

    elif gemini_signal.decision != groq_signal.decision and gemini_signal.decision in ["BUY", "SELL"] and groq_signal.decision in ["BUY", "SELL"]:
        print(f"❌ [consensus] خلاف! Gemini: {gemini_signal.decision} vs Groq: {groq_signal.decision} → HOLD")
        return None, "DISAGREEMENT", 0

    else:
        return gemini_signal, "NO_CONSENSUS", gemini_signal.confidence



# ============ الأخبار ============

async def calculate_atr(candles: list, period: int = 14):
    if len(candles) < period + 1: return 0.0
    tr_values = []
    for i in range(1, len(candles)):
        high, low = float(candles[i]["high"]), float(candles[i]["low"])
        prev_close = float(candles[i-1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
    if len(tr_values) < period:
        return sum(tr_values) / len(tr_values) if tr_values else 0.0
    return sum(tr_values[-period:]) / period

async def fetch_forex_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                xml_data = await resp.text()
                root = ET.fromstring(xml_data)
                news_list = []
                now = datetime.now(timezone.utc)
                for event in root.findall("event"):
                    try:
                        currency = event.find("country").text
                        impact = event.find("impact").text
                        time_str = event.find("date").text + " " + event.find("time").text
                        event_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        title = event.find("title").text
                        if currency == "USD" and impact == "High":
                            minutes_until = (event_time - now).total_seconds() / 60
                            news_list.append({
                                "title": title, "time": event_time, "minutes_until": minutes_until,
                                "impact": impact, "currency": currency,
                                "id": f"{currency}_{event_time.strftime('%Y%m%d_%H%M')}"
                            })
                    except: continue
                news_list.sort(key=lambda x: x["minutes_until"])
                return news_list
    except Exception as e:
        print(f"⚠️ فشل جلب الاخبار: {e}")
        return []

async def check_news_and_alert():
    try:
        news_list = await fetch_forex_news()
        now = time.time()
        async with db_lock: db["upcoming_news"] = news_list
        blocking_news, warning_news = [], []
        for news in news_list:
            news_id = news["id"]
            minutes_until = news["minutes_until"]
            if 25 <= minutes_until <= 35:
                async with db_lock:
                    if news_id not in db["news_notified"]:
                        db["news_notified"][news_id] = {"warned": True, "started": False, "ended": False}
                        warning_news.append(news)
            if -30 <= minutes_until <= 30:
                blocking_news.append(news)
                async with db_lock:
                    if news_id in db["news_notified"] and not db["news_notified"][news_id].get("started", False):
                        db["news_notified"][news_id]["started"] = True
                        await send_msg(f"🔴 <b>خبر عاجل الان!</b>\n📰 {news['title']}\n⏰ {news['time'].strftime('%H:%M')} UTC\n⚠️ توقف عن فتح صفقات جديدة لمدة 30 دقيقة")
            if minutes_until < -30:
                async with db_lock:
                    if news_id in db["news_notified"] and not db["news_notified"][news_id].get("ended", False):
                        db["news_notified"][news_id]["ended"] = True
                        await send_msg(f"🟢 <b>انتهى تأثير الخبر</b>\n📰 {news['title']}\n✅ يمكن استئناف التداول")
        if warning_news:
            titles = "\n".join([f"• <b>{n['title']}</b> ({n['time'].strftime('%H:%M')} UTC)" for n in warning_news[:3]])
            await send_msg(f"⚠️ <b>تحذير: اخبار عاجلة خلال 30 دقيقة!</b>\n\n{titles}\n\n🔴 سيتم ايقاف فتح الصفقات الجديدة\n⏸️ انتظر حتى تمر الاخبار")
        if blocking_news:
            max_block = max([n["minutes_until"] for n in blocking_news])
            async with db_lock: db["news_blocked_until"] = now + (max_block + 30) * 60
        else:
            async with db_lock:
                if db["news_blocked_until"] > 0 and now > db["news_blocked_until"]: db["news_blocked_until"] = 0
        async with db_lock:
            for oid in [nid for nid, info in db["news_notified"].items() if info.get("ended", False)][:50]:
                if oid in db["news_notified"]: del db["news_notified"][oid]
        return len(blocking_news) > 0
    except Exception as e:
        print(f"❌ خطأ check_news_and_alert: {e}")
        return False

async def is_news_blocking():
    async with db_lock: return time.time() < db["news_blocked_until"]

# ============ التقارير والرسوم ============

async def generate_performance_summary(user_id: str, period: str = "weekly"):
    account = await get_user_account(user_id)
    stats = account["stats"]
    total = stats["wins"] + stats["losses"]
    win_rate = (stats["wins"] / total * 100) if total > 0 else 0
    if period == "weekly": period_name, pips_data = "اسبوعي", stats.get("weekly_pips", {})
    elif period == "monthly": period_name, pips_data = "شهري", stats.get("monthly_pips", {})
    else: period_name, pips_data = "يومي", stats.get("daily_pips", {})
    period_pips = sum(pips_data.values()) if pips_data else stats["total_pips"]
    async with db_lock:
        gemini_calls = db["gemini_calls_today"]
    return f"""📊 <b>ملخص الاداء {period_name}</b>
📈 الصفقات: {total} | ✅ {stats["wins"]} | ❌ {stats["losses"]}
📉 نسبة الربح: {win_rate:.1f}%
💰 النقاط: {stats["total_pips"]:+.1f} | الفترة: {period_pips:+.1f}
⚖️ المخاطرة: {account["risk_percent"]}%
💵 الرصيد: {account["balance"]:,.2f} USD
📈 ربح/خسارة: {(account["balance"] - account["initial_balance"]):+,.2f} USD
🤖 تحليلات اليوم: {gemini_calls}"""

async def generate_equity_chart(user_id: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        account = await get_user_account(user_id)
        history = account["equity_history"]
        initial = account["initial_balance"]
        current = account["balance"]
        if len(history) < 2:
            dates = [datetime.now(timezone.utc)]
            balances = [current]
        else:
            dates = [datetime.fromisoformat(h["date"]) if isinstance(h["date"], str) else h["date"] for h in history]
            balances = [h["balance"] for h in history]
        fig, ax = plt.subplots(figsize=(10, 6))
        if len(dates) >= 2:
            ax.plot(dates, balances, linewidth=2, color="#00D26A", marker="o", markersize=4)
            ax.fill_between(dates, balances, initial, alpha=0.3, color="#00D26A")
        else:
            ax.scatter(dates, balances, color="#00D26A", s=100, zorder=5)
        ax.axhline(y=initial, color="gray", linestyle="--", alpha=0.5, label="الرصيد الابتدائي")
        ax.set_title("📈 نمو الرصيد", fontsize=16, fontweight="bold", color="white")
        ax.set_xlabel("التاريخ", fontsize=12, color="white")
        ax.set_ylabel("الرصيد (USD)", fontsize=12, color="white")
        ax.grid(True, alpha=0.3)
        ax.legend()
        if len(dates) >= 2:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.xticks(rotation=45)
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_facecolor("#1a1a2e")
        ax.tick_params(colors="white")
        for spine in ax.spines.values(): spine.set_color("white")
        plt.tight_layout()
        chart_path = "/tmp/equity_chart.png"
        plt.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
        plt.close()
        return chart_path
    except Exception as e:
        print(f"❌ خطأ رسم بياني: {e}")
        return None



# ============ أوامر Telegram ============

@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 الحالة", callback_data="status"), InlineKeyboardButton("💵 السعر", callback_data="price")],
        [InlineKeyboardButton("📈 الاشارة", callback_data="signal"), InlineKeyboardButton("📉 الاحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📊 اسبوعي", callback_data="weekly"), InlineKeyboardButton("📊 شهري", callback_data="monthly")],
        [InlineKeyboardButton("📈 رسم الرصيد", callback_data="equity_chart"), InlineKeyboardButton("⚡ ATR", callback_data="atr")],
        [InlineKeyboardButton("💰 تحديد الرصيد", callback_data="menu_setbalance"), InlineKeyboardButton("🔍 اخطاء", callback_data="errors")],
        [InlineKeyboardButton("⏸️ ايقاف", callback_data="pause"), InlineKeyboardButton("▶️ استئناف", callback_data="resume")],
    ]
    reply = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text(
        "🤖 <b>بوت الذهب الذكي v7.1</b>\n\n"
        "✅ الميزات:\n"
        "• 💾 حفظ البيانات\n"
        "• ✅ نظام تأكيد يدوي للصفقات\n"
        "• 💰 حساب PnL صحيح للذهب\n"
        "• 🔔 اشعارات اخبار قبل 30 دقيقة\n"
        "• 🎯 تحليل يقتصر على جلستي لندن ونيويورك\n"
        "• 📊 تحديثات فقط عند التغيرات المهمة\n\n"
        "اختر خياراً:",
        parse_mode="HTML", reply_markup=reply
    )

@require_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    account = await get_user_account(user_id)
    async with db_lock:
        paused = db["paused"]
        signals_count = len(db["signals"])
        blocked = time.time() < db["news_blocked_until"]
        atr_current = db["atr_data"]["current"]
        dxy = db["dxy_price"]
        analysis_count = db["analysis_count"]
        errors_count = len(db["api_errors"])
        uptime = int(time.time() - db["bot_start_time"])
        gemini_calls = db["gemini_calls_today"]
        upcoming = len(db["upcoming_news"])
        recent_signals_count = len(db["pending_signals"])
    active = account["active_trade"]
    risk = account["risk_percent"]
    status = "⏸️ متوقف" if paused else "✅ يعمل"
    trade_status = f"صفقة {active['direction']} نشطة" if active else "لا توجد صفقة"
    news_status = "🔴 موقف" if blocked else "🟢 لا اخبار"
    active_sessions = ", ".join(get_all_active_sessions()) or "خارج الجلسات"
    uptime_str = f"{uptime//3600}h {(uptime%3600)//60}m"
    weekend_status = "🛑 عطلة نهاية الاسبوع" if is_weekend() else "🟢 ايام عمل"
    msg = f"""📊 <b>حالة البوت v7.1</b>
الحالة: {status}
الجلسات: {active_sessions}
{weekend_status}
صفقتك: {trade_status}
اشارات مرسلة مؤخرا: {recent_signals_count}
اشارات: {signals_count} | تحاليل: {analysis_count}
المخاطرة: {risk}% | اخطاء: {errors_count}
الاخبار: {news_status} | قادمة: {upcoming}
ATR: {atr_current:.2f} | DXY: {dxy:.2f}
🤖 تحليلات اليوم: {gemini_calls}
⏱️ وقت التشغيل: {uptime_str}"""
    await update.effective_message.reply_text(msg, parse_mode="HTML")

@require_auth
async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = await fetch_price()
        dxy = await fetch_dxy_price()
        account = await get_user_account(str(update.effective_user.id))
        active = account["active_trade"]
        msg = f"💵 <b>الاسعار</b>\n\n🥇 XAU/USD: <code>{price:,.2f}</code>\n💵 DXY: <code>{dxy:.2f}</code>"
        if active:
            entry = active.get("entry_price", 0)
            direction = active.get("direction", "")
            if entry > 0 and direction:
                pips, _ = calculate_pnl(direction, entry, price)
                pnl_usd = calculate_pnl_usd(pips, active.get("lot_size", 0.01))
                msg += f"\n\n📊 <b>صفقتك النشطة:</b>\n{direction} @ {entry:,.2f}\nP&L: {pips:+.1f} نقاط ({pnl_usd:+.2f}$)"
        await update.effective_message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ خطأ: {e}")

@require_auth
async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        if not db["signals"]:
            await update.effective_message.reply_text("⏳ لا توجد اشارات بعد")
            return
        last = db["signals"][-1]
    await update.effective_message.reply_text(f"📈 <b>آخر اشارة</b>\n\n{last['text']}", parse_mode="HTML")

@require_auth
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    account = await get_user_account(user_id)
    stats = account["stats"]
    total = stats["wins"] + stats["losses"]
    win_rate = (stats["wins"] / total * 100) if total > 0 else 0
    balance = account["balance"]
    initial = account["initial_balance"]
    trades = await get_user_trades(user_id, limit=5)
    async with db_lock:
        analysis_count = db["analysis_count"]
        gemini_calls = db["gemini_calls_today"]
    recent_trades = ""
    if trades:
        recent_trades = "\n\n📋 <b>آخر 5 صفقات:</b>\n"
        for t in trades:
            result_emoji = "✅" if t.get("result") == "win" else "❌"
            recent_trades += f"{result_emoji} {t['direction']} {t['pnl_pips']:+.1f} نقاط ({t.get('pnl_usd', 0):+.2f}$) @ {t['exit_price']:,.2f}\n"
    msg = f"""📉 <b>احصائياتك</b>
الصفقات: {total} | ✅ {stats["wins"]} | ❌ {stats["losses"]}
الربح: {win_rate:.1f}% | النقاط: {stats["total_pips"]:+.1f}
التحاليل: {analysis_count} | تحليلات اليوم: {gemini_calls}
💵 الرصيد: {balance:,.2f} USD
📈 ربح/خسارة: {(balance - initial):+,.2f} USD
{recent_trades}"""
    await update.effective_message.reply_text(msg, parse_mode="HTML")

@require_auth
async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await generate_performance_summary(str(update.effective_user.id), "weekly")
    await update.effective_message.reply_text(msg, parse_mode="HTML")

@require_auth
async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await generate_performance_summary(str(update.effective_user.id), "monthly")
    await update.effective_message.reply_text(msg, parse_mode="HTML")

@require_auth
async def cmd_equity_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.effective_message.reply_text("⏳ جاري انشاء الرسم...")
    chart_path = await generate_equity_chart(user_id)
    if chart_path:
        account = await get_user_account(user_id)
        balance = account["balance"]
        initial = account["initial_balance"]
        caption = f"📈 <b>نمو رصيدك</b>\nالحالي: <code>{balance:,.2f}</code> USD\nربح/خسارة: <code>{(balance - initial):+,.2f}</code> USD"
        await send_photo(chart_path, caption)
    else:
        await update.effective_message.reply_text("❌ فشل انشاء الرسم")

@require_auth
async def cmd_atr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        atr = db["atr_data"]["current"]
        threshold = db["atr_data"]["threshold"]
    status = "🟢 طبيعي" if atr <= threshold else "🔴 مرتفع"
    await update.effective_message.reply_text(f"⚡ <b>ATR</b>\nالحالي: {atr:.2f}\nالحد: {threshold}\nالحالة: {status}", parse_mode="HTML")

@require_auth
async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        errors = db["api_errors"][-10:]
    if not errors:
        await update.effective_message.reply_text("✅ لا اخطاء")
        return
    msg = "🔍 <b>آخر 10 اخطاء:</b>\n\n"
    for i, err in enumerate(errors, 1):
        msg += f"{i}. [{err['time']}] {err['type']}: {err['error'][:60]}\n"
    await update.effective_message.reply_text(msg, parse_mode="HTML")



@require_auth
async def cmd_force_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_weekend():
        await update.effective_message.reply_text(
            "🛑 <b>عطلة نهاية الاسبوع!</b>\n\n"
            "⏸️ السوق مغلق اليوم (السبت/الاحد)\n"
            "📅 سيتم استئناف التحليل يوم الاثنين\n"
            "🕐 الجلسة الاولى: لندن 07:00 UTC",
            parse_mode="HTML"
        )
        return
    await update.effective_message.reply_text("🔄 <b>جاري التحليل الفوري...</b>", parse_mode="HTML")
    try:
        tf_data = await fetch_all_tf()
        dxy_price = await fetch_dxy_price()
        missing = [k for k, v in tf_data.items() if not v]
        if missing:
            await update.effective_message.reply_text(f"⚠️ بيانات ناقصة: {', '.join(missing)}")
            return

        signal, consensus_status, consensus_confidence = await consensus_analysis(tf_data, dxy_price)

        if signal is None:
            if consensus_status == "DISAGREEMENT":
                await update.effective_message.reply_text("❌ <b>خلاف بين النماذج</b>\nالقرار: HOLD\nانتظر فرصة أوضح", parse_mode="HTML")
            else:
                await update.effective_message.reply_text("❌ <b>خطأ في التحليل</b>\nحاول مرة أخرى", parse_mode="HTML")
            return

        async with db_lock:
            db["analysis_count"] += 1
            db["signals"].append({"text": signal.summary, "time": now_str(), "forced": True})
            if signal.decision == "HOLD": db["last_hold_reason"] = signal.summary[:300]

        emoji = "🟢" if signal.decision == "BUY" else "🔴" if signal.decision == "SELL" else "⏸️"

        if signal.decision in ["BUY", "SELL"] and signal.confidence >= MIN_CONFIDENCE:
            signal_id = f"sig_{int(time.time())}"
            async with db_lock:
                db["pending_signals"][signal_id] = {
                    "signal": signal.to_dict(),
                    "timestamp": time.time(),
                    "status": "pending",
                    "user_status": {}
                }

            await save_signal(signal_id, signal.to_dict(), signal.summary)

            await broadcast_signal_to_users(
                signal_id,
                f"{emoji} <b>إشارة {signal.decision} (ثقة {signal.confidence}%)</b>\n\n"
                f"📊 <b>التفاصيل:</b>\n"
                f"السعر المقترح: {signal.entry_price:,.2f}\n"
                f"🛑 SL: {signal.sl_pips:.1f} نقاط\n"
                f"🎯 TP1: {signal.tp1_pips:.1f} نقاط\n"
                f"🎯🎯 TP2: {signal.tp2_pips:.1f} نقاط\n"
                f"⚖️ RR: {signal.rr}\n"
                f"⏱️ المدة: {signal.duration}\n\n"
                f"💡 <b>ملخص:</b> {signal.summary}\n\n"
                f"⚠️ <b>اضغط على الزر للتأكيد</b>"
            )
        else:
            await send_msg(f"{emoji} <b>تحليل فوري ({signal.decision} - ثقة {signal.confidence}%)</b>\n\n{signal.summary}")

    except Exception as e:
        await update.effective_message.reply_text(f"❌ <b>خطأ:</b>\n{str(e)}")

@require_auth
async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    account = await get_user_account(user_id)
    if context.args:
        try:
            new_risk = float(context.args[0])
            if 0.1 <= new_risk <= 5.0:
                account["risk_percent"] = new_risk
                await save_user_account(user_id, account)
                await update.effective_message.reply_text(f"✅ <b>تم التعديل:</b> <code>{new_risk}%</code>", parse_mode="HTML")
            else:
                await update.effective_message.reply_text("❌ بين 0.1% و 5.0%", parse_mode="HTML")
        except ValueError:
            await update.effective_message.reply_text("❌ استخدم: /risk 1.5", parse_mode="HTML")
    else:
        await update.effective_message.reply_text(f"📊 مخاطرتك: <code>{account['risk_percent']}%</code>", parse_mode="HTML")

_awaiting_balance_input = set()  # user_ids currently being asked "كم رصيدك؟"

async def _apply_new_balance(user_id: str, new_balance: float):
    account = await get_user_account(user_id)
    account["balance"] = new_balance
    account["initial_balance"] = new_balance
    account["equity_history"] = [{"date": datetime.now(timezone.utc).isoformat(), "balance": new_balance}]
    await save_user_account(user_id, account)

async def _start_balance_flow(message, user_id: str):
    account = await get_user_account(user_id)
    if account["active_trade"]:
        await message.reply_text("⚠️ لا يمكن تغيير الرصيد وعندك صفقة نشطة. أغلقها أولاً.")
        return
    _awaiting_balance_input.add(user_id)
    await message.reply_text(
        f"💵 رصيدك الحالي: <code>{account['balance']:,.2f}</code> USD\n\n"
        "كم رصيدك الجديد؟ اكتب الرقم فقط (مثال: 5000)",
        parse_mode="HTML"
    )

@require_auth
async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        await _start_balance_flow(update.effective_message, user_id)
        return
    try:
        new_balance = float(context.args[0])
        if new_balance <= 0:
            await update.effective_message.reply_text("❌ الرصيد يجب أن يكون أكبر من صفر.")
            return
    except ValueError:
        await update.effective_message.reply_text("❌ استخدم: /setbalance 5000", parse_mode="HTML")
        return

    account = await get_user_account(user_id)
    if account["active_trade"]:
        await update.effective_message.reply_text("⚠️ لا يمكن تغيير الرصيد وعندك صفقة نشطة. أغلقها أولاً.")
        return

    await _apply_new_balance(user_id, new_balance)
    await update.effective_message.reply_text(
        f"✅ <b>تم تحديد رصيدك:</b> <code>{new_balance:,.2f}</code> USD",
        parse_mode="HTML"
    )

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in _awaiting_balance_input:
        return
    if not is_authorized(user_id):
        return
    text = (update.effective_message.text or "").strip().replace(",", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("❌ اكتب رقم صحيح أكبر من صفر (مثال: 5000)")
        return

    _awaiting_balance_input.discard(user_id)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ حفظ", callback_data=f"confirmbalance_{amount}"),
        InlineKeyboardButton("❌ إلغاء", callback_data="cancelbalance"),
    ]])
    await update.effective_message.reply_text(
        f"تأكيد: رصيدك الجديد <code>{amount:,.2f}</code> USD؟",
        parse_mode="HTML", reply_markup=keyboard
    )

@require_auth
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock: db["paused"] = True
    await save_state()
    await update.effective_message.reply_text("⏸️ <b>تم الايقاف</b>", parse_mode="HTML")

@require_auth
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock: db["paused"] = False
    await save_state()
    await update.effective_message.reply_text("▶️ <b>تم الاستئناف</b>", parse_mode="HTML")

@require_auth
async def cmd_resetapi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id) if update.effective_user else None
    if not is_admin(user_id):
        await update.effective_message.reply_text("⛔ هذا الامر للمشرف فقط.")
        return
    async with db_lock:
        was_paused = db["twelvedata_paused_until"] > time.time()
        db["twelvedata_paused_until"] = 0
        db["twelvedata_pause_notified"] = False
    await save_state()
    if was_paused:
        await update.effective_message.reply_text(
            "✅ <b>تم رفع الإيقاف عن TwelveData</b>\n\nالبوت سيحاول جلب الأسعار من جديد بالدورة القادمة.",
            parse_mode="HTML"
        )
    else:
        await update.effective_message.reply_text("ℹ️ لا يوجد إيقاف فعّال حاليًا على TwelveData.")

@require_auth
async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock: news_list = db["upcoming_news"][:5]
    if not news_list:
        await update.effective_message.reply_text("📰 لا توجد اخبار عاجلة قادمة")
        return
    msg = "📰 <b>الاخبار القادمة:</b>\n\n"
    for news in news_list:
        minutes = news["minutes_until"]
        if minutes > 0: time_str = f"خلال {int(minutes)} دقيقة"
        elif minutes > -60: time_str = "جارية الان!"
        else: time_str = "انتهت"
        msg += f"• <b>{news['title']}</b>\n  ⏰ {time_str} ({news['time'].strftime('%H:%M')} UTC)\n\n"
    await update.effective_message.reply_text(msg, parse_mode="HTML")

@require_auth
async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    trades = await get_user_trades(user_id, limit=20)
    if not trades:
        await update.effective_message.reply_text("📋 لا توجد صفقات مغلقة بعد")
        return
    msg = f"📋 <b>صفقاتك المغلقة ({len(trades)}):</b>\n\n"
    for i, t in enumerate(trades, 1):
        result_emoji = "✅" if t.get("result") == "win" else "❌"
        msg += f"{i}. {result_emoji} <b>{t['direction']}</b> @ {t['entry_price']:,.2f}\n   الخروج: {t['exit_price']:,.2f} | النتيجة: {t['pnl_pips']:+.1f} نقاط ({t.get('pnl_usd', 0):+.2f}$)\n   الثقة: {t.get('confidence', 'N/A')}% | {t['close_time']}\n\n"
    await update.effective_message.reply_text(msg, parse_mode="HTML")

@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🤖 <b>الاوامر</b>\n"
        "/start - القائمة\n"
        "/status - الحالة\n"
        "/price - الاسعار\n"
        "/signal - آخر اشارة\n"
        "/stats - الاحصائيات\n"
        "/trades - الصفقات المغلقة\n"
        "/weekly - اسبوعي\n"
        "/monthly - شهري\n"
        "/equity - رسم بياني\n"
        "/atr - ATR\n"
        "/errors - الاخطاء\n"
        "/force - تحليل فوري\n"
        "/news - الاخبار القادمة\n"
        "/risk - المخاطرة\n"
        "/setbalance - تحديد الرصيد\n"
        "/pause - ايقاف\n"
        "/resume - استئناف",
        parse_mode="HTML"
    )



@require_auth
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    async with db_lock:
        last_press = db.get("last_button_press", 0)
        if time.time() - last_press < 2:
            await query.answer("⏳ يرجى الانتظار...")
            return
        db["last_button_press"] = time.time()
    await query.answer()

    data = query.data

    # معالجة أزرار تأكيد الصفقات (كل مستخدم يقرر لحاله على حسابه الخاص)
    if data.startswith("accept_") or data.startswith("reject_"):
        is_accept = data.startswith("accept_")
        payload = data[len("accept_"):] if is_accept else data[len("reject_"):]
        parts = payload.rsplit("_", 1)
        if len(parts) != 2:
            await query.edit_message_text("⚠️ زر غير صالح")
            return
        signal_id, target_uid = parts
        clicking_uid = str(query.from_user.id)
        if clicking_uid != target_uid:
            await query.answer("⛔ هذا الزر ليس لك", show_alert=True)
            return

        async with db_lock:
            if signal_id not in db["pending_signals"]:
                try:
                    await query.edit_message_text("⏳ الإشارة منتهية الصلاحية")
                except Exception:
                    pass
                return
            signal_data = db["pending_signals"][signal_id]
            signal_dict = signal_data["signal"]
            already = signal_data["user_status"].get(clicking_uid)

        if already:
            await query.answer("✅ سبق وحسمت قرارك بهذي الإشارة", show_alert=True)
            return

        if not is_accept:
            async with db_lock:
                db["pending_signals"][signal_id]["user_status"][clicking_uid] = "rejected"
            await query.edit_message_text("❌ <b>تم تجاهل الإشارة</b>")
            return

        account = await get_user_account(clicking_uid)
        if account["active_trade"]:
            await query.answer("⚠️ عندك صفقة نشطة بالفعل - أغلقها أولاً", show_alert=True)
            return

        lot_size = calculate_lot_size(account["balance"], account["risk_percent"], signal_dict["sl_pips"])
        account["active_trade"] = {
            "direction": signal_dict["decision"],
            "entry_price": signal_dict["entry_price"],
            "sl_pips": signal_dict["sl_pips"],
            "tp1_pips": signal_dict["tp1_pips"],
            "tp2_pips": signal_dict["tp2_pips"],
            "rr": signal_dict["rr"],
            "duration": signal_dict["duration"],
            "confidence": signal_dict["confidence"],
            "analysis": signal_dict["summary"],
            "open_time": time.time(),
            "tp1_notified": False,
            "lot_size": lot_size,
            "last_update": time.time(),
            "high_pnl": 0,
            "low_pnl": 0,
        }
        await save_user_account(clicking_uid, account)

        async with db_lock:
            db["pending_signals"][signal_id]["user_status"][clicking_uid] = "accepted"

        await query.edit_message_text(
            f"✅ <b>صفقة نشطة الآن!</b>\n\n"
            f"{signal_dict['decision']} @ {signal_dict['entry_price']:,.2f}\n"
            f"🛑 SL: {signal_dict['sl_pips']:.1f} نقاط\n"
            f"🎯 TP1: {signal_dict['tp1_pips']:.1f} نقاط\n"
            f"🎯🎯 TP2: {signal_dict['tp2_pips']:.1f} نقاط\n"
            f"⚖️ RR: {signal_dict['rr']}\n"
            f"⏱️ المدة: {signal_dict['duration']}\n"
            f"📦 حجم اللوت: {lot_size} (حسب رصيدك ومخاطرتك)"
        )
        return

    if data == "force_analysis" and is_weekend():
        await query.message.reply_text(
            "🛑 <b>عطلة نهاية الاسبوع!</b>\n\n"
            "⏸️ السوق مغلق اليوم (السبت/الاحد)\n"
            "📅 سيتم استئناف التحليل يوم الاثنين\n"
            "🕐 الجلسة الاولى: لندن 07:00 UTC",
            parse_mode="HTML"
        )
        return

    handlers = {
        "status": cmd_status, "price": cmd_price, "signal": cmd_signal,
        "stats": cmd_stats, "weekly": cmd_weekly, "monthly": cmd_monthly,
        "equity_chart": cmd_equity_chart, "atr": cmd_atr,
        "errors": cmd_errors, "menu_start": cmd_start, "help_cmd": cmd_help,
    }
    if data in handlers:
        try:
            await handlers[data](update, context)
        except Exception as e:
            print(f"❌ خطأ زر {data}: {e}")
            await query.message.reply_text(f"❌ خطأ في تنفيذ الامر: {str(e)[:100]}")
    elif data == "pause":
        async with db_lock: db["paused"] = True
        await save_state()
        await query.message.reply_text("⏸️ تم الايقاف")
    elif data == "resume":
        async with db_lock: db["paused"] = False
        await save_state()
        await query.message.reply_text("▶️ تم الاستئناف")
    elif data == "menu_setbalance":
        await _start_balance_flow(query.message, str(query.from_user.id))
    elif data.startswith("confirmbalance_"):
        user_id = str(query.from_user.id)
        try:
            amount = float(data.replace("confirmbalance_", ""))
        except ValueError:
            await query.edit_message_text("❌ حدث خطأ، حاول من جديد.")
            return
        account = await get_user_account(user_id)
        if account["active_trade"]:
            await query.edit_message_text("⚠️ عندك صفقة نشطة الآن، ما تقدر تغيّر الرصيد. أغلقها أولاً.")
            return
        await _apply_new_balance(user_id, amount)
        await query.edit_message_text(f"✅ <b>تم حفظ رصيدك:</b> <code>{amount:,.2f}</code> USD", parse_mode="HTML")
    elif data == "cancelbalance":
        await query.edit_message_text("❌ تم الإلغاء - رصيدك لم يتغيّر.")

async def _monitor_one_user_trade(uid: str, current_price: float):
    account = await get_user_account(uid)
    trade = account["active_trade"]
    if not trade:
        return

    direction = trade.get("direction", "")
    entry = trade.get("entry_price", 0)
    sl_pips = trade.get("sl_pips", 0)
    tp1_pips = trade.get("tp1_pips", 0)
    tp2_pips = trade.get("tp2_pips", 0)
    confidence = trade.get("confidence", 0)
    lot_size = trade.get("lot_size", 0.01)
    if entry == 0:
        return

    pnl_pips, _ = calculate_pnl(direction, entry, current_price)
    pnl_usd = calculate_pnl_usd(pnl_pips, lot_size)

    trade["high_pnl"] = max(trade.get("high_pnl", 0), pnl_pips)
    trade["low_pnl"] = min(trade.get("low_pnl", 0), pnl_pips)

    reached_tp1 = tp1_pips > 0 and pnl_pips >= tp1_pips
    reached_tp2 = tp2_pips > 0 and pnl_pips >= tp2_pips
    hit_sl = sl_pips > 0 and pnl_pips <= -sl_pips

    last_update = trade.get("last_update", trade.get("open_time", time.time()))
    time_since_update = time.time() - last_update
    should_notify = False
    notify_msg = ""
    closed = False

    def _close(result: str, msg: str):
        nonlocal closed, notify_msg, should_notify
        account["stats"]["wins" if result == "win" else "losses"] += 1
        account["stats"]["total_pips"] += pnl_pips
        account["balance"] += pnl_usd
        account["equity_history"].append({"date": datetime.now(timezone.utc).isoformat(), "balance": account["balance"]})
        trade_data = {
            "direction": direction, "entry_price": entry, "exit_price": current_price,
            "pnl_pips": pnl_pips, "pnl_usd": pnl_usd, "result": result, "confidence": confidence,
            "open_time": trade.get("open_time", time.time()), "close_time": now_str(),
            "sl_pips": sl_pips, "tp1_pips": tp1_pips, "tp2_pips": tp2_pips,
            "rr": trade.get("rr", ""), "duration": trade.get("duration", ""), "lot_size": lot_size,
        }
        account["active_trade"] = None
        closed = True
        notify_msg = msg
        should_notify = True
        asyncio.ensure_future(add_user_trade_record(uid, trade_data))

    if hit_sl:
        _close("loss", f"🔴 <b>تم اغلاق الصفقة - وقف الخسارة</b>\n\n{direction} @ {entry:,.2f}\nالخروج: {current_price:,.2f}\nالخسارة: {pnl_pips:+.1f} نقاط ({pnl_usd:+.2f}$) 😔")
    elif reached_tp2:
        _close("win", f"🎯🎯 <b>تم اغلاق الصفقة - الهدف الثاني!</b>\n\n{direction} @ {entry:,.2f}\nالخروج: {current_price:,.2f}\nالربح: {pnl_pips:+.1f} نقاط ({pnl_usd:+.2f}$) 🎉🎉")
    elif reached_tp1 and not trade.get("tp1_notified", False):
        trade["tp1_notified"] = True
        trade["last_update"] = time.time()
        notify_msg = f"🎯 <b>الهدف الاول تم الوصول!</b>\n\n{direction} @ {entry:,.2f}\nالسعر الحالي: {current_price:,.2f}\nالربح: {pnl_pips:+.1f} نقاط ({pnl_usd:+.2f}$)\n\n💡 يمكنك:\n• نقل SL لنقطة الدخول (Break Even)\n• الانتظار للهدف الثاني: {tp2_pips:.1f} نقاط"
        should_notify = True
    elif time_since_update > 300:
        trade["last_update"] = time.time()
        high, low = trade.get("high_pnl", 0), trade.get("low_pnl", 0)
        status_emoji = "🟢" if pnl_pips > 0 else "🔴" if pnl_pips < 0 else "⚪"
        notify_msg = f"{status_emoji} <b>تحديث الصفقة</b>\n\n{direction} @ {entry:,.2f}\nالسعر: {current_price:,.2f}\nالربح: {pnl_pips:+.1f} نقاط ({pnl_usd:+.2f}$)\n📈 اعلى: {high:+.1f} | 📉 ادنى: {low:+.1f}\n🎯 TP1: {tp1_pips:.1f} | 🎯🎯 TP2: {tp2_pips:.1f} | 🛑 SL: {sl_pips:.1f}"
        should_notify = True

    if not closed:
        account["active_trade"] = trade
    await save_user_account(uid, account)

    if should_notify and notify_msg:
        await _send_raw(uid, notify_msg)


async def trade_monitor_coro():
    while True:
        try:
            async with db_lock:
                paused = db["paused"]
            if paused:
                await asyncio.sleep(5)
                continue

            user_ids = await get_all_authorized_user_ids()
            active_uids = []
            for uid in user_ids:
                account = await get_user_account(uid)
                if account["active_trade"]:
                    active_uids.append(uid)

            if not active_uids:
                await asyncio.sleep(TRADE_MONITOR_INTERVAL)
                continue

            current_price = await fetch_price()
            for uid in active_uids:
                try:
                    await _monitor_one_user_trade(uid, current_price)
                except Exception as e:
                    print(f"❌ خطأ trade_monitor للمستخدم {uid}: {e}")

            await asyncio.sleep(TRADE_MONITOR_INTERVAL)
        except Exception as e:
            print(f"❌ خطأ trade_monitor: {e}")
            await asyncio.sleep(TRADE_MONITOR_INTERVAL)



async def opportunity_analyzer_coro():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(5)
                    continue
                last_analysis = db["last_analysis_ts"]
                last_price = db["last_sent_price"]
                last_session = db["last_session_analysis"]

            if is_weekend():
                await asyncio.sleep(300)
                continue
            if await is_news_blocking():
                await asyncio.sleep(60)
                continue
            if not is_active_trading_session():
                await asyncio.sleep(180)
                continue

            current_session = get_session_name()
            current_price = await fetch_price()

            async with db_lock:
                dxy_stale = (time.time() - db["dxy_price_last_fetch"]) >= 300
            if dxy_stale:
                current_dxy = await fetch_dxy_price()
                async with db_lock:
                    db["dxy_price_last_fetch"] = time.time()
            else:
                async with db_lock:
                    current_dxy = db["dxy_price"]
            should_analyze = False
            reason = ""

            if last_price > 0:
                price_diff_pips = abs(current_price - last_price) / GOLD_PIP_VALUE
                if price_diff_pips >= SIGNIFICANT_MOVE_PIPS:
                    should_analyze = True 
