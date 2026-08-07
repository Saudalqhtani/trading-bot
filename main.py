"""
Gold Scalp AI Monitor v6.0 - Railway Edition (Optimized)
========================================================================
- اوامر Telegram تفاعلية
- مصدر رئيسي: Twelve Data
- مراقبة ذكية للصفقات بدلا من تحليل مستمر
- اشعارات الاخبار قبل 30 دقيقة
- تقليل الحمل على Gemini API
- تحديثات فقط عند تغيرات مهمة
"""

import os
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

# ============ الاعدادات ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SYMBOL = "XAU/USD"
DXY_SYMBOL = "DXY"
MONITOR_INTERVAL = 15
ANALYSIS_INTERVAL = 180
MIN_CONFIDENCE = 70
GEMINI_MODEL = "gemini-3.5-flash"
PIP_VALUE = 1.0

# اعدادات مراقبة الصفقات
TRADE_MONITOR_INTERVAL = 30
NEWS_CHECK_INTERVAL = 300
SIGNIFICANT_MOVE_PIPS = 5

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
    "طوكيو 🇵🇵": {"start": 0, "end": 9},
    "سيدني 🇦🇺": {"start": 22, "end": 7},
}

# ============ قاعدة البيانات ============
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

### ⚠️ تعليمات مهمة جداً:
- إذا كانت الإشارة BUY أو SELL، يجب أن تكون نسبة الثقة 75% أو أعلى.

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
        return "طوكيو 🇵🇵"
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
        active.append("طوكيو 🇵🇵")
    if hour >= SYDNEY_SESSION[0] or hour < SYDNEY_SESSION[1]:
        active.append("سيدني 🇦🇺")
    return active


def parse_signal_decision(text: str):
    decision = "HOLD"
    confidence = 0
    text_upper = text.upper()
    if "القرار النهائي:" in text:
        line = text.split("القرار النهائي:")[1].split("\n")[0].strip().upper()
        if "BUY" in line:
            decision = "BUY"
        elif "SELL" in line:
            decision = "SELL"
    elif "BUY" in text_upper and "SELL" not in text_upper.split("BUY")[0].split("\n")[-1]:
        decision = "BUY"
    elif "SELL" in text_upper:
        decision = "SELL"
    if "نسبة الثقة:" in text:
        try:
            conf_line = text.split("نسبة الثقة:")[1].split("\n")[0].strip()
            numbers = re.findall(r"\d+", conf_line)
            if numbers:
                confidence = int(numbers[0])
        except:
            pass
    return decision, confidence


def parse_trade_details(text: str):
    details = {"entry": 0, "sl_pips": 0, "tp1_pips": 0, "tp2_pips": 0, "rr": "", "duration": ""}
    try:
        if "سعر الدخول:" in text:
            line = text.split("سعر الدخول:")[1].split("\n")[0].strip()
            nums = re.findall(r"\d+\.?\d*", line)
            if nums:
                details["entry"] = float(nums[0])
        if "وقف الخسارة نقاط:" in text:
            line = text.split("وقف الخسارة نقاط:")[1].split("\n")[0].strip()
            nums = re.findall(r"\d+\.?\d*", line)
            if nums:
                details["sl_pips"] = float(nums[0])
        if "الهدف الاول نقاط:" in text:
            line = text.split("الهدف الاول نقاط:")[1].split("\n")[0].strip()
            nums = re.findall(r"\d+\.?\d*", line)
            if nums:
                details["tp1_pips"] = float(nums[0])
        if "الهدف الثاني نقاط:" in text:
            line = text.split("الهدف الثاني نقاط:")[1].split("\n")[0].strip()
            nums = re.findall(r"\d+\.?\d*", line)
            if nums:
                details["tp2_pips"] = float(nums[0])
        if "نسبة العائد للمخاطرة:" in text:
            details["rr"] = text.split("نسبة العائد للمخاطرة:")[1].split("\n")[0].strip()
        if "المدة المتوقعة:" in text:
            details["duration"] = text.split("المدة المتوقعة:")[1].split("\n")[0].strip()
    except Exception as e:
        print(f"⚠️ خطأ parse_trade_details: {e}")
    return details


