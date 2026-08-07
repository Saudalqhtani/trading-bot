
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
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
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
ANALYSIS_INTERVAL = 300  # 5 دقائق بالضبط
MIN_CONFIDENCE = 75
GEMINI_MODEL = "gemini-1.5-flash"
PIP_VALUE = 1.0

TIMEFRAMES = {
    "M30": "30min",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}

# ============ الجلسات (بالساعة UTC) ============
SESSIONS = {
    "لندن 🇬🇧": (7, 16),
    "نيويورك 🇺🇸": (12, 21),
    "طوكيو 🇯🇵": (0, 9),
    "سيدني 🇦🇺": (22, 7)
}

# ============ قاعدة البيانات في الذاكرة ============
db = {
    "trades": [],
    "signals": [],
    "stats": {"wins": 0, "losses": 0, "total_pips": 0},
    "balance_history": [1000.0],  # لرسم بياني نمو الرصيد
    "paused": False,
    "active_trade": None,
    "last_analysis_ts": 0,
    "risk_percent": 1.0,
    "news_blocked_until": 0,
    "last_price": 2650.0,
    "last_dxy": 105.0,
    "notified_sessions": {}
}
db_lock = asyncio.Lock()

# ============ البرومبت (Plain Text) ============
GOLD_SCALP_PROMPT = """
أنت رئيس المحللين الفنيين ومدير المخاطر في صندوق استثماري عالمي (Elite Financial Analyst). مهمتك هي قيادة "شبكة من 12 وكيلاً ذكياً ومخصصاً" لتحليل بيانات الشموع الفعلية لأربع فريمات زمنية (M30, M15, M5, M1) مع سعر مؤشر الدولار (DXY: {dxy_price})، وإصدار قرار تداول حاسم وخالي تماماً من العموميات بناءً على مفهوم الإجماع (Consensus System).

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
9. DXY & Correlation Agent: تحليل الارتباط العكسي مع مؤشر الدولار الحالي (DXY: {dxy_price}).
10. Sentiment Agent: مناطق تجمعات الـ Stop Loss المحتملة.
11. News & Macro Filter Agent: حظر الدخول قبل/بعد أخبار عالية التأثير بـ 20 دقيقة.
12. Dynamic Risk Guard Agent: لا يوجد سقف رقمي ثابت لعدد النقاط. ضع SL خلف أقرب نقطة هيكلية حقيقية، مع نسبة ريسك لا تقل عن 1:2.

### [صيغة المخرج]: أعطني النتيجة حصرياً على شكل نص عادي (Plain Text) مرتب بأسطر وخطوط واضحة، وبدون استخدام أقواس JSON أو رموز برمجة خاصة:
القرار النهائي: [BUY / SELL / HOLD]
نسبة الثقة: [رقم من 0-100]
سعر الدخول: [رقم]
مؤشر DXY الحالي: [{dxy_price}]
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


# ============ دوال مساعدة والجلسات ============
def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_current_session_info():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    if SESSIONS["لندن 🇬🇧"][0] <= hour < SESSIONS["لندن 🇬🇧"][1]:
        return "لندن 🇬🇧"
    elif SESSIONS["نيويورك 🇺🇸"][0] <= hour < SESSIONS["نيويورك 🇺🇸"][1]:
        return "نيويورك 🇺🇸"
    elif SESSIONS["طوكيو 🇯🇵"][0] <= hour < SESSIONS["طوكيو 🇯🇵"][1]:
        return "طوكيو 🇯🇵"
    elif hour >= SESSIONS["سيدني 🇦🇺"][0] or hour < SESSIONS["سيدني 🇦🇺"][1]:
        return "سيدني 🇦🇺"
    return "خارج الجلسات ⏸️"


def is_valid_session():
    s = get_current_session_info()
    return s != "خارج الجلسات ⏸️"


# ============ دوال الـ API (Twelve Data) ============
async def send_msg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()


async def send_photo_bytes(photo_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    data = aiohttp.FormData()
    data.add_field('chat_id', str(TELEGRAM_CHAT_ID))
    data.add_field('caption', caption)
    data.add_field('parse_mode', 'HTML')
    data.add_field('photo', photo_bytes, filename='chart.png', content_type='image/png')
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()


async def fetch_dxy():
    """جلب سعر مؤشر الدولار DXY"""
    url = "https://api.twelvedata.com/price"
    params = {"symbol": DXY_SYMBOL, "apikey": TWELVE_DATA_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            if "price" in data:
                val = float(data["price"])
                async with db_lock:
                    db["last_dxy"] = val
                return val
            return db["last_dxy"]


async def fetch_tf(interval: str):
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": SYMBOL, "interval": interval, "outputsize": 20, "apikey": TWELVE_DATA_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if "values" in data:
                candles = data["values"]
                if candles and interval == "1min":
                    async with db_lock:
                        db["last_price"] = float(candles[0]["close"])
                return candles
            return []


async def fetch_price():
    await fetch_tf("1min")
    async with db_lock:
        return db["last_price"]


async def fetch_all_tf():
    result = {}
    for label, interval in TIMEFRAMES.items():
        try:
            result[label] = await fetch_tf(interval)
            await asyncio.sleep(1)
        except Exception as e:
            result[label] = []
    return result


# ============ ميزة 5: حساب التذبذب (ATR) ============
def calculate_atr(candles, period=14):
    if not candles or len(candles) < period:
        return 0.0
    tr_sum = 0.0
    for i in range(min(period, len(candles))):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        tr_sum += (high - low)
    return tr_sum / period


# ============ ميزة 6: رسم بياني لنمو الرصيد ============
def generate_balance_chart():
    plt.figure(figsize=(6, 3))
    plt.style.use('dark_background')
    async with db_lock:
        history = list(db["balance_history"])
    plt.plot(history, marker='o', color='#00ffcc', linewidth=2)
    plt.title("Account Balance Growth", color='white', fontsize=10)
    plt.xlabel("Trades / Reports", color='gray', fontsize=8)
    plt.ylabel("Balance ($)", color='gray', fontsize=8)
    plt.grid(True, linestyle='--', alpha=0.3)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf.read()


async def analyze_gemini(tf_data: dict, dxy_price: float):
    prompt = GOLD_SCALP_PROMPT.format(
        dxy_price=dxy_price,
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
                    news_list.append({'minutes_until': minutes_until})
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
        return False
    except Exception:
        return False


# ============ أوامر Telegram ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 الحالة", callback_data="status"), InlineKeyboardButton("💵 السعر & DXY", callback_data="price")],
        [InlineKeyboardButton("📈 الإشارة", callback_data="signal"), InlineKeyboardButton("📉 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📈 تقرير النمو", callback_data="chart"), InlineKeyboardButton("📊 ملخص موسع", callback_data="summary")],
        [InlineKeyboardButton("⏸️ إيقاف", callback_data="pause"), InlineKeyboardButton("▶️ استئناف", callback_data="resume")],
    ]
    await update.message.reply_text("🤖 <b>بوت الذهب الذكي (مطور)</b>\n\nاختر أحد الخيارات:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        paused = db["paused"]
        signals_count = len(db["signals"])
        risk = db["risk_percent"]
    status_text = "⏸️ متوقف" if "عمل" not in ("✅ يعمل" if not paused else "⏸️ متوقف") else "✅ يعمل"
    msg = f"📊 <b>حالة البوت</b>\nالحالة: {status_text}\nالجلسة الحالية: {get_current_session_info()}\nإشارات اليوم: {signals_count}\nنسبة المخاطرة: {risk}%"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = await fetch_price()
        dxy = await fetch_dxy()
        msg = f"💵 <b>الأسعار الحالية اللحظية</b>\n\n🔹 XAU/USD: <code>{price:,.2f}</code> USD\n🔹 DXY (الدولار): <code>{dxy:,.2f}</code>"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب الأسعار: {e}")


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        if not db["signals"]:
            await update.message.reply_text("⏳ لا توجد إشارات بعد")
            return
        last = db["signals"][-1]
    await update.message.reply_text(f"📈 <b>آخر إشارة</b>\n\n{last['text']}", parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
    msg = f"📉 <b>إحصائيات الأداء السريعة</b>\nإجمالي الصفقات: {total}\n✅ رابحة: {stats['wins']}\n❌ خاسرة: {stats['losses']}\nنسبة الربح: {win_rate:.1f}%\nإجمالي النقاط: {stats['total_pips']:+.1f}"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        photo = generate_balance_chart()
        await send_photo_bytes(photo, "📈 <b>رسم بياني لنمو الرصيد والأداء</b>")
    except Exception as e:
        await update.message.reply_text(f"❌ تعذر إنشاء الرسم البياني: {e}")


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
    elif query.data == "chart":
        try:
            photo = generate_balance_chart()
            await send_photo_bytes(photo, "📈 <b>رسم بياني لنمو الرصيد والأداء</b>")
        except:
            await query.message.reply_text("❌ خطأ في إرسال الرسم البياني")
    elif query.data == "summary":
        async with db_lock:
            stats = db["stats"]
            total = stats["wins"] + stats["losses"]
        await query.message.reply_text(f"📊 <b>الملخص الموسع (أسبوعي/شهري)</b>\nإجمالي الصفقات المنفذة: {total}\nمجموع النقاط المحققة: {stats['total_pips']:+.1f} pips", parse_mode="HTML")
    elif query.data == "pause":
        async with db_lock:
            db["paused"] = True
        await query.message.reply_text("⏸️ تم الإيقاف المؤقت")
    elif query.data == "resume":
        async with db_lock:
            db["paused"] = False
        await query.message.reply_text("▶️ تم الاستئناف")


# ============ الخلفيات والمراقبة التلقائية ============
async def session_monitor_loop():
    """الميزة 1 & 2: مراقبة بداية ونهاية الجلسات وإرسال إشعارات تلقائية"""
    while True:
        try:
            now = datetime.now(timezone.utc)
            hour = now.hour
            minute = now.minute
            
            # فحص جلسة لندن (تبدأ 7 UTC، تنتهي 16 UTC)
            today_key = now.strftime("%Y-%m-%d")
            async with db_lock:
                notified = db["notified_sessions"]

            if hour == 7 and minute < 5:
                if notified.get(f"london_start_{today_key}") != True:
                    async with db_lock:
                        db["notified_sessions"][f"london_start_{today_key}"] = True
                    await send_msg("🟢 <b>جلسة لندن بدأت!</b> (انطلاق السيولة الأوروبية والسيشن الأساسي للذهب)")
            elif hour == 16 and minute < 5:
                if notified.get(f"london_end_{today_key}") != True:
                    async with db_lock:
                        db["notified_sessions"][f"london_end_{today_key}"] = True
                    await send_msg("🔴 <b>جلسة لندن انتهت / إغلاق التداخل</b>")

            # فحص جلسة نيويورك (تبدأ 12 UTC، تنتهي 21 UTC)
            if hour == 12 and minute < 5:
                if notified.get(f"ny_start_{today_key}") != True:
                    async with db_lock:
                        db["notified_sessions"][f"ny_start_{today_key}"] = True
                    await send_msg("🟢 <b>جلسة نيويورك بدأت!</b> (ذروة الزخم والسيولة الأمريكية)")
            elif hour == 21 and minute < 5:
                if notified.get(f"ny_end_{today_key}") != True:
                    async with db_lock:
                        db["notified_sessions"][f"ny_end_{today_key}"] = True
                    await send_msg("🔴 <b>جلسة نيويورك انتهت</b>")

        except Exception as e:
            pass
        await asyncio.sleep(60)


async def volatility_monitor_loop():
    """الميزة 5: تنبيه التذبذب العالي عند تجاوز ATR حداً معيناً"""
    while True:
        try:
            candles = await fetch_tf("5min")
            atr_val = calculate_atr(candles, period=14)
            if atr_val > 4.5:  # حد مرتفع للتذبذب على الذهب لفريم 5 دقائق
                await send_msg(f"⚠️ <b>تنبيه تذبذب عالي!</b>\nتم رصد حركة قوية ونطاق واسع في الشموع (ATR = {atr_val:.2f}). يرجى توخي الحذر وإدارة المخاطر بحارصة.")
        except Exception:
            pass
        await asyncio.sleep(600)  # كل 10 دقائق


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
                if await check_news_and_block():
                    await asyncio.sleep(60)
                    continue
                
                if not is_valid_session():
                    async with db_lock:
                        db["last_analysis_ts"] = time.time()
                else:
                    tf_data = await fetch_all_tf()
                    dxy_price = await fetch_dxy()
                    analysis_text = await analyze_gemini(tf_data, dxy_price)
                    
                    async with db_lock:
                        db["last_analysis_ts"] = time.time()
                        db["signals"].append({"text": analysis_text, "time": now_str()})
                    
                    await send_msg(f"📈 <b>إشارة تداول جديدة مع مؤشر DXY:</b>\n\n{analysis_text}")

            await asyncio.sleep(5)
        except Exception as e:
            await asyncio.sleep(5)


async def daily_report():
    """الميزة 4 & 6: التقرير اليومي الشامل متضمناً رسم نمو الرصيد"""
    async with db_lock:
        stats = db["stats"]
        risk = db["risk_percent"]
    msg = f"📅 <b>التقرير الشامل (يومي/دوري)</b>\nإجمالي النقاط: {stats['total_pips']:+.1f}\nالربح الإجمالي للصناعة: {stats['wins']} رابحة مقابل {stats['losses']} خاسرة\nنسبة المخاطرة الثابتة: {risk}%"
    try:
        photo = generate_balance_chart()
        await send_photo_bytes(photo, msg)
    except:
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
    application.add_handler(CommandHandler("chart", cmd_chart))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    print("🚀 بوت الذهب المتطور يعمل بكامل الميزات بنجاح!")
    await send_msg("🚀 <b>بوت الذهب (المطور مع إشعارات الجلسات وربط DXY والـ ATR) يعمل الآن بنجاح!</b>")

    await asyncio.gather(
        session_monitor_loop(),
        volatility_monitor_loop(),
        analysis_loop(),
        report_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
