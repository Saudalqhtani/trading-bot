"""
Gold Scalp AI Monitor v4 - Railway Edition (Full Features)
========================================================================
- أوامر Telegram تفاعلية
- إحصائيات وقاعدة بيانات في الذاكرة
- تقرير يومي
- تحكم كامل من الجوال
"""

import os
import json
import asyncio
import aiohttp
import time
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ============ الإعدادات ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SYMBOL = "XAU/USD"
MONITOR_INTERVAL = 15
ANALYSIS_INTERVAL = 180
MIN_CONFIDENCE = 75
GEMINI_MODEL = "gemini-1.5-flash"
PIP_VALUE = 1.0

TIMEFRAMES = {
    "M30": ("30min", 50),
    "M15": ("15min", 60),
    "M5": ("5min", 100),
    "M1": ("1min", 60),
}

LONDON_SESSION = (7, 16)
NEW_YORK_SESSION = (12, 21)

# ============ قاعدة البيانات في الذاكرة ============
db = {
    "trades": [],
    "signals": [],
    "stats": {"wins": 0, "losses": 0, "total_pips": 0},
    "paused": False,
    "active_trade": None,
    "last_analysis_ts": 0,
}
db_lock = asyncio.Lock()

# ============ البرومبت ============
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
1. Trend Agent: الاتجاه العام على M30 و M15 مقارنة بـ EMA 200 (احسبه فعليًا من بيانات M30/M15 المرفقة).
2. Session & Time Liquidity Agent: سحب السيولة الزمانية وتأكيد التداول داخل London/NY Kill Zones.
3. Order Block Agent: مناطق العرض/الطلب المؤسساتية غير المُعاد اختبارها على M15/M5.
4. FVG / Imbalance Agent: الفجوات السعرية غير المغطاة على M15 و M5.
5. Execution Trigger Agent: كسر هيكلية حقيقي (CHoCH) على M5/M1 فعليًا من البيانات المرفقة.
6. Candlestick Pattern Agent: شموع الارتداد والزخم المؤسساتي على M5.
7. Multi-Timeframe Alignment Agent: توافق [M30/M15 Macro] ➔ [M5 Structure] ➔ [M1 Trigger] - استخدم البيانات الفعلية الأربعة، لا تفترض.
8. Volume & Momentum Agent: اندفاع الحجم والزخم من بيانات M5/M1.
9. DXY & Correlation Agent: مؤشرات الزخم (RSI/Stochastic RSI) المحسوبة من M15/M5 المرفقة.
10. Sentiment Agent: مناطق تجمعات الـ Stop Loss المحتملة.
11. News & Macro Filter Agent: حظر الدخول قبل/بعد أخبار عالية التأثير بـ 20 دقيقة.
12. Dynamic Risk Guard Agent: لا يوجد سقف رقمي ثابت لعدد النقاط. ضع SL خلف أقرب نقطة هيكلية حقيقية (Swing High/Low محمي أو حدود منطقة Order Block) - المسافة تتحدد حسب تذبذب السوق الفعلي وقت التحليل، صغيرة كانت أو كبيرة، المهم أن تكون المنطقة آمنة فعليًا وليست عشوائية. TP1 و TP2 يوضعان عند أقرب مناطق سيولة/مقاومة أو دعم فعلية على الشارت (مو رقم ثابت مسبقًا). يجب أن تبقى نسبة العائد للمخاطرة (R:R) لا تقل عن 1:2 كحد أدنى مهما كانت المسافات.

### [طريقة القرار]:
- 12 وكيل يصوتون BUY/SELL/HOLD بناءً على البيانات الفعلية المرفقة فقط، بدون افتراضات.
- الوكلاء 5، 7، 11، 12 لا يصوتون BUY/SELL إلا بعد استيفاء شرط أن يكون SL خلف نقطة هيكلية حقيقية (مو عشوائي) وتوافق الفريمات الأربعة فعليًا و R:R لا يقل عن 1:2.
- إجماع 9+ أصوات: (9/12=75-80%)، (10/12=81-89%)، (11-12/12=90%+).
- أقل من 9 أصوات أو كان الـ SL بمكان غير هيكلي (عشوائي) أو R:R أقل من 1:2 = HOLD.

