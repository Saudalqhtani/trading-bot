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
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ============ الإعدادات ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SYMBOL = "XAU/USD"
MONITOR_INTERVAL = 15
ANALYSIS_INTERVAL = 300  # 5 دقائق
MIN_CONFIDENCE = 75
GEMINI_MODEL = "gemini-1.5-flash"
PIP_VALUE = 1.0

TIMEFRAMES = {
    "M30": ("30min", 50),
    "M15": ("15min", 60),
    "M5": ("5min", 100),
    "M1": ("1min", 60),
}

# ============ الجلسات ============
LONDON_SESSION = (7, 16)
NEW_YORK_SESSION = (12, 21)
TOKYO_SESSION = (0, 9)
SYDNEY_SESSION = (22, 7)

# ============ قاعدة البيانات في الذاكرة ============
db = {
    "trades": [],
    "signals": [],
    "stats": {"wins": 0, "losses": 0, "total_pips": 0},
    "paused": False,
    "active_trade": None,
    "last_analysis_ts": 0,
    "risk_percent": 1.0,
    "news_blocked_until": 0,
    "last_price": 2650.00,  # سعر افتراضي مبدئي
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
9. DXY & Correlation Agent: مؤشرات الزخم المحسوبة من M15/M5 المرفقة.
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


# ============ دوال الـ API ============
async def send_msg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()


async def fetch_price():
    """جلب السعر من آخر شمعة مخزنة في الذاكرة لتجنب استهلاك طلبات الـ API"""
    async with db_lock:
        return db["last_price"]


async def fetch_tf(interval: str, size: int):
    av_interval = interval.lower()
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": "XAUUSD",
        "interval": av_interval,
        "apikey": ALPHA_VANTAGE_API_KEY
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if "Information" in data or "Error Message" in data:
                print(f"⚠️ تحذير Alpha Vantage للفريم {interval}: {json.dumps(data)}")
                return {}
            for key in data:
                if "Time Series" in key:
                    candles = data[key]
                    # تحديث السعر الحالي تلقائياً من أحدث شمعة يتم جلبها
                    if candles:
                        latest_time = sorted(candles.keys())[-1]
                        price = float(candles[latest_time]["4. close"])
                        async with db_lock:
                            db["last_price"] = price
                    return candles
            return {}


async def fetch_all_tf():
    result = {}
    for label, (interval, size) in TIMEFRAMES.items():
        try:
            result[label] = await fetch_tf(interval, size)
            await asyncio.sleep(2)  # مهلة أمان بين الطلبات
        except Exception as e:
            print(f"❌ فشل جلب {label}: {e}")
            result[label] = {}
    return result


async def analyze_gemini(tf_data: dict):
    prompt = GOLD_SCALP_PROMPT.format(
        data_m30=json.dumps(tf_data.get("M30", {})),
        data_m15=json.dumps(tf_data.get("M15", {})),
        data_m5=json.dumps(tf_data.get("M5", {})),
        data_m1=json.dumps(tf_data.get("M1", {})),
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 6000}}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            result = await resp.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()


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


# ============ أوامر Telegram ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 الحالة", callback_data="status"),
         InlineKeyboardButton("💵 السعر", callback_data="price")],
        [InlineKeyboardButton("📈 الإشارة", callback_data="signal"),
         InlineKeyboardButton("📉 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("⏸️ إيقاف", callback_data="pause"),
         InlineKeyboardButton("▶️ استئناف", callback_data="resume")],
    ]
    reply = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 <b>بوت الذهب الذكي</b>\n\nاختر أحد الخيارات:",
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
    status = "⏸️ متوقف" if paused else "✅ يعمل"
    trade_status = f"صفقة {active['direction']} نشطة" if active else "لا توجد صفقة"
    news_status = "🔴 موقف بسبب خبر" if blocked else "🟢 لا توجد أخبار"
    msg = f"""
📊 <b>حالة البوت</b>
الحالة: {status}
الجلسة: {get_session_name()}
الصفقة: {trade_status}
إشارات اليوم: {signals_count}
نسبة المخاطرة: {risk}%
الأخبار: {news_status}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = await fetch_price()
        msg = f"💵 <b>سعر الذهب</b>\n\nXAU/USD: <code>{price:,.2f}</code> USD"
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
    msg = f"""
📉 <b>إحصائيات الأداء</b>
إجمالي الصفقات: {total}
✅ رابحة: {stats['wins']}
❌ خاسرة: {stats['losses']}
نسبة الربح: {win_rate:.1f}%
إجمالي النقاط: {stats['total_pips']:+.1f}
نسبة المخاطرة: {risk}%
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
/price - سعر الذهب الحالي
/signal - آخر إشارة
/stats - إحصائيات الأداء
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
                    analysis_text = await analyze_gemini(tf_data)
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
    msg = f"📅 <b>التقرير اليومي</b>\nالربح النقاط: {stats['total_pips']:+.1f}\nالمخاطرة: {risk}%"
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
    application.add_handler(CommandHandler("risk", cmd_risk))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    print("🚀 البوت يعمل مع Alpha Vantage - جاهز!")
    await send_msg("🚀 <b>بوت الذهب يعمل الآن بنجاح!</b>")

    await asyncio.gather(
        monitor_loop(),
        analysis_loop(),
        report_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
 
