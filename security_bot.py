"""
Security Bot v2.0 - بوت إدارة الأمان (نسخة محسّنة بالعربية)
========================================================================
- تنظيف الإدخال تلقائياً
- إضافة مستخدم بالرد على رسالته
- أزرار تفاعلية للإدارة
- تأكيد قبل الحذف
- رسائل توجيهية أوضح
"""

import os
import sys
import asyncio
import asyncpg
import logging
import re
import csv
import io
import time
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ============ الإعدادات ============
SECURITY_BOT_TOKEN = os.environ.get("SECURITY_BOT_TOKEN")
# يدعم عدة مشرفين: ADMIN_USER_IDS="111,222,333" (أو ADMIN_USER_ID القديم لمشرف واحد)
_admin_raw = os.environ.get("ADMIN_USER_IDS", "") or os.environ.get("ADMIN_USER_ID", "")
ADMIN_USER_IDS = set(x.strip() for x in _admin_raw.split(",") if x.strip())
DATABASE_URL = os.environ.get("DATABASE_URL")  # اتصال Postgres خارجي (Neon/Supabase/أي مزود) - مشترك مع بوت التداول
# يظهر للمستخدم غير المصرح كطريقة تواصل مع المشرف، مثلا: @my_username
ADMIN_CONTACT = os.environ.get("ADMIN_CONTACT", "")

_unauth_alert_cooldown = {}  # user_id -> آخر وقت تم تنبيه المشرف فيه، لمنع الإزعاج المتكرر

pg_pool: "asyncpg.Pool | None" = None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("SECURITY BOT v2.0 STARTING")
logger.info(f"DATABASE_URL set: {bool(DATABASE_URL)}")
logger.info(f"Admin count: {len(ADMIN_USER_IDS)}")
logger.info(f"SECURITY_BOT_TOKEN set: {bool(SECURITY_BOT_TOKEN)}")
logger.info("=" * 50)

# ============ دوال قاعدة البيانات (Postgres مشترك مع بوت التداول) ============

async def init_db():
    global pg_pool
    logger.info("Initializing Postgres pool...")
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set! Exiting.")
        raise RuntimeError("DATABASE_URL غير مضبوط - البوت يحتاج قاعدة بيانات Postgres خارجية للعمل")
    try:
        pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS authorized_users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    added_at TIMESTAMP DEFAULT NOW(),
                    added_by TEXT,
                    expires_at TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id SERIAL PRIMARY KEY,
                    action TEXT NOT NULL,
                    user_id TEXT,
                    actor_id TEXT,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        logger.info("Postgres DB initialized successfully (shared with trading bot)")
    except Exception as e:
        logger.error(f"DB init error: {e}")
        raise

def is_admin(user_id) -> bool:
    return str(user_id) in ADMIN_USER_IDS

async def log_activity(action, user_id=None, actor_id=None, note=None):
    try:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO activity_log (action, user_id, actor_id, note) VALUES ($1, $2, $3, $4)",
                action, str(user_id) if user_id else None, str(actor_id) if actor_id else None, note
            )
    except Exception as e:
        logger.error(f"Activity log error: {e}")

async def get_activity_log(limit=15):
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, user_id, actor_id, note, created_at FROM activity_log ORDER BY id DESC LIMIT $1",
            limit
        )
    return [(r["action"], r["user_id"], r["actor_id"], r["note"], r["created_at"]) for r in rows]

async def is_authorized(user_id) -> bool:
    if is_admin(user_id):
        return True
    try:
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT expires_at FROM authorized_users WHERE user_id = $1", str(user_id))
        if row is None:
            return False
        expires_at = row["expires_at"]
        if expires_at and expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
            return False
        return True
    except Exception as e:
        logger.error(f"Auth check error: {e}")
        return False

def contact_admin_text() -> str:
    if ADMIN_CONTACT:
        return f"تواصل مع المشرف: {ADMIN_CONTACT}"
    return "تواصل مع المشرف للحصول على الصلاحية."