### [صيغة المخرج]: أعطني JSON فقط بدون أي نص إضافي قبله أو بعده. كن مختصرًا وواضحًا في agents_votes (سطر واحد قصير لكل وكيل) وفي executive_summary (3-4 جمل كحد أقصى) حتى لا يتجاوز الرد الحد المسموح:
{{
  "final_decision": "BUY" | "SELL" | "HOLD",
  "confidence_score": رقم من 0-100,
  "trade_setup": {{
    "entry_zone": رقم (السعر الدقيق للدخول),
    "stop_loss_pips": رقم نقاط (المسافة الفعلية بين سعر الدخول وأقرب نقطة هيكلية حقيقية - بدون أي حد أقصى مفروض),
    "take_profit_1_pips": رقم نقاط (المسافة الفعلية لأقرب منطقة سيولة/مقاومة - بدون أي حد أقصى مفروض),
    "take_profit_2_pips": رقم نقاط (المسافة الفعلية للهدف الثاني الأبعد - بدون أي حد أقصى مفروض),
    "risk_reward_ratio": "مثال 1:3",
    "recommended_risk_percent": "نسبة المخاطرة الموصى بها",
    "expected_duration": "20-30 mins"
  }},
  "kill_zone_status": "London" | "NY" | "Outside Window",
  "agents_votes": ["قائمة تفصيلية بصوت كل وكيل من الـ 12 مع سبب مختصر يستند لبيانات فعلية"],
  "executive_summary": "ملخص تنفيذي بالعربية"
}}
"""


# ============ دوال مساعدة ============
def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def is_valid_session():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    return (LONDON_SESSION[0] <= hour < LONDON_SESSION[1]) or (NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1])


def get_session_name():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    if LONDON_SESSION[0] <= hour < LONDON_SESSION[1]:
        return "لندن 🇬🇧"
    elif NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]:
        return "نيويورك 🇺🇸"
    return "خارج الجلسات ⏸️"


# ============ API دوال ============
async def send_msg(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()


async def fetch_price():
    url = "https://api.twelvedata.com/quote"
    params = {"symbol": SYMBOL, "apikey": TWELVE_DATA_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            return float(data["close"])


async def fetch_tf(interval: str, size: int):
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": SYMBOL, "interval": interval, "outputsize": size, "apikey": TWELVE_DATA_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            return data["values"]


async def fetch_all_tf():
    result = {}
    for label, (interval, size) in TIMEFRAMES.items():
        result[label] = await fetch_tf(interval, size)
        await asyncio.sleep(1)
    return result


async def analyze_gemini(tf_data: dict):
    prompt = GOLD_SCALP_PROMPT.format(
        data_m30=json.dumps(tf_data["M30"]),
        data_m15=json.dumps(tf_data["M15"]),
        data_m5=json.dumps(tf_data["M5"]),
        data_m1=json.dumps(tf_data["M1"]),
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 6000}}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            result = await resp.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(clean)


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
    
    status = "⏸️ متوقف" if paused else "✅ يعمل"
    trade_status = f"صفقة {active['direction']} نشطة" if active else "لا توجد صفقة"
    
    msg = f"""
📊 <b>حالة البوت</b>

الحالة: {status}
الجلسة: {get_session_name()}
الصفقة: {trade_status}
إشارات اليوم: {signals_count}
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
    
    msg = f"""
📈 <b>آخر إشارة</b>

القرار: {last['decision']}
الثقة: {last['confidence']}%
السعر: {last['price']}
الوقت: {last['time']}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
    
    msg = f"""
📉 <b>إحصائيات الأداء</b>

إجمالي الصفقات: {total}
✅ رابحة: {stats['wins']}
❌ خاسرة: {stats['losses']}
نسبة الربح: {win_rate:.1f}%
إجمالي النقاط: {stats['total_pips']:+.1f}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = True
    await update.message.reply_text("⏸️ <b>تم إيقاف البوت مؤقتاً</b>", parse_mode="HTML")
    await send_msg("⏸️ البوت متوقف مؤقتاً من المستخدم")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = False
    await update.message.reply_text("▶️ <b>تم استئناف البوت</b>", parse_mode="HTML")
    await send_msg("▶️ البوت يعمل الآن")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
🤖 <b>الأوامر المتاحة</b>

/start - القائمة الرئيسية
/status - حالة البوت
/price - سعر الذهب الحالي
/signal - آخر إشارة
/stats - إحصائيات الأداء
/pause - إيقاف مؤقت
/resume - استئناف
/help - المساعدة

