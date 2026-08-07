"""
Gold Scalp AI Monitor v5.3 - Railway Edition (Twelve Data Primary)
========================================================================
- أوامر Telegram تفاعلية
- مصدر رئيسي: Twelve Data (API Key جديد)
- إحصائيات وقاعدة بيانات في الذاكرة
- تقرير يومي
- تحكم كامل من الجوال
- جلسات لندن، نيويورك، طوكيو، سيدني
- تخصيص نسبة المخاطرة
- إشعار قبل الأخبار العاجلة
"""



enhanced_code = '''import os
import json
import asyncio
import aiohttp
import time
import math
import re
import xml.etree.ElementTree as ET
import traceback
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ============ الإعدادات ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SYMBOL = "XAU/USD"
DXY_SYMBOL = "DXY"
MONITOR_INTERVAL = 15
ANALYSIS_INTERVAL = 180  # 3 دقائق
MIN_CONFIDENCE = 70
GEMINI_MODEL = "gemini-1.5-flash"
PIP_VALUE = 1.0

TIMEFRAMES = {
    "M30": "30min",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}

# ============ الجلسات ============
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

# ============ قاعدة البيانات في الذاكرة ============
db = {
    "trades": [],
    "signals": [],
    "stats": {"wins": 0, "losses": 0, "total_pips": 0, "daily_pips": {}, "weekly_pips": {}, "monthly_pips": {}},
    "paused": False,
    "active_trade": None,
    "last_analysis_ts": 0,
    "risk_percent": 1.0,
    "news_blocked_until": 0,
    "last_price": 2650.0,
    "dxy_price": 103.0,
    "session_notified": {},
    "atr_data": {"current": 0, "threshold": 15.0, "last_alert": 0},
    "equity_history": [],
    "initial_balance": 10000.0,
    "current_balance": 10000.0,
    "analysis_count": 0,
    "last_hold_reason": "",
    "api_errors": [],
    "bot_start_time": time.time(),
}
db_lock = asyncio.Lock()

# ============ البرومبت ============
GOLD_SCALP_PROMPT = """
أنت رئيس المحللين الفنيين ومدير المخاطر في صندوق استثماري عالمي. مهمتك تحليل بيانات الشموع الفعلية لأربع فريمات (M30, M15, M5, M1) وإصدار قرار تداول حاسم.

⚠️ [نمط التشغيل: صفقات الزخم المتوسطة - 20-30 دقيقة]

بيانات الشموع (الأحدث أولاً):

== M30 ==
{data_m30}

== M15 ==
{data_m15}

== M5 ==
{data_m5}

== M1 ==
{data_m1}

== DXY ==
سعر DXY: {dxy_price}

---

### تعليمات حاسمة:
- إذا كانت هناك فرصة واضحة (BUY أو SELL) مع نسبة ثقة 70%+، أصدر الإشارة فوراً.
- إذا لم تكن هناك فرصة واضحة، أرجع HOLD مع ذكر السبب المحدد.
- لا تُرجع HOLD افتراضياً - حلل البيانات فعلياً.
- DXY يرتفع = الذهب ينخفض (عكسي)، DXY ينخفض = الذهب يرتفع.

### صيغة المخرج (نص عادي فقط):
القرار النهائي: [BUY / SELL / HOLD]
نسبة الثقة: [رقم من 0-100]
سعر الدخول: [رقم]
وقف الخسارة نقاط: [رقم]
الهدف الأول نقاط: [رقم]
الهدف الثاني نقاط: [رقم]
نسبة العائد للمخاطرة: [مثال 1:3]
المخاطرة الموصى بها: [نسبة]
المدة المتوقعة: [مثال 20-30 mins]
حالة الجلسة: [اسم الجلسة]
تفاصيل أصوات الوكلاء: [قائمة مختصرة]
ملخص تنفيذي: [ملخص بالعربية]
"""


# ============ دوال مساعدة ============
def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def is_valid_session():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    in_london = LONDON_SESSION[0] <= hour < LONDON_SESSION[1]
    in_ny = NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]
    in_tokyo = TOKYO_SESSION[0] <= hour < TOKYO_SESSION[1]
    in_sydney = hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1]
    return in_london or in_ny or in_tokyo or in_sydney


def get_session_name():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    if LONDON_SESSION[0] <= hour < LONDON_SESSION[1]:
        return "لندن 🇬🇧"
    elif NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]:
        return "نيويورك 🇺🇸"
    elif TOKYO_SESSION[0] <= hour < TOKYO_SESSION[1]:
        return "طوكيو 🇯🇵"
    elif hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1]:
        return "سيدني 🇦🇺"
    return "خارج الجلسات ⏸️"


def get_all_active_sessions():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    active = []
    if LONDON_SESSION[0] <= hour < LONDON_SESSION[1]:
        active.append("لندن 🇬🇧")
    if NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]:
        active.append("نيويورك 🇺🇸")
    if TOKYO_SESSION[0] <= hour < TOKYO_SESSION[1]:
        active.append("طوكيو 🇯🇵")
    if hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1]:
        active.append("سيدني 🇦🇺")
    return active


def parse_signal_decision(text: str):
    """استخراج القرار ونسبة الثقة من نص التحليل"""
    decision = "HOLD"
    confidence = 0
    
    text_upper = text.upper()
    if "القرار النهائي:" in text:
        line = text.split("القرار النهائي:")[1].split("\\n")[0].strip().upper()
        if "BUY" in line:
            decision = "BUY"
        elif "SELL" in line:
            decision = "SELL"
    elif "BUY" in text_upper and "SELL" not in text_upper.split("BUY")[0].split("\\n")[-1]:
        decision = "BUY"
    elif "SELL" in text_upper:
        decision = "SELL"
    
    if "نسبة الثقة:" in text:
        try:
            conf_line = text.split("نسبة الثقة:")[1].split("\\n")[0].strip()
            numbers = re.findall(r'\\d+', conf_line)
            if numbers:
                confidence = int(numbers[0])
        except:
            pass
    
    return decision, confidence


# ============ دوال الـ API ============
async def send_msg(text: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
    except Exception as e:
        print(f"❌ فشل إرسال Telegram: {e}")


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
        print(f"❌ فشل إرسال صورة: {e}")


async def fetch_tf(interval: str, symbol: str = SYMBOL):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": 20,
            "apikey": TWELVE_DATA_API_KEY
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                
                if "code" in data and data["code"] != 200:
                    print(f"⚠️ Twelve Data خطأ {interval}: {data.get('message', 'unknown')}")
                    return {}
                
                if "values" in data and data["values"]:
                    candles = data["values"]
                    current_close = float(candles[0]["close"])
                    async with db_lock:
                        if symbol == SYMBOL:
                            db["last_price"] = current_close
                        elif symbol == DXY_SYMBOL:
                            db["dxy_price"] = current_close
                    return candles
                else:
                    print(f"⚠️ Twelve Data: لا بيانات {interval}")
                    return {}
                    
    except Exception as e:
        print(f"❌ استثناء fetch_tf {interval}: {e}")
        return {}


async def fetch_price():
    await fetch_tf("1min")
    async with db_lock:
        return db["last_price"]


async def fetch_dxy_price():
    await fetch_tf("1min", DXY_SYMBOL)
    async with db_lock:
        return db["dxy_price"]


async def fetch_all_tf():
    result = {}
    for label, interval in TIMEFRAMES.items():
        try:
            data = await fetch_tf(interval)
            if data:
                result[label] = data
            else:
                result[label] = {}
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"❌ فشل جلب {label}: {e}")
            result[label] = {}
    return result


async def analyze_gemini(tf_data: dict, dxy_price: float):
    try:
        prompt = GOLD_SCALP_PROMPT.format(
            data_m30=json.dumps(tf_data.get("M30", {}))[:2000],
            data_m15=json.dumps(tf_data.get("M15", {}))[:2000],
            data_m5=json.dumps(tf_data.get("M5", {}))[:2000],
            data_m1=json.dumps(tf_data.get("M1", {}))[:2000],
            dxy_price=dxy_price,
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 4000, "temperature": 0.3}
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                result = await resp.json()
                
                if "error" in result:
                    err = result["error"].get("message", "Unknown")
                    print(f"❌ Gemini API خطأ: {err}")
                    return f"ERROR: {err}"
                
                if "candidates" not in result or not result["candidates"]:
                    print("❌ Gemini: لا candidates")
                    return "ERROR: No candidates"
                
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
                
    except Exception as e:
        print(f"❌ استثناء Gemini: {e}")
        return f"ERROR: {str(e)}"


# ============ حساب ATR ============
async def calculate_atr(candles: list, period: int = 14):
    if len(candles) < period + 1:
        return 0.0
    tr_values = []
    for i in range(1, len(candles)):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i-1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
    if len(tr_values) < period:
        return sum(tr_values) / len(tr_values) if tr_values else 0.0
    return sum(tr_values[-period:]) / period


# ============ الأخبار ============
async def fetch_forex_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                xml_data = await resp.text()
                root = ET.fromstring(xml_data)
                news_list = []
                now = datetime.now(timezone.utc)
                for event in root.findall('event'):
                    try:
                        currency = event.find('country').text
                        impact = event.find('impact').text
                        time_str = event.find('date').text + ' ' + event.find('time').text
                        event_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        if currency == 'USD' and impact == 'High':
                            minutes_until = (event_time - now).total_seconds() / 60
                            news_list.append({'title': event.find('title').text, 'time': event_time, 'minutes_until': minutes_until})
                    except:
                        continue
                return news_list
    except Exception as e:
        print(f"⚠️ فشل جلب الأخبار: {e}")
        return []


async def check_news_and_block():
    try:
        news_list = await fetch_forex_news()
        now = time.time()
        blocking = []
        for news in news_list:
            if -30 <= news['minutes_until'] <= 20:
                block_until = now + (news['minutes_until'] + 30) * 60
                async with db_lock:
                    db["news_blocked_until"] = block_until
                blocking.append(news)
        if blocking:
            titles = "\\n".join([f"• {n['title']}" for n in blocking[:3]])
            await send_msg(f"🔴 <b>توقف بسبب أخبار:</b>\\n{titles}")
            return True
        async with db_lock:
            if db["news_blocked_until"] > 0 and now > db["news_blocked_until"]:
                db["news_blocked_until"] = 0
        return False
    except Exception as e:
        return False


# ============ إشعارات الجلسات ============
async def session_notification_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            current_minute = now.minute
            
            for session_name, config in SESSIONS_CONFIG.items():
                start_h = config["start"]
                end_h = config["end"]
                today_key = now.strftime("%Y%m%d")
                start_key = f"{session_name}_start_{today_key}"
                end_key = f"{session_name}_end_{today_key}"
                
                if current_hour == start_h and current_minute == 0:
                    async with db_lock:
                        if not db["session_notified"].get(start_key, False):
                            db["session_notified"][start_key] = True
                            await send_msg(f"🟢 <b>جلسة {session_name} بدأت!</b>\\n\\nالسوق نشط الآن! 🚀")
                
                if current_hour == end_h and current_minute == 59:
                    async with db_lock:
                        if not db["session_notified"].get(end_key, False):
                            db["session_notified"][end_key] = True
                            await send_msg(f"🔴 <b>جلسة {session_name} انتهت</b>\\n\\nانتظر الجلسة القادمة! ⏸️")
            
            async with db_lock:
                two_days_ago = (now - timedelta(days=2)).strftime("%Y%m%d")
                for k in list(db["session_notified"].keys()):
                    if k.endswith(two_days_ago):
                        del db["session_notified"][k]
            
            await asyncio.sleep(30)
        except Exception as e:
            print(f"❌ خطأ session_notification: {e}")
            await asyncio.sleep(30)


# ============ ATR تنبيه ============
async def atr_alert_loop():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(60)
                    continue
            
            candles = await fetch_tf("15min")
            if candles and len(candles) > 15:
                atr = await calculate_atr(candles, 14)
                async with db_lock:
                    db["atr_data"]["current"] = atr
                    threshold = db["atr_data"]["threshold"]
                    last_alert = db["atr_data"]["last_alert"]
                
                if atr > threshold and (time.time() - last_alert) > 1800:
                    await send_msg(f"⚡ <b>تذبذب عالي!</b>\\nATR: {atr:.2f} نقاط\\nانتبه للمخاطر! 🚨")
                    async with db_lock:
                        db["atr_data"]["last_alert"] = time.time()
            
            await asyncio.sleep(300)
        except Exception as e:
            print(f"❌ خطأ ATR: {e}")
            await asyncio.sleep(300)


# ============ ملخص الأداء ============
async def generate_performance_summary(period: str = "weekly"):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        now = datetime.now(timezone.utc)
        
        if period == "weekly":
            period_name = "أسبوعي"
            pips_data = stats.get("weekly_pips", {})
        elif period == "monthly":
            period_name = "شهري"
            pips_data = stats.get("monthly_pips", {})
        else:
            period_name = "يومي"
            pips_data = stats.get("daily_pips", {})
        
        period_pips = sum(pips_data.values()) if pips_data else stats["total_pips"]
        
        return f"""
📊 <b>ملخص الأداء {period_name}</b>
📈 الصفقات: {total} | ✅ {stats["wins"]} | ❌ {stats["losses"]}
📉 نسبة الربح: {win_rate:.1f}%
💰 النقاط: {stats["total_pips"]:+.1f} | الفترة: {period_pips:+.1f}
⚖️ المخاطرة: {db["risk_percent"]}%
💵 الرصيد: {db["current_balance"]:,.2f} USD
📈 ربح/خسارة: {(db["current_balance"] - db["initial_balance"]):+,.2f} USD
        """


# ============ رسم بياني ============
async def generate_equity_chart():
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        
        async with db_lock:
            history = db["equity_history"].copy()
            initial = db["initial_balance"]
        
        if len(history) < 2:
            dates = [datetime.now(timezone.utc) - timedelta(days=i) for i in range(7, 0, -1)]
            balances = [initial + (i * 50) for i in range(7)]
        else:
            dates = [h["date"] for h in history]
            balances = [h["balance"] for h in history]
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(dates, balances, linewidth=2, color='#00D26A', marker='o', markersize=4)
        ax.fill_between(dates, balances, initial, alpha=0.3, color='#00D26A')
        ax.axhline(y=initial, color='gray', linestyle='--', alpha=0.5, label='الرصيد الابتدائي')
        ax.set_title('📈 نمو الرصيد', fontsize=16, fontweight='bold', color='white')
        ax.set_xlabel('التاريخ', fontsize=12, color='white')
        ax.set_ylabel('الرصيد (USD)', fontsize=12, color='white')
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax.xaxis.set_major_locator(mdates.DayLocator())
        plt.xticks(rotation=45)
        fig.patch.set_facecolor('#1a1a2e')
        ax.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white')
        for spine in ax.spines.values():
            spine.set_color('white')
        plt.tight_layout()
        chart_path = "/tmp/equity_chart.png"
        plt.savefig(chart_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
        plt.close()
        return chart_path
    except Exception as e:
        print(f"❌ خطأ رسم بياني: {e}")
        return None


# ============ أوامر Telegram ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 الحالة", callback_data="status"),
         InlineKeyboardButton("💵 السعر", callback_data="price")],
        [InlineKeyboardButton("📈 الإشارة", callback_data="signal"),
         InlineKeyboardButton("📉 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📊 أسبوعي", callback_data="weekly"),
         InlineKeyboardButton("📊 شهري", callback_data="monthly")],
        [InlineKeyboardButton("📈 رسم الرصيد", callback_data="equity_chart"),
         InlineKeyboardButton("⚡ ATR", callback_data="atr")],
        [InlineKeyboardButton("🔍 أخطاء", callback_data="errors"),
         InlineKeyboardButton("🔄 تحليل فوري", callback_data="force_analysis")],
        [InlineKeyboardButton("⏸️ إيقاف", callback_data="pause"),
         InlineKeyboardButton("▶️ استئناف", callback_data="resume")],
    ]
    reply = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 <b>بوت الذهب الذكي</b>\\n\\n"
        "✅ الميزات:\\n"
        "• 🟢🔴 إشعارات الجلسات\\n"
        "• 📊 ربط DXY\\n"
        "• 📈 ملخص أسبوعي/شهري\\n"
        "• ⚡ تنبيه ATR\\n"
        "• 📉 رسم بياني\\n"
        "• 🔍 سجل أخطاء\\n"
        "• 🔄 تحليل فوري\\n\\n"
        "اختر خياراً:",
        parse_mode="HTML", reply_markup=reply
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        paused = db["paused"]
        active = db["active_trade"]
        signals_count = len(db["signals"])
        risk = db["risk_percent"]
        blocked = time.time() < db["news_blocked_until"]
        atr_current = db["atr_data"]["current"]
        dxy = db["dxy_price"]
        analysis_count = db["analysis_count"]
        errors_count = len(db["api_errors"])
        uptime = int(time.time() - db["bot_start_time"])
    
    status = "⏸️ متوقف" if paused else "✅ يعمل"
    trade_status = f"صفقة {active['direction']} نشطة" if active else "لا توجد صفقة"
    news_status = "🔴 موقف" if blocked else "🟢 لا أخبار"
    active_sessions = ", ".join(get_all_active_sessions()) or "خارج الجلسات"
    uptime_str = f"{uptime//3600}h {(uptime%3600)//60}m"
    
    msg = f"""
📊 <b>حالة البوت</b>
الحالة: {status}
الجلسات: {active_sessions}
الصفقة: {trade_status}
إشارات: {signals_count} | تحاليل: {analysis_count}
المخاطرة: {risk}% | أخطاء: {errors_count}
الأخبار: {news_status}
ATR: {atr_current:.2f} | DXY: {dxy:.2f}
⏱️ وقت التشغيل: {uptime_str}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = await fetch_price()
        dxy = await fetch_dxy_price()
        msg = f"💵 <b>الأسعار</b>\\n\\n🥇 XAU/USD: <code>{price:,.2f}</code>\\n💵 DXY: <code>{dxy:.2f}</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        if not db["signals"]:
            await update.message.reply_text("⏳ لا توجد إشارات بعد")
            return
        last = db["signals"][-1]
    msg = f"📈 <b>آخر إشارة</b>\\n\\n{last['text']}"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        balance = db["current_balance"]
        initial = db["initial_balance"]
        analysis_count = db["analysis_count"]
    
    msg = f"""
📉 <b>الإحصائيات</b>
الصفقات: {total} | ✅ {stats["wins"]} | ❌ {stats["losses"]}
الربح: {win_rate:.1f}% | النقاط: {stats["total_pips"]:+.1f}
التحاليل: {analysis_count}
💵 الرصيد: {balance:,.2f} USD
📈 ربح/خسارة: {(balance - initial):+,.2f} USD
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await generate_performance_summary("weekly")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await generate_performance_summary("monthly")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_equity_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري إنشاء الرسم...")
    chart_path = await generate_equity_chart()
    if chart_path:
        async with db_lock:
            balance = db["current_balance"]
            initial = db["initial_balance"]
        caption = f"📈 <b>نمو الرصيد</b>\\nالحالي: <code>{balance:,.2f}</code> USD\\nربح/خسارة: <code>{(balance - initial):+,.2f}</code> USD"
        await send_photo(chart_path, caption)
    else:
        await update.message.reply_text("❌ فشل إنشاء الرسم")


async def cmd_atr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        atr = db["atr_data"]["current"]
        threshold = db["atr_data"]["threshold"]
    status = "🟢 طبيعي" if atr <= threshold else "🔴 مرتفع"
    await update.message.reply_text(f"⚡ <b>ATR</b>\\nالحالي: {atr:.2f}\\nالحد: {threshold}\\nالحالة: {status}", parse_mode="HTML")


async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        errors = db["api_errors"][-10:]
    if not errors:
        await update.message.reply_text("✅ لا أخطاء")
        return
    msg = "🔍 <b>آخر 10 أخطاء:</b>\\n\\n"
    for i, err in enumerate(errors, 1):
        msg += f"{i}. [{err['time']}] {err['type']}: {err['error'][:60]}\\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_force_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 <b>جاري التحليل الفوري...</b>", parse_mode="HTML")
    try:
        tf_data = await fetch_all_tf()
        dxy_price = await fetch_dxy_price()
        
        missing = [k for k, v in tf_data.items() if not v]
        if missing:
            await update.message.reply_text(f"⚠️ بيانات ناقصة: {', '.join(missing)}")
            return
        
        analysis_text = await analyze_gemini(tf_data, dxy_price)
        
        if analysis_text.startswith("ERROR"):
            await update.message.reply_text(f"❌ <b>خطأ:</b>\\n{analysis_text}")
            return
        
        decision, confidence = parse_signal_decision(analysis_text)
        
        async with db_lock:
            db["analysis_count"] += 1
            db["signals"].append({"text": analysis_text, "time": now_str(), "forced": True})
            if decision == "HOLD":
                db["last_hold_reason"] = analysis_text[:300]
        
        emoji = "🟢" if decision == "BUY" else "🔴" if decision == "SELL" else "⏸️"
        await send_msg(f"{emoji} <b>تحليل فوري ({decision} - ثقة {confidence}%)</b>\\n\\n{analysis_text}")
        
    except Exception as e:
        await update.message.reply_text(f"❌ <b>خطأ:</b>\\n{str(e)}")


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        current_risk = db["risk_percent"]
    if context.args:
        try:
            new_risk = float(context.args[0])
            if 0.1 <= new_risk <= 5.0:
                async with db_lock:
                    db["risk_percent"] = new_risk
                await update.message.reply_text(f"✅ <b>تم التعديل:</b> <code>{new_risk}%</code>", parse_mode="HTML")
            else:
                await update.message.reply_text("❌ بين 0.1% و 5.0%", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ استخدم: /risk 1.5", parse_mode="HTML")
    else:
        await update.message.reply_text(f"📊 المخاطرة: <code>{current_risk}%</code>", parse_mode="HTML")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = True
    await update.message.reply_text("⏸️ <b>تم الإيقاف</b>", parse_mode="HTML")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = False
    await update.message.reply_text("▶️ <b>تم الاستئناف</b>", parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
🤖 <b>الأوامر</b>
/start - القائمة
/status - الحالة
/price - الأسعار
/signal - آخر إشارة
/stats - الإحصائيات
/weekly - أسبوعي
/monthly - شهري
/equity - رسم بياني
/atr - ATR
/errors - الأخطاء
/force - تحليل فوري
/risk - المخاطرة
/pause - إيقاف
/resume - استئناف
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    handlers = {
        "status": cmd_status, "price": cmd_price, "signal": cmd_signal,
        "stats": cmd_stats, "weekly": cmd_weekly, "monthly": cmd_monthly,
        "equity_chart": cmd_equity_chart, "atr": cmd_atr,
        "errors": cmd_errors, "force_analysis": cmd_force_analysis,
    }
    if query.data in handlers:
        await handlers[query.data](query, context)
    elif query.data == "pause":
        async with db_lock:
            db["paused"] = True
        await query.message.reply_text("⏸️ تم الإيقاف")
    elif query.data == "resume":
        async with db_lock:
            db["paused"] = False
        await query.message.reply_text("▶️ تم الاستئناف")


# ============ الحلقات الرئيسية (محمية بالكامل) ============
async def safe_loop(name: str, coro_func, interval: int = 60):
    """حلقة محمية - إذا تعطلت تعيد التشغيل تلقائياً"""
    while True:
        try:
            await coro_func()
        except asyncio.CancelledError:
            print(f"⚠️ {name} تم إلغاؤه")
            break
        except Exception as e:
            tb = traceback.format_exc()
            print(f"❌ {name} تعطل: {e}\\n{tb}")
            try:
                await send_msg(f"⚠️ <b>تنبيه:</b> حلقة {name} تعطلت وسيتم إعادة تشغيلها\\n<code>{str(e)[:100]}</code>")
            except:
                pass
            await asyncio.sleep(interval)


async def monitor_coro():
    """مراقبة الرصيد"""
    while True:
        async with db_lock:
            if db["paused"]:
                await asyncio.sleep(MONITOR_INTERVAL)
                continue
        
        now = datetime.now(timezone.utc)
        if now.minute == 0:
            async with db_lock:
                db["equity_history"].append({"date": now, "balance": db["current_balance"]})
                if len(db["equity_history"]) > 100:
                    db["equity_history"] = db["equity_history"][-100:]
        
        await asyncio.sleep(MONITOR_INTERVAL)


async def analysis_coro():
    """التحليل الرئيسي"""
    while True:
        async with db_lock:
            if db["paused"]:
                await asyncio.sleep(5)
                continue
            has_trade = db["active_trade"] is not None
            elapsed = time.time() - db["last_analysis_ts"]

        if not has_trade and elapsed >= ANALYSIS_INTERVAL:
            print(f"🔍 [analysis] بدء تحليل - elapsed: {elapsed:.0f}s")
            
            news_blocked = await check_news_and_block()
            if news_blocked:
                print("🔴 [analysis] موقف بسبب أخبار")
                await asyncio.sleep(60)
                continue
            
            if not is_valid_session():
                session = get_session_name()
                print(f"⏸️ [analysis] خارج الجلسات: {session}")
                async with db_lock:
                    db["last_analysis_ts"] = time.time()
                await asyncio.sleep(60)
                continue
            
            print("📊 [analysis] جلب البيانات...")
            tf_data = await fetch_all_tf()
            missing = [k for k, v in tf_data.items() if not v]
            if missing:
                print(f"⚠️ [analysis] ناقص: {missing}")
                await send_msg(f"⚠️ <b>بيانات ناقصة:</b> {', '.join(missing)}")
            
            print("💵 [analysis] جلب DXY...")
            dxy_price = await fetch_dxy_price()
            
            print("🤖 [analysis] Gemini...")
            analysis_text = await analyze_gemini(tf_data, dxy_price)
            
            if analysis_text.startswith("ERROR"):
                print(f"❌ [analysis] Gemini خطأ: {analysis_text}")
                await send_msg(f"❌ <b>خطأ تحليل:</b>\\n{analysis_text}")
                async with db_lock:
                    db["last_analysis_ts"] = time.time()
                await asyncio.sleep(60)
                continue
            
            decision, confidence = parse_signal_decision(analysis_text)
            print(f"📈 [analysis] قرار: {decision} | ثقة: {confidence}%")
            
            async with db_lock:
                db["last_analysis_ts"] = time.time()
                db["analysis_count"] += 1
                db["signals"].append({"text": analysis_text, "time": now_str()})
                if decision == "HOLD":
                    db["last_hold_reason"] = analysis_text[:300]
            
            if decision in ["BUY", "SELL"] and confidence >= MIN_CONFIDENCE:
                emoji = "🟢" if decision == "BUY" else "🔴"
                await send_msg(f"{emoji} <b>إشارة {decision} (ثقة {confidence}%)</b>\\n\\n{analysis_text}")
                print(f"✅ [analysis] إشارة مرسلة: {decision}")
            elif decision in ["BUY", "SELL"] and confidence < MIN_CONFIDENCE:
                await send_msg(f"⏸️ <b>فرصة ضعيفة</b> ({decision} - ثقة {confidence}%)\\nالحد: {MIN_CONFIDENCE}%")
                print(f"⏸️ [analysis] ثقة منخفضة: {confidence}%")
            else:
                async with db_lock:
                    count = db["analysis_count"]
                if count % 3 == 0:
                    await send_msg(f"⏸️ <b>لا فرص واضحة (HOLD)</b>\\nتحاليل: {count} | الجلسة: {get_session_name()}")
                print(f"⏸️ [analysis] HOLD")

        await asyncio.sleep(5)


async def report_coro():
    """التقرير اليومي"""
    while True:
        now = datetime.now(timezone.utc)
        next_report = (now + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
        wait = (next_report - now).total_seconds()
        await asyncio.sleep(wait)
        
        async with db_lock:
            stats = db["stats"]
            risk = db["risk_percent"]
            balance = db["current_balance"]
            initial = db["initial_balance"]
        
        await send_msg(
            f"📅 <b>التقرير اليومي</b>\\n"
            f"النقاط: {stats['total_pips']:+.1f}\\n"
            f"المخاطرة: {risk}%\\n"
            f"الرصيد: {balance:,.2f} USD\\n"
            f"ربح/خسارة: {(balance - initial):+,.2f} USD"
        )


async def session_coro():
    """إشعارات الجلسات"""
    while True:
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        current_minute = now.minute
        
        for session_name, config in SESSIONS_CONFIG.items():
            start_h = config["start"]
            end_h = config["end"]
            today_key = now.strftime("%Y%m%d")
            start_key = f"{session_name}_start_{today_key}"
            end_key = f"{session_name}_end_{today_key}"
            
            if current_hour == start_h and current_minute == 0:
                async with db_lock:
                    if not db["session_notified"].get(start_key, False):
                        db["session_notified"][start_key] = True
                        await send_msg(f"🟢 <b>جلسة {session_name} بدأت!</b> 🚀")
            
            if current_hour == end_h and current_minute == 59:
                async with db_lock:
                    if not db["session_notified"].get(end_key, False):
                        db["session_notified"][end_key] = True
                        await send_msg(f"🔴 <b>جلسة {session_name} انتهت</b> ⏸️")
        
        async with db_lock:
            two_days_ago = (now - timedelta(days=2)).strftime("%Y%m%d")
            for k in list(db["session_notified"].keys()):
                if k.endswith(two_days_ago):
                    del db["session_notified"][k]
        
        await asyncio.sleep(30)


async def atr_coro():
    """مراقبة ATR"""
    while True:
        async with db_lock:
            if db["paused"]:
                await asyncio.sleep(60)
                continue
        
        candles = await fetch_tf("15min")
        if candles and len(candles) > 15:
            atr = await calculate_atr(candles, 14)
            async with db_lock:
                db["atr_data"]["current"] = atr
                threshold = db["atr_data"]["threshold"]
                last_alert = db["atr_data"]["last_alert"]
            
            if atr > threshold and (time.time() - last_alert) > 1800:
                await send_msg(f"⚡ <b>تذبذب عالي!</b> ATR: {atr:.2f} نقاط 🚨")
                async with db_lock:
                    db["atr_data"]["last_alert"] = time.time()
        
        await asyncio.sleep(300)


# ============ نقطة الدخول ============
async def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("price", cmd_price))
    application.add_handler(CommandHandler("signal", cmd_signal))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("weekly", cmd_weekly))
    application.add_handler(CommandHandler("monthly", cmd_monthly))
    application.add_handler(CommandHandler("equity", cmd_equity_chart))
    application.add_handler(CommandHandler("atr", cmd_atr))
    application.add_handler(CommandHandler("errors", cmd_errors))
    application.add_handler(CommandHandler("force", cmd_force_analysis))
    application.add_handler(CommandHandler("risk", cmd_risk))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    print("🚀 البوت يعمل!")
    await send_msg(
        f"🚀 <b>بوت الذهب يعمل!</b>\\n\\n"
        f"⏰ الجلسة: {get_session_name()}\\n"
        f"📊 تحليل كل {ANALYSIS_INTERVAL//60} دقائق\\n"
        f"🎯 الحد الأدنى للثقة: {MIN_CONFIDENCE}%\\n\\n"
        f"استخدم /force لتحليل فوري"
    )

    # تشغيل الحلقات بشكل مستقل (إذا تعطلت إحداها، الباقي يستمر!)
    tasks = [
        asyncio.create_task(safe_loop("monitor", monitor_coro, 10)),
        asyncio.create_task(safe_loop("analysis", analysis_coro, 10)),
        asyncio.create_task(safe_loop("report", report_coro, 3600)),
        asyncio.create_task(safe_loop("session", session_coro, 30)),
        asyncio.create_task(safe_loop("atr", atr_coro, 300)),
    ]
    
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
'''

with open('/mnt/agents/output/gold_bot_stable.py', 'w', encoding='utf-8') as f:
    f.write(enhanced_code)

print("✅ تم إنشاء الملف بنجاح!")
print(f"📄 طول الكود: {len(enhanced_code)} حرف")