# ============ دوال الـ API ============
async def send_msg(text: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
    except Exception as e:
        print(f"❌ فشل ارسال Telegram: {e}")


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


async def fetch_tf(interval: str, symbol: str = SYMBOL):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": 20, "apikey": TWELVE_DATA_API_KEY}
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
            result[label] = data if data else {}
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"❌ فشل جلب {label}: {e}")
            result[label] = {}
    return result


async def analyze_gemini(tf_data: dict, dxy_price: float):
    try:
        async with db_lock:
            db["last_gemini_call"] = time.time()
            db["gemini_calls_today"] += 1
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
            "generationConfig": {"maxOutputTokens": 4000, "temperature": 0.3, "topP": 0.95}
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                result = await resp.json()
                if "error" in result:
                    err = result["error"]
                    err_msg = err.get("message", "Unknown Gemini error")
                    err_code = err.get("code", "unknown")
                    print(f"❌ Gemini API خطأ [{err_code}]: {err_msg}")
                    if "not found" in err_msg.lower() or "not supported" in err_msg.lower():
                        print("🔄 محاولة بنموذج احتياطي...")
                        return await analyze_gemini_fallback(prompt)
                    return f"ERROR: {err_msg}"
                if "candidates" not in result or not result["candidates"]:
                    print("❌ Gemini: لا candidates")
                    return "ERROR: No candidates in response"
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
    except Exception as e:
        print(f"❌ استثناء Gemini: {e}")
        return f"ERROR: {str(e)}"


async def analyze_gemini_fallback(prompt: str):
    fallback_models = ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-3-flash"]
    for model in fallback_models:
        try:
            print(f"🔄 تجربة نموذج احتياطي: {model}")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 4000, "temperature": 0.3}}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    result = await resp.json()
                    if "error" not in result and "candidates" in result:
                        text = result["candidates"][0]["content"]["parts"][0]["text"]
                        print(f"✅ نموذج {model} نجح!")
                        return text.strip()
        except Exception as e:
            print(f"❌ نموذج {model} فشل: {e}")
            continue
    return "ERROR: جميع النماذج فشلت"


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


# ============ الاخبار - محسّن ============
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
                    except:
                        continue
                news_list.sort(key=lambda x: x["minutes_until"])
                return news_list
    except Exception as e:
        print(f"⚠️ فشل جلب الاخبار: {e}")
        return []


async def check_news_and_alert():
    try:
        news_list = await fetch_forex_news()
        now = time.time()
        async with db_lock:
            db["upcoming_news"] = news_list
        blocking_news = []
        warning_news = []
        for news in news_list:
            news_id = news["id"]
            minutes_until = news["minutes_until"]
            # تحذير قبل 30 دقيقة
            if 25 <= minutes_until <= 35:
                async with db_lock:
                    if news_id not in db["news_notified"]:
                        db["news_notified"][news_id] = {"warned": True, "started": False, "ended": False}
                        warning_news.append(news)
            # الاخبار الجارية
            if -30 <= minutes_until <= 30:
                blocking_news.append(news)
                async with db_lock:
                    if news_id in db["news_notified"] and not db["news_notified"][news_id].get("started", False):
                        db["news_notified"][news_id]["started"] = True
                        await send_msg(
                            f"🔴 <b>خبر عاجل الان!</b>\n"
                            f"📰 {news['title']}\n"
                            f"⏰ {news['time'].strftime('%H:%M')} UTC\n"
                            f"⚠️ توقف عن فتح صفقات جديدة لمدة 30 دقيقة"
                        )
            # انتهاء تأثير الخبر
            if minutes_until < -30:
                async with db_lock:
                    if news_id in db["news_notified"] and not db["news_notified"][news_id].get("ended", False):
                        db["news_notified"][news_id]["ended"] = True
                        await send_msg(
                            f"🟢 <b>انتهى تأثير الخبر</b>\n"
                            f"📰 {news['title']}\n"
                            f"✅ يمكن استئناف التداول"
                        )
        # ارسال تحذيرات مجمعة
        if warning_news:
            titles = "\n".join([f"• <b>{n['title']}</b> ({n['time'].strftime('%H:%M')} UTC)" for n in warning_news[:3]])
            await send_msg(
                f"⚠️ <b>تحذير: اخبار عاجلة خلال 30 دقيقة!</b>\n\n"
                f"{titles}\n\n"
                f"🔴 سيتم ايقاف فتح الصفقات الجديدة\n"
                f"⏸️ انتظر حتى تمر الاخبار"
            )
        # تحديث حالة الحظر
        if blocking_news:
            max_block = max([n["minutes_until"] for n in blocking_news])
            block_until = now + (max_block + 30) * 60
            async with db_lock:
                db["news_blocked_until"] = block_until
        else:
            async with db_lock:
                if db["news_blocked_until"] > 0 and now > db["news_blocked_until"]:
                    db["news_blocked_until"] = 0
        # تنظيف الاخبار القديمة
        async with db_lock:
            old_ids = [nid for nid, info in db["news_notified"].items() if info.get("ended", False)]
            for oid in old_ids[:50]:
                if oid in db["news_notified"]:
                    del db["news_notified"][oid]
        return len(blocking_news) > 0
    except Exception as e:
        print(f"❌ خطأ check_news_and_alert: {e}")
        return False