💡 <b>نصائح:</b>
• البوت يعمل فقط في جلسات لندن ونيويورك
• الثقة المطلوبة: 75%+
• أنت تنفذ الصفقات يدوياً على XM
    """
    await update.message.reply_text(msg, parse_mode="HTML")


# ============ معالج الأزرار (مُصلح) ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # نستخدم query.message مباشرة لأنه يحتوي على reply_text
    if query.data == "status":
        msg = f"""
📊 <b>حالة البوت</b>

الحالة: {'⏸️ متوقف' if db['paused'] else '✅ يعمل'}
الجلسة: {get_session_name()}
الصفقة: {'صفقة ' + db['active_trade']['direction'] + ' نشطة' if db['active_trade'] else 'لا توجد صفقة'}
إشارات اليوم: {len(db['signals'])}
        """
        await query.message.reply_text(msg, parse_mode="HTML")
        
    elif query.data == "price":
        try:
            price = await fetch_price()
            msg = f"💵 <b>سعر الذهب</b>\n\nXAU/USD: <code>{price:,.2f}</code> USD"
            await query.message.reply_text(msg, parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ خطأ: {e}")
            
    elif query.data == "signal":
        if not db["signals"]:
            await query.message.reply_text("⏳ لا توجد إشارات بعد")
        else:
            last = db["signals"][-1]
            msg = f"""
📈 <b>آخر إشارة</b>

القرار: {last['decision']}
الثقة: {last['confidence']}%
السعر: {last['price']}
الوقت: {last['time']}
            """
            await query.message.reply_text(msg, parse_mode="HTML")
            
    elif query.data == "stats":
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        msg = f"""
📉 <b>إحصائيات الأداء</b>

إجمالي الصفقات: {total}
✅ رابحة: {stats['wins']}
❌ خاسرة: {stats['losses']}
نسبة الربح: {win_rate:.1f}%
إجمالي النقاط: {stats['total_pips']:+.1f}
        """
        await query.message.reply_text(msg, parse_mode="HTML")
        
    elif query.data == "pause":
        db["paused"] = True
        await query.message.reply_text("⏸️ <b>تم إيقاف البوت مؤقتاً</b>", parse_mode="HTML")
        await send_msg("⏸️ البوت متوقف مؤقتاً من المستخدم")
        
    elif query.data == "resume":
        db["paused"] = False
        await query.message.reply_text("▶️ <b>تم استئناف البوت</b>", parse_mode="HTML")
        await send_msg("▶️ البوت يعمل الآن")


# ============ التقرير اليومي ============
async def daily_report():
    async with db_lock:
        stats = db["stats"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        signals_today = [s for s in db["signals"] if s["time"].startswith(today)]
    
    msg = f"""
📅 <b>التقرير اليومي</b>

إشارات اليوم: {len(signals_today)}
الصفقات المغلقة: {stats['wins'] + stats['losses']}
إجمالي النقاط: {stats['total_pips']:+.1f}

