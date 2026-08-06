"""
Gold Scalp AI Monitor v4 - Railway Edition
========================================================================
- asyncio بدل threading
- بدون STATE_FILE (Railway filesystem مؤقت)
- جدولة بـ asyncio
"""

import os
import json
import asyncio
import aiohttp
from datetime import datetime, timezone

# ============ الإعدادات من متغيرات البيئة ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SYMBOL = "XAU/USD"
MONITOR_INTERVAL_SECONDS = 15
ANALYSIS_INTERVAL_SECONDS = 180
MIN_CONFIDENCE_TO_ALERT = 75
GEMINI_MODEL = "gemini-1.5-flash"  # الموديل المتاح حالياً
PIP_VALUE = 1.0

TIMEFRAMES = {
    "M30": ("30min", 50),
    "M15": ("15min", 60),
    "M5": ("5min", 100),
    "M1": ("1min", 60),
}

LONDON_SESSION = (7, 16)
NEW_YORK_SESSION = (12, 21)

# حالة البوت في الذاكرة (Railway filesystem مؤقت)
state = {
    "active_trade": None,
    "last_analysis_ts": 0,
}
state_lock = asyncio.Lock()

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


def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def is_valid_trading_session():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    in_london = LONDON_SESSION[0] <= hour < LONDON_SESSION[1]
    in_ny = NEW_YORK_SESSION[0] <= hour < NEW_YORK_SESSION[1]
    return in_london or in_ny


async def send_telegram_message(session: aiohttp.ClientSession, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()


async def fetch_current_price(session: aiohttp.ClientSession):
    url = "https://api.twelvedata.com/quote"
    params = {"symbol": SYMBOL, "apikey": TWELVE_DATA_API_KEY}
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        data = await resp.json()
        if "close" not in data:
            raise RuntimeError(f"خطأ Twelve Data (quote): {data}")
        return float(data["close"])


async def fetch_timeframe(session: aiohttp.ClientSession, interval: str, outputsize: int):
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": SYMBOL, "interval": interval, "outputsize": outputsize, "apikey": TWELVE_DATA_API_KEY}
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        data = await resp.json()
        if "values" not in data:
            raise RuntimeError(f"خطأ Twelve Data ({interval}): {data}")
        return data["values"]


async def fetch_all_timeframes(session: aiohttp.ClientSession):
    result = {}
    for label, (interval, size) in TIMEFRAMES.items():
        result[label] = await fetch_timeframe(session, interval, size)
        await asyncio.sleep(1)  # تجنب rate limit
    return result


async def analyze_with_gemini(session: aiohttp.ClientSession, tf_data: dict):
    prompt_text = GOLD_SCALP_PROMPT.format(
        data_m30=json.dumps(tf_data["M30"]),
        data_m15=json.dumps(tf_data["M15"]),
        data_m5=json.dumps(tf_data["M5"]),
        data_m1=json.dumps(tf_data["M1"]),
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"maxOutputTokens": 6000}
    }
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
        result = await resp.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)


async def open_new_trade(session: aiohttp.ClientSession, analysis: dict, current_price: float):
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

    emoji = "🟢" if direction == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>إشارة جديدة {direction} - ذهب</b>\n\n"
        f"الدخول: {entry}\n"
        f"الثقة: {trade['confidence']}%\n"
        f"SL: {trade['sl_price']:.2f}\n"
        f"TP1: {trade['tp1_price']:.2f} | TP2: {trade['tp2_price']:.2f}\n"
        f"الحالة: {analysis.get('kill_zone_status', '-')}\n\n"
        f"<b>الملخص:</b>\n{trade['summary']}\n\n"
        f"🕐 {trade['opened_at']}"
    )
    await send_telegram_message(session, msg)
    print(f"  🆕 صفقة جديدة: {direction} @ {entry}")
    return trade


async def check_trade_hit(trade: dict, current_price: float):
    direction = trade["direction"]
    sign = 1 if direction == "BUY" else -1
    if (current_price - trade["sl_price"]) * sign <= 0:
        return True, "sl"
    if (current_price - trade["tp2_price"]) * sign >= 0:
        return True, "tp2"
    if (current_price - trade["tp1_price"]) * sign >= 0:
        return True, "tp1"
    return False, None


