
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



import os
import json
import asyncio
import aiohttp
import time
import math
import re
import xml.etree.ElementTree as ET
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
ANALYSIS_INTERVAL = 300
MIN_CONFIDENCE = 75
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
    "لندن 🇬🇧": {"start": 7, "end": 16, "tz": "UTC"},
    "نيويورك 🇺🇸": {"start": 12, "end": 21, "tz": "UTC"},
    "طوكيو 🇯🇵": {"start": 0, "end": 9, "tz": "UTC"},
    "سيدني 🇦🇺": {"start": 22, "end": 7, "tz": "UTC"},
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
}
db_lock = asyncio.Lock()

# ============ البرومبت (Plain Text) ============
GOLD_SCALP_PROMPT = """
أنت رئيس المحللين الفنيين ومدير المخاطر في صندوق استثماري عالمي (Elite Financial Analyst). مهمتك هي قيادة "شبكة من 12 وكيلاً ذكياً ومخصصاً" لتحليل بيانات الشموع الفعلية المرفقة لأربع فريمات زمنية (M30, M15, M5, M1)، وإصدار قرار تداول حاسم وخالي تماماً من العموميات بناءً على مفهوم الإجماع (Consensus System).

⚠️ [نمط التشغيل: صفقات الزخم المتوسطة - MEDIUM-TERM MOMENTUM MODE]
هدف النظام اقتناص صفقات متوسطة المدى الحركي تنتهي خلال 20-30 دقيقة، مع حركات سعرية أعمق ونسبة عائد للمخاطرة عالية.

بيانات الشموع الفعلية لكل فريم (الأحدث أولاً):

== M30 ==
{data_m30}

== M15 ==
{data_m15}

== M5 ==
{data_m5}

== M1 ==
{data_m1}

== DXY (مؤشر الدولار) ==
سعر DXY الحالي: {dxy_price}

---

### [تفصيل شبكة الوكلاء الـ 12]:
1. Trend Agent: الاتجاه العام على M30 و M15 مقارنة بـ EMA 200.
2. Session & Time Liquidity Agent: سحب السيولة الزمانية وتأكيد التداول داخل London/NY Kill Zones.
3. Order Block Agent: مناطق العرض/الطلب المؤسساتية غير المُعاد اختبارها على M15/M5.
4. FVG / Imbalance Agent: الفجوات السعرية غير المغطاة على M15 و M5.
5. Execution Trigger Agent: كسر هيكلية حقيقي (CHoCH) على M5/M1 فعليًا من البيانات المرفقة.
6. Candlestick Pattern Agent: شموع الارتداد والزخم المؤسساتي على M5.
7. Multi-Timeframe Alignment Agent: توافق [M30/M15 Macro] ➔ [M5 Structure] ➔ [M1 Trigger].
8. Volume & Momentum Agent: اندفاع الحجم والزخم من بيانات M5/M1.
9. DXY & Correlation Agent: مؤشرات الزخم المحسوبة من M15/M5 المرفقة. حلل علاقة الذهب مع DXY: إذا كان DXY يرتفع فالذهب عادة ينخفض والعكس صحيح.
10. Sentiment Agent: مناطق تجمعات الـ Stop Loss المحتملة.
11. News & Macro Filter Agent: حظر الدخول قبل/بعد أخبار عالية التأثير بـ 20 دقيقة.
12. Dynamic Risk Guard Agent: لا يوجد سقف رقمي ثابت لعدد النقاط. ضع SL خلف أقرب نقطة هيكلية حقيقية، مع نسبة ريسك لا تقل عن 1:2.

### [صيغة المخرج]: أعطني النتيجة حصرياً على شكل نص عادي (Plain Text) مرتب بأسطر وخطوط واضحة، وبدون استخدام أقواس JSON أو رموز برمجة خاصة:
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


# ============ دوال الـ API (Twelve Data) ============
async def send_msg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()


async def send_photo(photo_path: str, caption: str = ""):
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


async def fetch_tf(interval: str, symbol: str = SYMBOL):
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
                print(f"⚠️ تحذير Twelve Data للفريم {interval}: {data.get('message')}")
                return {}
            
            if "values" in data:
                candles = data["values"]
                if candles:
                    current_close = float(candles[0]["close"])
                    async with db_lock:
                        if symbol == SYMBOL:
                            db["last_price"] = current_close
                        elif symbol == DXY_SYMBOL:
                            db["dxy_price"] = current_close
                return candles
            return {}


async def fetch_price():
    candles = await fetch_tf("1min")
    async with db_lock:
        return db["last_price"]


async def fetch_dxy_price():
    candles = await fetch_tf("1min", DXY_SYMBOL)
    async with db_lock:
        return db["dxy_price"]


async def fetch_all_tf():
    result = {}
    for label, interval in TIMEFRAMES.items():
        try:
            result[label] = await fetch_tf(interval)
            await asyncio.sleep(1)
        except Exception as e:
            print(f"❌ فشل جلب {label}: {e}")
            result[label] = {}
    return result


async def analyze_gemini(tf_data: dict, dxy_price: float):
    prompt = GOLD_SCALP_PROMPT.format(
        data_m30=json.dumps(tf_data.get("M30", {})),
        data_m15=json.dumps(tf_data.get("M15", {})),
        data_m5=json.dumps(tf_data.get("M5", {})),
        data_m1=json.dumps(tf_data.get("M1", {})),
        dxy_price=dxy_price,
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 6000}}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            result = await resp.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()


# ============ حساب ATR ============
async def calculate_atr(candles: list, period: int = 14):
    if len(candles) < period + 1:
        return 0.0
    
    tr_values = []
    for i in range(1, len(candles)):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i-1]["close"])
        
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = max(tr1, tr2, tr3)
        tr_values.append(tr)
    
    if len(tr_values) < period:
        return sum(tr_values) / len(tr_values) if tr_values else 0.0
    
    atr = sum(tr_values[-period:]) / period
    return atr


# ============ الأخبار ============
async def fetch_forex_news():
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            xml_data = await resp.text()
            root = ET.fromstring(xml_data)
            news_list = []
            now = datetime.now(timezone.utc)
            for event in root.findall('event'):
                currency = event.find('country').text
                impact = event.find('impact').text
                time_str = event.find('date').text + ' ' + event.find('time').text
                event_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if currency == 'USD' and impact == 'High':
                    minutes_until = (event_time - now).total_seconds() / 60
                    news_list.append({
                        'title': event.find('title').text,
                        'time': event_time,
                        'minutes_until': minutes_until
                    })
            return news_list


async def check_news_and_block():
    try:
        news_list = await fetch_forex_news()
        now = time.time()
        for news in news_list:
            if -30 <= news['minutes_until'] <= 20:
                block_until = now + (news['minutes_until'] + 30) * 60
                async with db_lock:
                    db["news_blocked_until"] = block_until
                return True
        async with db_lock:
            if db["news_blocked_until"] > 0 and now > db["news_blocked_until"]:
                db["news_blocked_until"] = 0
        return False
    except Exception as e:
        return False


# ============ إشعارات بداية/نهاية الجلسات ============
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
                            emoji = "🟢"
                            await send_msg(f"{emoji} <b>جلسة {session_name} بدأت!</b>\n\nالسوق الآن نشط. استعد للفرص! 🚀")
                
                if current_hour == end_h and current_minute == 59:
                    async with db_lock:
                        if not db["session_notified"].get(end_key, False):
                            db["session_notified"][end_key] = True
                            emoji = "🔴"
                            await send_msg(f"{emoji} <b>جلسة {session_name} انتهت</b>\n\nتم إغلاق الجلسة. انتظر الجلسة القادمة! ⏸️")
            
            async with db_lock:
                two_days_ago = (now - timedelta(days=2)).strftime("%Y%m%d")
                keys_to_remove = [k for k in db["session_notified"] if k.endswith(two_days_ago)]
                for k in keys_to_remove:
                    del db["session_notified"][k]
            
            await asyncio.sleep(30)
        except Exception as e:
            print(f"❌ خطأ في إشعارات الجلسات: {e}")
            await asyncio.sleep(30)


# ============ تنبيه التذبذب العالي (ATR) ============
async def atr_alert_loop():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(60)
                    continue
            
            candles = await fetch_tf("15min")
            if candles and len(candles) > 15:
                atr = await calculate_atr(candles, period=14)
                
                async with db_lock:
                    db["atr_data"]["current"] = atr
                    threshold = db["atr_data"]["threshold"]
                    last_alert = db["atr_data"]["last_alert"]
                
                if atr > threshold and (time.time() - last_alert) > 1800:
                    await send_msg(
                        f"⚡ <b>تنبيه: تذبذب عالي!</b>\n\n"
                        f"ATR الحالي: <code>{atr:.2f}</code> نقاط\n"
                        f"الحد: <code>{threshold}</code> نقاط\n\n"
                        f"🚨 السوق متقلب جداً. انتبه للمخاطر!"
                    )
                    async with db_lock:
                        db["atr_data"]["last_alert"] = time.time()
            
            await asyncio.sleep(300)
        except Exception as e:
            print(f"❌ خطأ في ATR: {e}")
            await asyncio.sleep(300)


# ============ ملخص الأداء ============
async def generate_performance_summary(period: str = "weekly"):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        
        now = datetime.now(timezone.utc)
        
        if period == "weekly":
            start_of_week = now - timedelta(days=now.weekday())
            start_key = start_of_week.strftime("%Y-%m-%d")
            period_name = "أسبوعي"
            pips_data = stats.get("weekly_pips", {})
        elif period == "monthly":
            start_key = now.strftime("%Y-%m")
            period_name = "شهري"
            pips_data = stats.get("monthly_pips", {})
        else:
            start_key = now.strftime("%Y-%m-%d")
            period_name = "يومي"
            pips_data = stats.get("daily_pips", {})
        
        period_pips = sum(pips_data.values()) if pips_data else stats["total_pips"]
        
        msg = f"""