🕐 {now_str()}
    """
    await send_msg(msg)


# ============ التحليل والمراقبة ============
async def open_trade(analysis: dict, price: float):
    direction = analysis["final_decision"]
    setup = analysis["trade_setup"]
    entry = float(setup["entry_zone"])
    sl_pips = float(setup["stop_loss_pips"])
    tp1_pips = float(setup["take_profit_1_pips"])
    tp2_pips = float(setup["take_profit_2_pips"])

    sign = 1 if direction == "BUY" else -1
    trade = {
        "direction": direction,
        "entry": entry,
        "sl_price": entry - sign * sl_pips * PIP_VALUE,
        "tp1_price": entry + sign * tp1_pips * PIP_VALUE,
        "tp2_price": entry + sign * tp2_pips * PIP_VALUE,
        "opened_at": now_str(),
        "confidence": analysis["confidence_score"],
        "summary": analysis.get("executive_summary", "-"),
    }

    async with db_lock:
        db["active_trade"] = trade
        db["signals"].append({
            "decision": direction,
            "confidence": analysis["confidence_score"],
            "price": entry,
            "time": now_str(),
        })

    emoji = "🟢" if direction == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>إشارة جديدة {direction}</b>\n\n"
        f"الدخول: {entry}\n"
        f"الثقة: {trade['confidence']}%\n"
        f"SL: {trade['sl_price']:.2f}\n"
        f"TP1: {trade['tp1_price']:.2f} | TP2: {trade['tp2_price']:.2f}\n"
        f"R:R: {setup.get('risk_reward_ratio', '-')}\n"
        f"المخاطرة: {setup.get('recommended_risk_percent', '-')}\n\n"
        f"<b>الملخص:</b>\n{trade['summary']}\n\n"
        f"🕐 {trade['opened_at']}"
    )
    await send_msg(msg)
    return trade


async def check_trade(trade: dict, price: float):
    direction = trade["direction"]
    sign = 1 if direction == "BUY" else -1
    
    if (price - trade["sl_price"]) * sign <= 0:
        return "sl"
    if (price - trade["tp2_price"]) * sign >= 0:
        return "tp2"
    if (price - trade["tp1_price"]) * sign >= 0:
        return "tp1"
    return None


async def close_trade(trade: dict, price: float, reason: str):
    direction = trade["direction"]
    entry = trade["entry"]
    pips = abs(price - entry) / PIP_VALUE
    
    async with db_lock:
        db["active_trade"] = None
        if reason == "sl":
            db["stats"]["losses"] += 1
            db["stats"]["total_pips"] -= pips
        else:
            db["stats"]["wins"] += 1
            db["stats"]["total_pips"] += pips

    if reason == "sl":
        msg = f"❌ <b>وقف خسارة - {direction}</b>\nالسعر: {price}\nالخسارة: {pips:.1f} نقطة\n🕐 {now_str()}"
    elif reason == "tp2":
        msg = f"🎯 <b>TP2 محقق - {direction}</b>\nالسعر: {price}\nالربح: {pips:.1f} نقطة\n🕐 {now_str()}"
    else:
        msg = f"✅ <b>TP1 محقق - {direction}</b>\nالسعر: {price}\nالربح: {pips:.1f} نقطة\n🕐 {now_str()}"
    
    await send_msg(msg)


# ============ الحلقات الرئيسية ============
async def monitor_loop():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(MONITOR_INTERVAL)
                    continue
                trade = db["active_trade"]

            if trade:
                price = await fetch_price()
                result = await check_trade(trade, price)
                if result:
                    await close_trade(trade, price, result)
                    async with db_lock:
                        db["last_analysis_ts"] = 0

            await asyncio.sleep(MONITOR_INTERVAL)
        except Exception as e:
            print(f"❌ خطأ مراقبة: {e}")
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
                if not is_valid_session():
                    print(f"[تحليل] خارج الجلسات - تخطي")
                    async with db_lock:
                        db["last_analysis_ts"] = time.time()
                else:
                    print(f"[تحليل] جاري التحليل...")
                    tf_data = await fetch_all_tf()
                    price = await fetch_price()
                    analysis = await analyze_gemini(tf_data)
                    decision = analysis["final_decision"]
                    confidence = float(analysis["confidence_score"])
                    print(f"  القرار: {decision} | الثقة: {confidence}%")

                    async with db_lock:
                        db["last_analysis_ts"] = time.time()
                        if decision in ("BUY", "SELL") and confidence >= MIN_CONFIDENCE:
                            await open_trade(analysis, price)
                        else:
                            print("  ⏸️ HOLD أو ثقة منخفضة")

            await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ خطأ تحليل: {e}")
            await asyncio.sleep(5)


async def report_loop():
    while True:
        now = datetime.now(timezone.utc)
        next_report = (now + timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
        wait = (next_report - now).total_seconds()
        await asyncio.sleep(wait)
        await daily_report()


# ============ نقطة الدخول ============
async def main():
    # إعداد Telegram bot
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("price", cmd_price))
    application.add_handler(CommandHandler("signal", cmd_signal))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))

    # بدء البوت
    await application.initialize()
    await application.start()
    
    # إشعار بدء التشغيل
    await send_msg("🚀 <b>بوت الذهب يعمل الآن!</b>\n\nالأوامر المتاحة:\n/status - الحالة\n/price - السعر\n/signal - الإشارة\n/stats - الإحصائيات\n/pause - إيقاف\n/resume - استئناف\n/help - المساعدة")

    # تشغيل المهام
    await asyncio.gather(
        monitor_loop(),
        analysis_loop(),
        report_loop(),
        application.updater.start_polling(),
    )


if __name__ == "__main__":
    asyncio.run(main())
 