async def alert_admins_unauthorized(context: ContextTypes.DEFAULT_TYPE, user_id, username, first_name):
    """ينبّه كل المشرفين بمحاولة دخول غير مصرح على بوت الأمان نفسه، مع زر اضافة سريع (كل 10 دقائق كحد أقصى لنفس المستخدم)"""
    if not ADMIN_USER_IDS:
        return
    now = time.time()
    last = _unauth_alert_cooldown.get(str(user_id), 0)
    if now - last < 600:
        return
    _unauth_alert_cooldown[str(user_id)] = now

    display_name = first_name or (f"@{username}" if username else f"مستخدم {user_id}")
    text = f"🚨 محاولة دخول غير مصرحة (بوت الأمان)\n\nالاسم: {display_name}\nالمعرف: {user_id}"
    if username:
        text += f"\nاليوزر: @{username}"
    keyboard = [[InlineKeyboardButton("✅ اضافة فورية", callback_data=f"quickadd_{user_id}")]]
    for admin_id in ADMIN_USER_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logger.warning(f"Admin alert failed for {admin_id}: {e}")

async def add_user(user_id, username=None, first_name=None, added_by=None, expires_at=None):
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO authorized_users (user_id, username, first_name, added_by, expires_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name,
                added_by=excluded.added_by, expires_at=excluded.expires_at
        """, str(user_id), username, first_name, str(added_by) if added_by else None, expires_at)
    note = f"مؤقت حتى {expires_at}" if expires_at else "دائم"
    await log_activity("added", user_id, added_by, note)

async def remove_user(user_id, removed_by=None, note=None):
    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM authorized_users WHERE user_id = $1", str(user_id))
    await log_activity("removed", user_id, removed_by, note)

async def get_expired_users():
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, first_name, expires_at FROM authorized_users WHERE expires_at IS NOT NULL")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = []
    for row in rows:
        if row["expires_at"] and row["expires_at"] <= now:
            expired.append((row["user_id"], row["username"], row["first_name"]))
    return expired

async def get_users():
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, first_name, added_at, expires_at FROM authorized_users ORDER BY added_at DESC")
    return [(r["user_id"], r["username"], r["first_name"], r["added_at"], r["expires_at"]) for r in rows]

async def get_user_count():
    async with pg_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM authorized_users")
    return count

# ============ دوال مساعدة ============

def clean_user_id(text: str) -> str:
    """تنظيف معرف المستخدم من الرموز الزائدة"""
    if not text:
        return ""
    text = text.lstrip("@")
    text = text.rstrip("/")
    text = text.strip()
    cleaned = re.sub(r"[^0-9]", "", text)
    return cleaned

def format_user_info(user_id, username=None, first_name=None) -> str:
    """تنسيق معلومات المستخدم للعرض"""
    parts = [f"ID: {user_id}"]
    if first_name:
        parts.append(f"الاسم: {first_name}")
    if username:
        parts.append(f"@{username}")
    return " | ".join(parts)

# ============ الأوامر ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /start from user {update.effective_user.id}")
    user = update.effective_user
    user_id = user.id
    
    if is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("+ اضافة مستخدم", callback_data="menu_add")],
            [InlineKeyboardButton("حذف مستخدم", callback_data="menu_remove")],
            [InlineKeyboardButton("قائمة المستخدمين", callback_data="menu_users")],
            [InlineKeyboardButton("التحقق من مستخدم", callback_data="menu_check")],
            [InlineKeyboardButton("📋 سجل النشاط", callback_data="menu_log"),
             InlineKeyboardButton("📊 تصدير CSV", callback_data="menu_export")],
            [InlineKeyboardButton("📢 بث جماعي", callback_data="menu_broadcast")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "بوت ادارة الامان v2.0" + "\n\n" +
            f"مرحبا المشرف {user.first_name}!" + "\n" +
            f"معرفك: {user_id}" + "\n\n" +
            "اختر خيارا من الازرار:"
        )
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        text = (
            "بوت ادارة الامان" + "\n\n" +
            f"مرحبا {user.first_name}!" + "\n" +
            f"معرفك: {user_id}" + "\n\n" +
            "الاوامر:" + "\n" +
            "/id - عرض معرفك" + "\n" +
            "/check - التحقق من صلاحيتك"
        )
        if await is_authorized(user_id):
            text += "\n\n" + "انت مصرح لاستخدام بوت التداول!"
            await update.message.reply_text(text)
        else:
            text += "\n\n" + contact_admin_text()
            await update.message.reply_text(text)
            await alert_admins_unauthorized(context, user_id, user.username, user.first_name)

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = "معرفك:" + "\n" + str(user.id) + "\n\n" + "ارسل هذا المعرف للمشرف لتفعيل حسابك."
    await update.message.reply_text(msg)

def parse_duration_days(args, used_slots=0):
    """يبحث عن رقم أيام اختياري في نهاية args. يرجع (days_or_None, remaining_args)"""
    if len(args) > used_slots:
        try:
            days = int(args[used_slots])
            if days > 0:
                return days, args[:used_slots]
        except ValueError:
            pass
    return None, args

async def adduser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    # الحالة 1: بالرد على رسالة المستخدم (اختياري: /adduser <ايام>)
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = str(target_user.id)
        target_username = target_user.username
        target_first_name = target_user.first_name
        
        days, _ = parse_duration_days(context.args, used_slots=0)
        expires_at = None
        expiry_note = ""
        if days:
            expires_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)
            expires_at = expires_dt.isoformat()
            expiry_note = f"\n⏳ صلاحية مؤقتة: {days} يوم (حتى {expires_dt.strftime('%Y-%m-%d %H:%M')} UTC)"
        
        if await is_authorized(target_id):
            await update.message.reply_text(
                "المستخدم موجود مسبقا!" + "\n\n" +
                format_user_info(target_id, target_username, target_first_name)
            )
            return
        
        await add_user(target_id, target_username, target_first_name, user.id, expires_at)
        
        await update.message.reply_text(
            "تمت الاضافة!" + "\n\n" +
            format_user_info(target_id, target_username, target_first_name) + "\n\n" +
            "يمكنه الان استخدام بوت التداول." + expiry_note
        )
        
        try:
            notify_msg = (
                "تم تفعيل حسابك!" + "\n\n" +
                "لديك الان صلاحية استخدام بوت التداول." + "\n" +
                "اضغط /start في بوت التداول للبدء." + expiry_note
            )
            await context.bot.send_message(chat_id=target_id, text=notify_msg)
        except Exception as e:
            logger.warning(f"Notify error: {e}")
            await update.message.reply_text("لم استطع ارسال اشعار للمستخدم")
        return
    
    # الحالة 2: كتابة المعرف مباشرة (اختياري: /adduser <id> <ايام>)
    if not context.args:
        await update.message.reply_text(
            "الاستخدام:" + "\n\n" +
            "الاسهل: بالرد على رسالة المستخدم واكتب /adduser" + "\n\n" +
            "او اكتب المعرف: /adduser 123456789" + "\n" +
            "صلاحية مؤقتة: /adduser 123456789 7  (7 ايام)"
        )
        return
    
    raw_id = context.args[0]
    target_id = clean_user_id(raw_id)
    days, _ = parse_duration_days(context.args, used_slots=1)
    
    if not target_id:
        await update.message.reply_text(
            "معرف غير صالح!" + "\n\n" +
            f"المدخل: {raw_id}" + "\n" +
            "المعرف يجب ان يكون ارقاما فقط." + "\n\n" +
            "جرب الطريقة السهلة: بالرد على رسالة المستخدم واكتب /adduser"
        )
        return
    
    try:
        int(target_id)
    except ValueError:
        await update.message.reply_text("المعرف يجب ان يكون رقما!")
        return
    
    if await is_authorized(target_id):
        await update.message.reply_text(f"المستخدم {target_id} موجود مسبقا.")
        return
    
    expires_at = None
    expiry_note = ""
    if days:
        expires_dt = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)
        expires_at = expires_dt.isoformat()
        expiry_note = f"\n⏳ صلاحية مؤقتة: {days} يوم (حتى {expires_dt.strftime('%Y-%m-%d %H:%M')} UTC)"
    
    await add_user(target_id, added_by=user.id, expires_at=expires_at)
    
    await update.message.reply_text(
        "تمت الاضافة!" + "\n\n" +
        f"المستخدم: {target_id}" + "\n" +
        "يمكنه الان استخدام بوت التداول." + expiry_note
    )
    
    try:
        notify_msg = (
            "تم تفعيل حسابك!" + "\n\n" +
            "لديك الان صلاحية استخدام بوت التداول." + "\n" +
            "اضغط /start في بوت التداول للبدء." + expiry_note
        )
        await context.bot.send_message(chat_id=target_id, text=notify_msg)
    except Exception as e:
        logger.warning(f"Notify error: {e}")

async def removeuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    if not context.args:
        await update.message.reply_text(
            "الاستخدام: /removeuser 123456789" + "\n\n" +
            "او استخدم زر حذف مستخدم من القائمة الرئيسية."
        )
        return
    
    raw_id = context.args[0]
    target_id = clean_user_id(raw_id)
    
    if not target_id:
        await update.message.reply_text(f"معرف غير صالح! المدخل: {raw_id}")
        return
    
    if not await is_authorized(target_id):
        await update.message.reply_text(f"المستخدم {target_id} غير موجود.")
        return
    
    if is_admin(target_id):
        await update.message.reply_text("لا يمكن حذف المشرف!")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("نعم احذف", callback_data=f"confirm_remove_{target_id}"),
            InlineKeyboardButton("الغاء", callback_data="cancel_remove")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "تأكيد الحذف" + "\n\n" +
        f"هل انت متأكد من حذف المستخدم {target_id}?" + "\n\n" +
        "سيتم الغاء صلاحيته فورا.",
        reply_markup=reply_markup
    )
async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    users = await get_users()
    count = await get_user_count()
    
    if not users:
        await update.message.reply_text("لا يوجد مستخدمون مصرح لهم.")
        return
    
    lines_list = [f"المستخدمون المصرح لهم ({count}):", ""]
    
    for idx, (uid, username, first_name, added_at, expires_at) in enumerate(users, 1):
        name_display = first_name or (f"@{username}" if username else f"مستخدم {uid}")
        lines_list.append(f"{idx}. {name_display}")
        lines_list.append(f"   المعرف: {uid}")
        lines_list.append(f"   تاريخ الاضافة: {added_at}")
        if expires_at:
            lines_list.append(f"   ⏳ تنتهي: {expires_at}")
        lines_list.append("")
    
    keyboard = [
        [InlineKeyboardButton("اضافة مستخدم جديد", callback_data="menu_add")],
        [InlineKeyboardButton("تحديث القائمة", callback_data="menu_users")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("\n".join(lines_list), reply_markup=reply_markup)

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if context.args:
        if not is_admin(user.id):
            await update.message.reply_text("هذا الامر للمشرف فقط!")
            return
        
        raw_id = context.args[0]
        target_id = clean_user_id(raw_id)
        
        if not target_id:
            await update.message.reply_text("معرف غير صالح!")
            return
        
        if is_admin(target_id):
            await update.message.reply_text(f"المستخدم {target_id} هو المشرف!")
        elif await is_authorized(target_id):
            await update.message.reply_text(f"المستخدم {target_id} مصرح.")
        else:
            await update.message.reply_text(
                f"المستخدم {target_id} غير مصرح." + "\n\n" +
                f"للاضافة: /adduser {target_id}"
            )
    else:
        if is_admin(user.id):
            await update.message.reply_text(
                "انت المشرف!" + "\n\n" +
                f"معرفك: {user.id}"
            )
        elif await is_authorized(user.id):
            await update.message.reply_text(
                "انت مصرح لاستخدام بوت التداول." + "\n\n" +
                f"معرفك: {user.id}"
            )
        else:
            await update.message.reply_text(
                "غير مصرح!" + "\n\n" +
                f"معرفك: {user.id}" + "\n" +
                contact_admin_text()
            )
            await alert_admins_unauthorized(context, user.id, user.username, user.first_name)

# ============ سجل النشاط ============

ACTION_LABELS = {"added": "➕ اضافة", "removed": "➖ حذف", "expired": "⏳ انتهاء صلاحية"}

async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    entries = await get_activity_log(limit=15)
    if not entries:
        await update.message.reply_text("لا يوجد نشاط مسجل بعد.")
        return
    
    lines_list = ["📋 آخر 15 نشاط:", ""]
    for action, target_id, actor_id, note, created_at in entries:
        label = ACTION_LABELS.get(action, action)
        line = f"{label} | مستخدم: {target_id or '-'} | بواسطة: {actor_id or 'النظام'} | {created_at}"
        if note:
            line += f" ({note})"
        lines_list.append(line)
    
    await update.message.reply_text("\n".join(lines_list))

# ============ بث رسالة جماعية ============

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    if not context.args:
        await update.message.reply_text(
            "الاستخدام: /broadcast <الرسالة>" + "\n\n" +
            "مثال: /broadcast صيانة مجدولة الساعة 10 مساء"
        )
        return
    
    message_text = "📢 " + " ".join(context.args)
    users = await get_users()
    if not users:
        await update.message.reply_text("لا يوجد مستخدمون لارسال البث لهم.")
        return
    
    sent, failed = 0, 0
    for uid, *_rest in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {uid}: {e}")
            failed += 1
    
    await log_activity("broadcast", actor_id=user.id, note=message_text[:200])
    await update.message.reply_text(f"تم الارسال: {sent} نجح | {failed} فشل")

# ============ تصدير القائمة ============

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    users = await get_users()
    if not users:
        await update.message.reply_text("لا يوجد مستخدمون لتصديرهم.")
        return
    
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["user_id", "username", "first_name", "added_at", "expires_at"])
    for row in users:
        writer.writerow(row)
    
    csv_bytes = buffer.getvalue().encode("utf-8-sig")
    filename = f"authorized_users_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=f"📊 تصدير {len(users)} مستخدم"
    )

# ============ فحص دوري لانتهاء الصلاحيات المؤقتة ============

async def check_expired_job(context: ContextTypes.DEFAULT_TYPE):
    expired = await get_expired_users()
    if not expired:
        return
    for uid, username, first_name in expired:
        await remove_user(uid, removed_by=None, note="انتهت المدة المؤقتة تلقائيا")
        await log_activity("expired", uid, None, "انتهاء تلقائي")
        name_display = first_name or (f"@{username}" if username else f"مستخدم {uid}")
        for admin_id in ADMIN_USER_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⏳ انتهت صلاحية {name_display} (المعرف: {uid}) وتم الغاؤها تلقائيا."
                )
            except Exception as e:
                logger.warning(f"Admin expiry notify failed for {admin_id}: {e}")
        try:
            await context.bot.send_message(
                chat_id=uid,
                text="⏳ انتهت صلاحيتك المؤقتة لاستخدام بوت التداول. تواصل مع المشرف للتجديد."
            )
        except Exception as e:
            logger.warning(f"User expiry notify failed for {uid}: {e}")

# ============ معالجة الأزرار ============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if not is_admin(user.id):
        await query.edit_message_text("هذا الامر للمشرف فقط!")
        return
    
    data = query.data
    
    if data.startswith("quickadd_"):
        target_id = data.replace("quickadd_", "")
        if await is_authorized(target_id):
            await query.edit_message_text(f"✅ المستخدم {target_id} مصرح مسبقًا.")
            return
        await add_user(target_id, added_by=user.id)
        await query.edit_message_text(f"✅ تمت اضافة المستخدم {target_id} فورًا.")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="✅ تم تفعيل حسابك! لديك الآن صلاحية استخدام بوت التداول. اضغط /start في بوت التداول للبدء."
            )
        except Exception as e:
            logger.warning(f"Notify error: {e}")
        return
    
    if data == "menu_log":
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
        entries = await get_activity_log(limit=15)
        if not entries:
            await query.edit_message_text(
                "لا يوجد نشاط مسجل بعد.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        lines_list = ["📋 آخر 15 نشاط:", ""]
        for action, target_id, actor_id, note, created_at in entries:
            label = ACTION_LABELS.get(action, action)
            line = f"{label} | مستخدم: {target_id or '-'} | بواسطة: {actor_id or 'النظام'} | {created_at}"
            if note:
                line += f" ({note})"
            lines_list.append(line)
        await query.edit_message_text(
            "\n".join(lines_list),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data == "menu_export":
        users = await get_users()
        if not users:
            await query.answer("لا يوجد مستخدمون لتصديرهم.", show_alert=True)
            return
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["user_id", "username", "first_name", "added_at", "expires_at"])
        for row in users:
            writer.writerow(row)
        csv_bytes = buffer.getvalue().encode("utf-8-sig")
        filename = f"authorized_users_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(csv_bytes),
            filename=filename,
            caption=f"📊 تصدير {len(users)} مستخدم"
        )
        return
    
    if data == "menu_broadcast":
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
        await query.edit_message_text(
            "📢 بث جماعي" + "\n\n" +
            "اكتب: /broadcast <الرسالة>" + "\n\n" +
            "مثال: /broadcast صيانة مجدولة الساعة 10 مساء" + "\n\n" +
            "الرسالة تنزل لكل المستخدمين المصرح لهم.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    if data == "menu_add":
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
        await query.edit_message_text(
            "اضافة مستخدم" + "\n\n" +
            "الطريقة الاسهل:" + "\n" +
            "1. اذهب الى بوت التداول" + "\n" +
            "2. اضغط رد على رسالة المستخدم" + "\n" +
            "3. اكتب: /adduser" + "\n\n" +
            "او اكتب المعرف مباشرة:" + "\n" +
            "/adduser 123456789" + "\n\n" +
            "نصيحة: الطريقة الاولى اسهل - لا تحتاج لنسخ المعرف!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == "menu_remove":
        users = await get_users()
        if not users:
            keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
            await query.edit_message_text(
                "لا يوجد مستخدمون للحذف.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        keyboard = []
        for uid, username, first_name, _added_at, _expires_at in users:
            name = first_name or (f"@{username}" if username else f"مستخدم {uid}")
            keyboard.append([InlineKeyboardButton(f"حذف {name}", callback_data=f"remove_{uid}")])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="menu_main")])
        
        await query.edit_message_text(
            "اختر المستخدم للحذف:" + "\n\n" +
            "تحذير: سيتم الغاء صلاحيته فورا!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("remove_"):
        target_id = data.replace("remove_", "")
        keyboard = [
            [
                InlineKeyboardButton("نعم احذف", callback_data=f"confirm_remove_{target_id}"),
                InlineKeyboardButton("الغاء", callback_data="menu_remove")
            ]
        ]
        await query.edit_message_text(
            "تأكيد الحذف" + "\n\n" +
            f"هل انت متأكد من حذف المستخدم {target_id}?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data.startswith("confirm_remove_"):
        target_id = data.replace("confirm_remove_", "")
        
        if not await is_authorized(target_id):
            keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
            await query.edit_message_text(
                f"المستخدم {target_id} غير موجود.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if is_admin(target_id):
            keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
            await query.edit_message_text(
                "لا يمكن حذف المشرف!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        await remove_user(target_id, removed_by=user.id)
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=
                    "تم الغاء صلاحيتك." + "\n\n" +
                    "لم تعد تستطيع استخدام بوت التداول." + "\n" +
                    "تواصل مع المشرف اذا كنت تعتقد ان هذا خطأ."
            )
        except Exception as e:
            logger.warning(f"Notify remove error: {e}")
        
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
        await query.edit_message_text(
            "تم الحذف!" + "\n\n" +
            f"المستخدم: {target_id}" + "\n" +
            "تم الغاء صلاحيته.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == "cancel_remove":
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
        await query.edit_message_text(
            "تم الالغاء.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == "menu_users":
        users = await get_users()
        count = await get_user_count()
        
        if not users:
            keyboard = [
                [InlineKeyboardButton("اضافة مستخدم", callback_data="menu_add")],
                [InlineKeyboardButton("رجوع", callback_data="menu_main")]
            ]
            await query.edit_message_text(
                "لا يوجد مستخدمون مصرح لهم.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        lines_list = [f"المستخدمون المصرح لهم ({count}):", ""]
        for idx, (uid, username, first_name, added_at, expires_at) in enumerate(users, 1):
            name_display = first_name or (f"@{username}" if username else f"مستخدم {uid}")
            lines_list.append(f"{idx}. {name_display}")
            lines_list.append(f"   المعرف: {uid}")
            lines_list.append(f"   تاريخ الاضافة: {added_at}")
            if expires_at:
                lines_list.append(f"   ⏳ تنتهي: {expires_at}")
            lines_list.append("")
        
        keyboard = [
            [InlineKeyboardButton("اضافة مستخدم جديد", callback_data="menu_add")],
            [InlineKeyboardButton("حذف مستخدم", callback_data="menu_remove")],
            [InlineKeyboardButton("رجوع", callback_data="menu_main")]
        ]
        
        await query.edit_message_text(
            "\n".join(lines_list),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == "menu_check":
        keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
        await query.edit_message_text(
            "التحقق من مستخدم" + "\n\n" +
            "اكتب المعرف: /check 123456789" + "\n\n" +
            "او للتحقق من نفسك فقط اكتب: /check",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == "menu_main":
        keyboard = [
            [InlineKeyboardButton("+ اضافة مستخدم", callback_data="menu_add")],
            [InlineKeyboardButton("حذف مستخدم", callback_data="menu_remove")],
            [InlineKeyboardButton("قائمة المستخدمين", callback_data="menu_users")],
            [InlineKeyboardButton("التحقق من مستخدم", callback_data="menu_check")],
            [InlineKeyboardButton("📋 سجل النشاط", callback_data="menu_log"),
             InlineKeyboardButton("📊 تصدير CSV", callback_data="menu_export")],
            [InlineKeyboardButton("📢 بث جماعي", callback_data="menu_broadcast")],
        ]
        
        text = (
            "بوت ادارة الامان v2.0" + "\n\n" +
            f"مرحبا المشرف {user.first_name}!" + "\n" +
            f"معرفك: {user.id}" + "\n\n" +
            "اختر خيارا من الازرار:"
        )
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

# ============ التشغيل ============

def main():
    logger.info("Starting Security Bot v2.0 main()...")
    
    if not SECURITY_BOT_TOKEN:
        logger.error("SECURITY_BOT_TOKEN not set! Exiting.")
        sys.exit(1)
    logger.info("SECURITY_BOT_TOKEN is set")
    
    if not ADMIN_USER_IDS:
        logger.warning("No admins configured (ADMIN_USER_IDS/ADMIN_USER_ID) - no one can manage users!")
    else:
        logger.info(f"Admins: {ADMIN_USER_IDS}")

    async def _post_init(app: Application):
        try:
            await init_db()
        except Exception as e:
            logger.error(f"Failed to init DB: {e}")
            raise

    try:
        logger.info("Building application...")
        application = Application.builder().token(SECURITY_BOT_TOKEN).post_init(_post_init).build()
        logger.info("Application built successfully")
    except Exception as e:
        logger.error(f"Failed to build application: {e}")
        sys.exit(1)
    
    logger.info("Adding handlers...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("adduser", adduser_cmd))
    application.add_handler(CommandHandler("removeuser", removeuser_cmd))
    application.add_handler(CommandHandler("users", users_cmd))
    application.add_handler(CommandHandler("check", check_cmd))
    application.add_handler(CommandHandler("log", log_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("export", export_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Handlers added")
    
    if application.job_queue is not None:
        application.job_queue.run_repeating(check_expired_job, interval=3600, first=30)
        logger.info("Scheduled periodic expiry check (every hour)")
    else:
        logger.warning("job_queue unavailable - install 'python-telegram-bot[job-queue]' for auto-expiry")
    
    logger.info("Starting polling...")
    try:
        application.run_polling(
            stop_signals=None,
            close_loop=False,
            poll_interval=1.0,
            timeout=10
        )
    except Exception as e:
        logger.error(f"Polling error: {e}")
        raise

if __name__ == "__main__":
    main()