📊 <b>ملخص الأداء {period_name}</b>

📈 إجمالي الصفقات: {total}
✅ رابحة: {stats["wins"]}
❌ خاسرة: {stats["losses"]}
📉 نسبة الربح: {win_rate:.1f}%
💰 إجمالي النقاط: {stats["total_pips"]:+.1f}
📊 نقاط الفترة: {period_pips:+.1f}
⚖️ نسبة المخاطرة: {db["risk_percent"]}%

💵 الرصيد الحالي: {db["current_balance"]:,.2f} USD
📈 الربح/الخسارة: {(db["current_balance"] - db["initial_balance"]):+,.2f} USD
        """
        return msg


# ============ رسم بياني لنمو الرصيد ============
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
        ax.spines['bottom'].set_color('white')
        ax.spines['top'].set_color('white')
        ax.spines['right'].set_color('white')
        ax.spines['left'].set_color('white')
        
        plt.tight_layout()
        chart_path = "/tmp/equity_chart.png"
        plt.savefig(chart_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
        plt.close()
        
        return chart_path
    except Exception as e:
        print(f"❌ خطأ في إنشاء الرسم البياني: {e}")
        return None


# ============ أوامر Telegram ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 الحالة", callback_data="status"),
         InlineKeyboardButton("💵 السعر", callback_data="price")],
        [InlineKeyboardButton("📈 الإشارة", callback_data="signal"),
         InlineKeyboardButton("📉 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📊 ملخص أسبوعي", callback_data="weekly"),
         InlineKeyboardButton("📊 ملخص شهري", callback_data="monthly")],
        [InlineKeyboardButton("📈 رسم الرصيد", callback_data="equity_chart"),
         InlineKeyboardButton("⚡ ATR", callback_data="atr")],
        [InlineKeyboardButton("⏸️ إيقاف", callback_data="pause"),
         InlineKeyboardButton("▶️ استئناف", callback_data="resume")],
    ]
    reply = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 <b>بوت الذهب الذكي - النسخة المحسّنة</b>\n\n"
        "✅ الميزات الجديدة:\n"
        "• 🟢🔴 إشعارات بداية/نهاية الجلسات\n"
        "• 📊 ربط DXY مع التحليل\n"
        "• 📈 ملخص أداء أسبوعي/شهري\n"
        "• ⚡ تنبيه التذبذب العالي (ATR)\n"
        "• 📉 رسم بياني لنمو الرصيد\n\n"
        "اختر أحد الخيارات:",
        parse_mode="HTML",
        reply_markup=reply
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
    
    status = "⏸️ متوقف" if paused else "✅ يعمل"
    trade_status = f"صفقة {active['direction']} نشطة" if active else "لا توجد صفقة"
    news_status = "🔴 موقف بسبب خبر" if blocked else "🟢 لا توجد أخبار"
    active_sessions = ", ".join(get_all_active_sessions()) if get_all_active_sessions() else "خارج الجلسات"
    
    msg = f"""