async def notify_trade_closed(session: aiohttp.ClientSession, trade: dict, current_price: float, reason: str):
    direction = trade["direction"]
    if reason == "sl":
        msg = (
            f"❌ <b>تم ضرب وقف الخسارة - {direction}</b>\n\n"
            f"السعر الحالي: {current_price}\nالدخول: {trade['entry']}\n\n"
            f"جاري البحث عن فرصة جديدة...\n🕐 {now_str()}"
        )
    elif reason == "tp2":
        msg = (
            f"🎯 <b>تحقق الهدف الثاني (TP2) - {direction}</b>\n\n"
            f"السعر الحالي: {current_price}\nالدخول: {trade['entry']}\n\n"
            f"الصفقة اكتملت ✅ جاري البحث عن فرصة جديدة...\n🕐 {now_str()}"
        )
    else:  # tp1
        msg = (
            f"✅ <b>تحقق الهدف الأول (TP1) - {direction}</b>\n\n"
            f"السعر الحالي: {current_price}\nالدخول: {trade['entry']}\n\n"
            f"جاري إعادة تحليل السوق فورًا...\n🕐 {now_str()}"
        )
    await send_telegram_message(session, msg)


async def price_monitor_loop(session: aiohttp.ClientSession):
    """مراقبة السعر - تفحص كل 15 ثانية"""
    while True:
        try:
            async with state_lock:
                trade = state.get("active_trade")

            if trade is not None:
                current_price = await fetch_current_price(session)
                print(f"[مراقبة {now_str()}] {trade['direction']} | السعر: {current_price}")

                should_close, reason = await check_trade_hit(trade, current_price)
                if should_close:
                    await notify_trade_closed(session, trade, current_price, reason)
                    async with state_lock:
                        state["active_trade"] = None
                        state["last_analysis_ts"] = 0
                    print(f"  🔒 أُغلقت ({reason})")

            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

        except Exception as e:
            print(f"  ❌ خطأ بمراقبة السعر: {e}")
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)


async def analysis_loop(session: aiohttp.ClientSession):
    """تحليل Gemini - كل 3 دقائق"""
    while True:
        try:
            async with state_lock:
                has_trade = state.get("active_trade") is not None
                elapsed = time.time() - state.get("last_analysis_ts", 0)

            if not has_trade and elapsed >= ANALYSIS_INTERVAL_SECONDS:
                if not is_valid_trading_session():
                    print(f"[تحليل {now_str()}] خارج الجلسات - تخطي")
                    async with state_lock:
                        state["last_analysis_ts"] = time.time()
                else:
                    print(f"[تحليل {now_str()}] جاري التحليل...")
                    tf_data = await fetch_all_timeframes(session)
                    current_price = await fetch_current_price(session)
                    analysis = await analyze_with_gemini(session, tf_data)
                    decision = analysis["final_decision"]
                    confidence = float(analysis["confidence_score"])
                    print(f"  القرار: {decision} | الثقة: {confidence}%")

                    async with state_lock:
                        state["last_analysis_ts"] = time.time()
                        if decision in ("BUY", "SELL") and confidence >= MIN_CONFIDENCE_TO_ALERT:
                            state["active_trade"] = await open_new_trade(session, analysis, current_price)
                        else:
                            print("  ⏸️ HOLD أو ثقة منخفضة")

            await asyncio.sleep(5)

        except Exception as e:
            print(f"  ❌ خطأ بالتحليل: {e}")
            await asyncio.sleep(5)


async def main():
    print("🚀 بدء تشغيل نظام مراقبة الذهب v4 (Railway Edition)...")
    
    # إشعار بدء التشغيل
    async with aiohttp.ClientSession() as session:
        await send_telegram_message(session, "🚀 <b>بوت الذهب يعمل الآن!</b>\nجاري مراقبة السوق...")
        
        # تشغيل المهمتين معاً
        await asyncio.gather(
            price_monitor_loop(session),
            analysis_loop(session)
        )


if __name__ == "__main__":
    asyncio.run(main())