async def is_news_blocking():
    async with db_lock:
        return time.time() < db["news_blocked_until"]


# ============ اشعارات الجلسات ============
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
                            await send_msg(f"🟢 <b>جلسة {session_name} بدأت!</b>\n\nالسوق نشط الان! 🚀")
                if current_hour == end_h and current_minute == 59:
                    async with db_lock:
                        if not db["session_notified"].get(end_key, False):
                            db["session_notified"][end_key] = True
                            await send_msg(f"🔴 <b>جلسة {session_name} انتهت</b>\n\nانتظر الجلسة القادمة! ⏸️")
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
                    await send_msg(f"⚡ <b>تذبذب عالي!</b>\nATR: {atr:.2f} نقاط\nانتبه للمخاطر! 🚨")
                    async with db_lock:
                        db["atr_data"]["last_alert"] = time.time()
            await asyncio.sleep(300)
        except Exception as e:
            print(f"❌ خطأ ATR: {e}")
            await asyncio.sleep(300)


# ============ ملخص الاداء ============
async def generate_performance_summary(period: str = "weekly"):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        now = datetime.now(timezone.utc)
        if period == "weekly":
            period_name = "اسبوعي"
            pips_data = stats.get("weekly_pips", {})
        elif period == "monthly":
            period_name = "شهري"
            pips_data = stats.get("monthly_pips", {})
        else:
            period_name = "يومي"
            pips_data = stats.get("daily_pips", {})
        period_pips = sum(pips_data.values()) if pips_data else stats["total_pips"]
        gemini_calls = db["gemini_calls_today"]
        return f"""
📊 <b>ملخص الاداء {period_name}</b>
📈 الصفقات: {total} | ✅ {stats["wins"]} | ❌ {stats["losses"]}
📉 نسبة الربح: {win_rate:.1f}%
💰 النقاط: {stats["total_pips"]:+.1f} | الفترة: {period_pips:+.1f}
⚖️ المخاطرة: {db["risk_percent"]}%
💵 الرصيد: {db["current_balance"]:,.2f} USD
📈 ربح/خسارة: {(db["current_balance"] - db["initial_balance"]):+,.2f} USD
🤖 استدعاءات Gemini اليوم: {gemini_calls}
        """


# ============ رسم بياني ============
async def generate_equity_chart():
    try:
        import matplotlib
        matplotlib.use("Agg")
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
        ax.plot(dates, balances, linewidth=2, color="#00D26A", marker="o", markersize=4)
        ax.fill_between(dates, balances, initial, alpha=0.3, color="#00D26A")
        ax.axhline(y=initial, color="gray", linestyle="--", alpha=0.5, label="الرصيد الابتدائي")
        ax.set_title("📈 نمو الرصيد", fontsize=16, fontweight="bold", color="white")
        ax.set_xlabel("التاريخ", fontsize=12, color="white")
        ax.set_ylabel("الرصيد (USD)", fontsize=12, color="white")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.xaxis.set_major_locator(mdates.DayLocator())
        plt.xticks(rotation=45)
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_facecolor("#1a1a2e")
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("white")
        plt.tight_layout()
        chart_path = "/tmp/equity_chart.png"
        plt.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
        plt.close()
        return chart_path
    except Exception as e:
        print(f"❌ خطأ رسم بياني: {e}")
        return None