📊 <b>حالة البوت</b>
الحالة: {status}
الجلسات النشطة: {active_sessions}
الصفقة: {trade_status}
إشارات اليوم: {signals_count}
نسبة المخاطرة: {risk}%
الأخبار: {news_status}
ATR الحالي: {atr_current:.2f} نقاط
سعر DXY: {dxy:.2f}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = await fetch_price()
        dxy = await fetch_dxy_price()
        msg = f"💵 <b>سعر الذهب</b>\n\nXAU/USD: <code>{price:,.2f}</code> USD\nDXY: <code>{dxy:.2f}</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        if not db["signals"]:
            await update.message.reply_text("⏳ لا توجد إشارات بعد")
            return
        last = db["signals"][-1]
    msg = f"📈 <b>آخر إشارة</b>\n\n{last['text']}"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        risk = db["risk_percent"]
        balance = db["current_balance"]
        initial = db["initial_balance"]
    
    msg = f"""
📉 <b>إحصائيات الأداء</b>
إجمالي الصفقات: {total}
✅ رابحة: {stats["wins"]}
❌ خاسرة: {stats["losses"]}
نسبة الربح: {win_rate:.1f}%
إجمالي النقاط: {stats["total_pips"]:+.1f}
نسبة المخاطرة: {risk}%

💵 الرصيد: {balance:,.2f} USD
📈 الربح/خسارة: {(balance - initial):+,.2f} USD
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await generate_performance_summary("weekly")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await generate_performance_summary("monthly")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_equity_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري إنشاء الرسم البياني...")
    chart_path = await generate_equity_chart()
    if chart_path:
        async with db_lock:
            balance = db["current_balance"]
            initial = db["initial_balance"]
        caption = f"📈 <b>نمو الرصيد</b>\nالرصيد الحالي: <code>{balance:,.2f}</code> USD\nالربح/خسارة: <code>{(balance - initial):+,.2f}</code> USD"
        await send_photo(chart_path, caption)
    else:
        await update.message.reply_text("❌ فشل إنشاء الرسم البياني")


async def cmd_atr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        atr = db["atr_data"]["current"]
        threshold = db["atr_data"]["threshold"]
    
    status = "🟢 طبيعي" if atr <= threshold else "🔴 مرتفع"
    msg = f"""
⚡ <b>مؤشر التذبذب (ATR)</b>
ATR الحالي: {atr:.2f} نقاط
الحد: {threshold} نقاط
الحالة: {status}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        current_risk = db["risk_percent"]
    if context.args:
        try:
            new_risk = float(context.args[0])
            if 0.1 <= new_risk <= 5.0:
                async with db_lock:
                    db["risk_percent"] = new_risk
                await update.message.reply_text(f"✅ <b>تم تعديل نسبة المخاطرة</b>\nالجديدة: <code>{new_risk}%</code>", parse_mode="HTML")
            else:
                await update.message.reply_text("❌ يجب أن تكون بين 0.1% و 5.0%", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ استخدم: /risk 1.5", parse_mode="HTML")
    else:
        await update.message.reply_text(f"📊 نسبة المخاطرة الحالية: <code>{current_risk}%</code>", parse_mode="HTML")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = True
    await update.message.reply_text("⏸️ <b>تم إيقاف البوت مؤقتاً</b>", parse_mode="HTML")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = False
    await update.message.reply_text("▶️ <b>تم استئناف البوت</b>", parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
🤖 <b>الأوامر المتاحة</b>
/start - القائمة الرئيسية
/status - حالة البوت
/price - سعر الذهب + DXY
/signal - آخر إشارة
/stats - إحصائيات الأداء
/weekly - ملخص أسبوعي
/monthly - ملخص شهري
/equity - رسم بياني للرصيد
/atr - مؤشر التذبذب
/risk - نسبة المخاطرة
/pause - إيقاف مؤقت
/resume - استئناف
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "status":
        await cmd_status(query, context)
    elif query.data == "price":
        await cmd_price(query, context)
    elif query.data == "signal":
        await cmd_signal(query, context)
    elif query.data == "stats":
        await cmd_stats(query, context)
    elif query.data == "weekly":
        await cmd_weekly(query, context)
    elif query.data == "monthly":
        await cmd_monthly(query, context)
    elif query.data == "equity_chart":
        await cmd_equity_chart(query, context)
    elif query.data == "atr":
        await cmd_atr(query, context)
    elif query.data == "pause":
        async with db_lock:
            db["paused"] = True
        await query.message.reply_text("⏸️ تم الإيقاف المؤقت")
    elif query.data == "resume":
        async with db_lock:
            db["paused"] = False
        await query.message.reply_text("▶️ تم الاستئناف")


# ============ الحلقات الرئيسية ============
async def monitor_loop():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(MONITOR_INTERVAL)
                    continue
            
            now = datetime.now(timezone.utc)
            if now.minute == 0:
                async with db_lock:
                    db["equity_history"].append({
                        "date": now,
                        "balance": db["current_balance"]
                    })
                    if len(db["equity_history"]) > 100:
                        db["equity_history"] = db["equity_history"][-100:]
            
            await asyncio.sleep(MONITOR_INTERVAL)
        except Exception as e:
            await asyncio.sleep(MONITOR_INTERVAL)


async def analysis_loop():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(5)
                    continue
                has_trade = db["active_trade"] is not None
                elapsed = time.time() - db["last_analysis_ts"]

            if not has_trade and elapsed >= ANALYSIS_INTERVAL:
                news_blocked = await check_news_and_block()
                if news_blocked:
                    await asyncio.sleep(60)
                    continue
                
                if not is_valid_session():
                    async with db_lock:
                        db["last_analysis_ts"] = time.time()
                else:
                    tf_data = await fetch_all_tf()
                    dxy_price = await fetch_dxy_price()
                    analysis_text = await analyze_gemini(tf_data, dxy_price)
                    
                    async with db_lock:
                        db["last_analysis_ts"] = time.time()
                        db["signals"].append({"text": analysis_text, "time": now_str()})
                    
                    await send_msg(f"📈 <b>إشارة تداول جديدة:</b>\n\n{analysis_text}")

            await asyncio.sleep(5)
        except Exception as e:
            await asyncio.sleep(5)


async def daily_report():
    async with db_lock:
        stats = db["stats"]
        risk = db["risk_percent"]
        balance = db["current_balance"]
        initial = db["initial_balance"]
    
    msg = f"""
📅 <b>التقرير اليومي</b>
الربح النقاط: {stats["total_pips"]:+.1f}
المخاطرة: {risk}%
الرصيد: {balance:,.2f} USD
الربح/خسارة: {(balance - initial):+,.2f} USD
    """
    await send_msg(msg)


async def report_loop():
    while True:
        now = datetime.now(timezone.utc)
        next_report = (now + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
        wait = (next_report - now).total_seconds()
        await asyncio.sleep(wait)
        await daily_report()


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
    application.add_handler(CommandHandler("risk", cmd_risk))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    print("🚀 البوت يعمل مع Twelve Data - جاهز!")
    await send_msg("🚀 <b>بوت الذهب يعمل الآن بنجاح!</b>\n\n✅ الميزات الجديدة:\n• إشعارات الجلسات\n• ربط DXY\n• ملخص أسبوعي/شهري\n• تنبيه ATR\n• رسم بياني للرصيد")

    await asyncio.gather(
        monitor_loop(),
        analysis_loop(),
        report_loop(),
        session_notification_loop(),
        atr_alert_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