# ============ اوامر Telegram ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 الحالة", callback_data="status"),
         InlineKeyboardButton("💵 السعر", callback_data="price")],
        [InlineKeyboardButton("📈 الاشارة", callback_data="signal"),
         InlineKeyboardButton("📉 الاحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📊 اسبوعي", callback_data="weekly"),
         InlineKeyboardButton("📊 شهري", callback_data="monthly")],
        [InlineKeyboardButton("📈 رسم الرصيد", callback_data="equity_chart"),
         InlineKeyboardButton("⚡ ATR", callback_data="atr")],
        [InlineKeyboardButton("🔍 اخطاء", callback_data="errors"),
         InlineKeyboardButton("🔄 تحليل فوري", callback_data="force_analysis")],
        [InlineKeyboardButton("⏸️ ايقاف", callback_data="pause"),
         InlineKeyboardButton("▶️ استئناف", callback_data="resume")],
    ]
    reply = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 <b>بوت الذهب الذكي v6.0</b>\n\n"
        "✅ الميزات الجديدة:\n"
        "• 🔔 اشعارات اخبار قبل 30 دقيقة\n"
        "• 📡 مراقبة ذكية للصفقات\n"
        "• 🧠 تقليل استخدام Gemini\n"
        "• 📊 تحديثات فقط عند التغيرات المهمة\n\n"
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
        gemini_calls = db["gemini_calls_today"]
        upcoming = len(db["upcoming_news"])
    status = "⏸️ متوقف" if paused else "✅ يعمل"
    trade_status = f"صفقة {active['direction']} نشطة" if active else "لا توجد صفقة"
    news_status = "🔴 موقف" if blocked else "🟢 لا اخبار"
    active_sessions = ", ".join(get_all_active_sessions()) or "خارج الجلسات"
    uptime_str = f"{uptime//3600}h {(uptime%3600)//60}m"
    msg = f"""
📊 <b>حالة البوت v6.0</b>
الحالة: {status}
الجلسات: {active_sessions}
الصفقة: {trade_status}
اشارات: {signals_count} | تحاليل: {analysis_count}
المخاطرة: {risk}% | اخطاء: {errors_count}
الاخبار: {news_status} | قادمة: {upcoming}
ATR: {atr_current:.2f} | DXY: {dxy:.2f}
🤖 Gemini اليوم: {gemini_calls}
⏱️ وقت التشغيل: {uptime_str}
    """
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = await fetch_price()
        dxy = await fetch_dxy_price()
        async with db_lock:
            active = db["active_trade"]
        msg = f"💵 <b>الاسعار</b>\n\n🥇 XAU/USD: <code>{price:,.2f}</code>\n💵 DXY: <code>{dxy:.2f}</code>"
        if active:
            entry = active.get("entry_price", 0)
            direction = active.get("direction", "")
            if entry > 0 and direction:
                pips_diff = (price - entry) * (1 if direction == "BUY" else -1)
                msg += f"\n\n📊 <b>الصفقة النشطة:</b>\n{direction} @ {entry:,.2f}\nP&L: {pips_diff:+.1f} نقاط"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        if not db["signals"]:
            await update.message.reply_text("⏳ لا توجد اشارات بعد")
            return
        last = db["signals"][-1]
    msg = f"📈 <b>آخر اشارة</b>\n\n{last['text']}"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        stats = db["stats"]
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        balance = db["current_balance"]
        initial = db["initial_balance"]
        analysis_count = db["analysis_count"]
        gemini_calls = db["gemini_calls_today"]
    msg = f"""
📉 <b>الاحصائيات</b>
الصفقات: {total} | ✅ {stats["wins"]} | ❌ {stats["losses"]}
الربح: {win_rate:.1f}% | النقاط: {stats["total_pips"]:+.1f}
التحاليل: {analysis_count} | Gemini اليوم: {gemini_calls}
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
    await update.message.reply_text("⏳ جاري انشاء الرسم...")
    chart_path = await generate_equity_chart()
    if chart_path:
        async with db_lock:
            balance = db["current_balance"]
            initial = db["initial_balance"]
        caption = f"📈 <b>نمو الرصيد</b>\nالحالي: <code>{balance:,.2f}</code> USD\nربح/خسارة: <code>{(balance - initial):+,.2f}</code> USD"
        await send_photo(chart_path, caption)
    else:
        await update.message.reply_text("❌ فشل انشاء الرسم")


async def cmd_atr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        atr = db["atr_data"]["current"]
        threshold = db["atr_data"]["threshold"]
    status = "🟢 طبيعي" if atr <= threshold else "🔴 مرتفع"
    await update.message.reply_text(f"⚡ <b>ATR</b>\nالحالي: {atr:.2f}\nالحد: {threshold}\nالحالة: {status}", parse_mode="HTML")


async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        errors = db["api_errors"][-10:]
    if not errors:
        await update.message.reply_text("✅ لا اخطاء")
        return
    msg = "🔍 <b>آخر 10 اخطاء:</b>\n\n"
    for i, err in enumerate(errors, 1):
        msg += f"{i}. [{err['time']}] {err['type']}: {err['error'][:60]}\n"
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
            await update.message.reply_text(f"❌ <b>خطأ:</b>\n{analysis_text}")
            return
        decision, confidence = parse_signal_decision(analysis_text)
        async with db_lock:
            db["analysis_count"] += 1
            db["signals"].append({"text": analysis_text, "time": now_str(), "forced": True})
            if decision == "HOLD":
                db["last_hold_reason"] = analysis_text[:300]
        emoji = "🟢" if decision == "BUY" else "🔴" if decision == "SELL" else "⏸️"
        await send_msg(f"{emoji} <b>تحليل فوري ({decision} - ثقة {confidence}%)</b>\n\n{analysis_text}")
    except Exception as e:
        await update.message.reply_text(f"❌ <b>خطأ:</b>\n{str(e)}")


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
    await update.message.reply_text("⏸️ <b>تم الايقاف</b>", parse_mode="HTML")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        db["paused"] = False
    await update.message.reply_text("▶️ <b>تم الاستئناف</b>", parse_mode="HTML")


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_lock:
        news_list = db["upcoming_news"][:5]
    if not news_list:
        await update.message.reply_text("📰 لا توجد اخبار عاجلة قادمة")
        return
    msg = "📰 <b>الاخبار القادمة:</b>\n\n"
    for news in news_list:
        minutes = news["minutes_until"]
        if minutes > 0:
            time_str = f"خلال {int(minutes)} دقيقة"
        elif minutes > -60:
            time_str = "جارية الان!"
        else:
            time_str = "انتهت"
        msg += f"• <b>{news['title']}</b>\n  ⏰ {time_str} ({news['time'].strftime('%H:%M')} UTC)\n\n"
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
🤖 <b>الاوامر</b>
/start - القائمة
/status - الحالة
/price - الاسعار
/signal - آخر اشارة
/stats - الاحصائيات
/weekly - اسبوعي
/monthly - شهري
/equity - رسم بياني
/atr - ATR
/errors - الاخطاء
/force - تحليل فوري
/news - الاخبار القادمة
/risk - المخاطرة
/pause - ايقاف
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
        await query.message.reply_text("⏸️ تم الايقاف")
    elif query.data == "resume":
        async with db_lock:
            db["paused"] = False
        await query.message.reply_text("▶️ تم الاستئناف")


# ============ مراقبة الصفقات - الجديد ============
async def trade_monitor_coro():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(5)
                    continue
                active_trade = db["active_trade"]
            if not active_trade:
                await asyncio.sleep(TRADE_MONITOR_INTERVAL)
                continue
            current_price = await fetch_price()
            async with db_lock:
                trade = db["active_trade"]
                if not trade:
                    await asyncio.sleep(TRADE_MONITOR_INTERVAL)
                    continue
                direction = trade.get("direction", "")
                entry = trade.get("entry_price", 0)
                sl_pips = trade.get("sl_pips", 0)
                tp1_pips = trade.get("tp1_pips", 0)
                tp2_pips = trade.get("tp2_pips", 0)
                if entry == 0:
                    await asyncio.sleep(TRADE_MONITOR_INTERVAL)
                    continue
                if direction == "BUY":
                    pnl_pips = current_price - entry
                else:
                    pnl_pips = entry - current_price
                db["trade_last_pnl"] = pnl_pips
                if pnl_pips > db["trade_high_pnl"]:
                    db["trade_high_pnl"] = pnl_pips
                if pnl_pips < db["trade_low_pnl"]:
                    db["trade_low_pnl"] = pnl_pips
                reached_tp1 = False
                reached_tp2 = False
                hit_sl = False
                if direction == "BUY":
                    if tp1_pips > 0 and pnl_pips >= tp1_pips:
                        reached_tp1 = True
                    if tp2_pips > 0 and pnl_pips >= tp2_pips:
                        reached_tp2 = True
                    if sl_pips > 0 and pnl_pips <= -sl_pips:
                        hit_sl = True
                else:
                    if tp1_pips > 0 and pnl_pips >= tp1_pips:
                        reached_tp1 = True
                    if tp2_pips > 0 and pnl_pips >= tp2_pips:
                        reached_tp2 = True
                    if sl_pips > 0 and pnl_pips <= -sl_pips:
                        hit_sl = True
                last_update = db["trade_last_update"]
                time_since_update = time.time() - last_update
                should_notify = False
                notify_msg = ""
                if hit_sl:
                    db["stats"]["losses"] += 1
                    db["stats"]["total_pips"] += pnl_pips
                    db["active_trade"] = None
                    db["trade_last_update"] = time.time()
                    notify_msg = (
                        f"🔴 <b>تم اغلاق الصفقة - وقف الخسارة</b>\n\n"
                        f"{direction} @ {entry:,.2f}\n"
                        f"الخروج: {current_price:,.2f}\n"
                        f"الخسارة: {pnl_pips:+.1f} نقاط 😔"
                    )
                    should_notify = True
                elif reached_tp2:
                    db["stats"]["wins"] += 1
                    db["stats"]["total_pips"] += pnl_pips
                    db["active_trade"] = None
                    db["trade_last_update"] = time.time()
                    notify_msg = (
                        f"🎯🎯 <b>تم اغلاق الصفقة - الهدف الثاني!</b>\n\n"
                        f"{direction} @ {entry:,.2f}\n"
                        f"الخروج: {current_price:,.2f}\n"
                        f"الربح: {pnl_pips:+.1f} نقاط 🎉🎉"
                    )
                    should_notify = True
                elif reached_tp1 and not trade.get("tp1_notified", False):
                    trade["tp1_notified"] = True
                    db["trade_last_update"] = time.time()
                    notify_msg = (
                        f"🎯 <b>الهدف الاول تم الوصول!</b>\n\n"
                        f"{direction} @ {entry:,.2f}\n"
                        f"السعر الحالي: {current_price:,.2f}\n"
                        f"الربح: {pnl_pips:+.1f} نقاط\n\n"
                        f"💡 يمكنك:\n"
                        f"• نقل SL لنقطة الدخول (Break Even)\n"
                        f"• الانتظار للهدف الثاني: {tp2_pips:.1f} نقاط"
                    )
                    should_notify = True
                elif time_since_update > 300:
                    db["trade_last_update"] = time.time()
                    high = db["trade_high_pnl"]
                    low = db["trade_low_pnl"]
                    status_emoji = "🟢" if pnl_pips > 0 else "🔴" if pnl_pips < 0 else "⚪"
                    notify_msg = (
                        f"{status_emoji} <b>تحديث الصفقة</b>\n\n"
                        f"{direction} @ {entry:,.2f}\n"
                        f"السعر: {current_price:,.2f}\n"
                        f"الربح: {pnl_pips:+.1f} نقاط\n"
                        f"📈 اعلى: {high:+.1f} | 📉 ادنى: {low:+.1f}\n"
                        f"🎯 TP1: {tp1_pips:.1f} | 🎯🎯 TP2: {tp2_pips:.1f} | 🛑 SL: {sl_pips:.1f}"
                    )
                    should_notify = True
                price_buffer = db["price_change_buffer"]
                price_buffer.append({"price": current_price, "time": time.time()})
                cutoff = time.time() - 60
                price_buffer[:] = [p for p in price_buffer if p["time"] > cutoff]
                if len(price_buffer) >= 2:
                    recent_change = abs(current_price - price_buffer[0]["price"])
                    if recent_change >= SIGNIFICANT_MOVE_PIPS and time_since_update > 60:
                        db["trade_last_update"] = time.time()
                        direction_arrow = "📈" if current_price > price_buffer[0]["price"] else "📉"
                        notify_msg = (
                            f"{direction_arrow} <b>تحرك سريع!</b>\n\n"
                            f"{direction} @ {entry:,.2f}\n"
                            f"السعر: {current_price:,.2f}\n"
                            f"التغير: {recent_change:+.1f} نقاط في آخر دقيقة\n"
                            f"الربح الحالي: {pnl_pips:+.1f} نقاط"
                        )
                        should_notify = True
            if should_notify and notify_msg:
                await send_msg(notify_msg)
                print(f"📊 [trade_monitor] اشعار مرسل: {notify_msg[:50]}...")
            await asyncio.sleep(TRADE_MONITOR_INTERVAL)
        except Exception as e:
            print(f"❌ خطأ trade_monitor: {e}")
            await asyncio.sleep(TRADE_MONITOR_INTERVAL)


# ============ محلل الفرص - محسّن ============
async def opportunity_analyzer_coro():
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(5)
                    continue
                has_trade = db["active_trade"] is not None
                last_analysis = db["last_analysis_ts"]
                last_price = db["last_sent_price"]
                last_session = db["last_session_analysis"]
            if has_trade:
                await asyncio.sleep(10)
                continue
            news_blocking = await is_news_blocking()
            if news_blocking:
                await asyncio.sleep(60)
                continue
            if not is_valid_session():
                await asyncio.sleep(60)
                continue
            current_session = get_session_name()
            current_price = await fetch_price()
            current_dxy = await fetch_dxy_price()
            should_analyze = False
            reason = ""
            if last_price > 0 and abs(current_price - last_price) >= SIGNIFICANT_MOVE_PIPS:
                should_analyze = True
                reason = f"تغير سعري كبير ({abs(current_price - last_price):.1f} نقاط)"
            elapsed = time.time() - last_analysis
            if elapsed >= 600:
                should_analyze = True
                reason = f"مرور {elapsed/60:.0f} دقيقة على آخر تحليل"
            if current_session != last_session and current_session != "خارج الجلسات ⏸️":
                should_analyze = True
                reason = f"بداية جلسة {current_session}"
                async with db_lock:
                    db["last_session_analysis"] = current_session
            if should_analyze:
                print(f"🔍 [opportunity] سبب التحليل: {reason}")
                tf_data = await fetch_all_tf()
                missing = [k for k, v in tf_data.items() if not v]
                if missing:
                    print(f"⚠️ [opportunity] بيانات ناقصة: {missing}")
                    await asyncio.sleep(30)
                    continue
                analysis_text = await analyze_gemini(tf_data, current_dxy)
                if analysis_text.startswith("ERROR"):
                    print(f"❌ [opportunity] Gemini خطأ: {analysis_text}")
                    await asyncio.sleep(60)
                    continue
                decision, confidence = parse_signal_decision(analysis_text)
                trade_details = parse_trade_details(analysis_text)
                async with db_lock:
                    db["last_analysis_ts"] = time.time()
                    db["last_sent_price"] = current_price
                    db["analysis_count"] += 1
                    db["signals"].append({"text": analysis_text, "time": now_str()})
                    if decision == "HOLD":
                        db["last_hold_reason"] = analysis_text[:300]
                if decision in ["BUY", "SELL"] and confidence >= MIN_CONFIDENCE:
                    emoji = "🟢" if decision == "BUY" else "🔴"
                    async with db_lock:
                        db["active_trade"] = {
                            "direction": decision,
                            "entry_price": current_price,
                            "sl_pips": trade_details["sl_pips"],
                            "tp1_pips": trade_details["tp1_pips"],
                            "tp2_pips": trade_details["tp2_pips"],
                            "rr": trade_details["rr"],
                            "duration": trade_details["duration"],
                            "confidence": confidence,
                            "analysis": analysis_text,
                            "open_time": time.time(),
                            "tp1_notified": False,
                        }
                        db["trade_last_update"] = time.time()
                        db["trade_entry_price"] = current_price
                        db["trade_last_pnl"] = 0
                        db["trade_high_pnl"] = 0
                        db["trade_low_pnl"] = 0
                    await send_msg(
                        f"{emoji} <b>اشارة {decision} (ثقة {confidence}%)</b>\n\n"
                        f"{analysis_text}\n\n"
                        f"📊 <b>تم فتح الصفقة:</b>\n"
                        f"الدخول: {current_price:,.2f}\n"
                        f"🛑 SL: {trade_details['sl_pips']:.1f} نقاط\n"
                        f"🎯 TP1: {trade_details['tp1_pips']:.1f} نقاط\n"
                        f"🎯🎯 TP2: {trade_details['tp2_pips']:.1f} نقاط"
                    )
                    print(f"✅ [opportunity] صفقة جديدة: {decision} @ {current_price}")
                elif decision in ["BUY", "SELL"] and confidence < MIN_CONFIDENCE:
                    if elapsed >= ANALYSIS_INTERVAL:
                        await send_msg(
                            f"⏸️ <b>فرصة ضعيفة</b> ({decision} - ثقة {confidence}%)\n"
                            f"الحد: {MIN_CONFIDENCE}%\n"
                            f"السبب: {reason}"
                        )
                    print(f"⏸️ [opportunity] ثقة منخفضة: {confidence}%")
                else:
                    async with db_lock:
                        count = db["analysis_count"]
                    if count % 3 == 0 and elapsed >= ANALYSIS_INTERVAL:
                        await send_msg(
                            f"⏸️ <b>لا فرص واضحة (HOLD)</b>\n"
                            f"تحاليل: {count} | الجلسة: {current_session}\n"
                            f"السعر: {current_price:,.2f} | DXY: {current_dxy:.2f}"
                        )
                    print(f"⏸️ [opportunity] HOLD - {reason}")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"❌ خطأ opportunity_analyzer: {e}")
            await asyncio.sleep(30)


# ============ الحلقات الرئيسية (محمية) ============
async def safe_loop(name: str, coro_func, interval: int = 60):
    while True:
        try:
            await coro_func()
        except asyncio.CancelledError:
            print(f"⚠️ {name} تم الغاؤه")
            break
        except Exception as e:
            tb = traceback.format_exc()
            print(f"❌ {name} تعطل: {e}\n{tb}")
            try:
                await send_msg(f"⚠️ <b>تنبيه:</b> حلقة {name} تعطلت وسيتم اعادة تشغيلها\n<code>{str(e)[:100]}</code>")
            except:
                pass
            await asyncio.sleep(interval)


async def monitor_coro():
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


async def news_coro():
    """حلقة فحص الاخبار المنفصلة"""
    while True:
        try:
            async with db_lock:
                if db["paused"]:
                    await asyncio.sleep(60)
                    continue
            await check_news_and_alert()
            await asyncio.sleep(NEWS_CHECK_INTERVAL)
        except Exception as e:
            print(f"❌ خطأ news_coro: {e}")
            await asyncio.sleep(NEWS_CHECK_INTERVAL)


async def report_coro():
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
            gemini_calls = db["gemini_calls_today"]
            db["gemini_calls_today"] = 0
        await send_msg(
            f"📅 <b>التقرير اليومي</b>\n"
            f"النقاط: {stats['total_pips']:+.1f}\n"
            f"المخاطرة: {risk}%\n"
            f"الرصيد: {balance:,.2f} USD\n"
            f"ربح/خسارة: {(balance - initial):+,.2f} USD\n"
            f"🤖 استدعاءات Gemini: {gemini_calls}"
        )


async def session_coro():
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
        except Exception as e:
            print(f"❌ خطأ session_coro: {e}")
            await asyncio.sleep(30)


async def atr_coro():
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
                    await send_msg(f"⚡ <b>تذبذب عالي!</b> ATR: {atr:.2f} نقاط 🚨")
                    async with db_lock:
                        db["atr_data"]["last_alert"] = time.time()
            await asyncio.sleep(300)
        except Exception as e:
            print(f"❌ خطأ atr_coro: {e}")
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
    application.add_handler(CommandHandler("news", cmd_news))
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
        f"🚀 <b>بوت الذهب يعمل! v6.0</b>\n\n"
        f"⏰ الجلسة: {get_session_name()}\n"
        f"🤖 النموذج: {GEMINI_MODEL}\n"
        f"📡 مراقبة ذكية للصفقات\n"
        f"🔔 اشعارات اخبار قبل 30 دقيقة\n"
        f"🧠 تقليل استخدام Gemini\n\n"
        f"استخدم /force لتحليل فوري"
    )

    tasks = [
        asyncio.create_task(safe_loop("monitor", monitor_coro, 10)),
        asyncio.create_task(safe_loop("opportunity", opportunity_analyzer_coro, 10)),
        asyncio.create_task(safe_loop("trade_monitor", trade_monitor_coro, 10)),
        asyncio.create_task(safe_loop("news", news_coro, 60)),
        asyncio.create_task(safe_loop("report", report_coro, 3600)),
        asyncio.create_task(safe_loop("session", session_coro, 30)),
        asyncio.create_task(safe_loop("atr", atr_coro, 300)),
    ]
    
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
