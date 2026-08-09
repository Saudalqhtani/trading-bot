"""
Security Bot v2.0 - بوت إدارة الأمان (نسخة محسّنة وسهلة الاستخدام)
========================================================================
- ✅ تنظيف الإدخال تلقائياً (إزالة الرموز الزائدة)
- ✅ إضافة مستخدم بالرد على رسالته
- ✅ أزرار تفاعلية للإدارة
- ✅ تأكيد قبل الحذف
- ✅ رسائل توجيهية أوضح
"""

import os
import sys
import sqlite3
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ============ Settings ============
SECURITY_BOT_TOKEN = os.environ.get("SECURITY_BOT_TOKEN")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "")
DB_PATH = os.environ.get("DB_PATH", "/app/data/gold_bot.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("SECURITY BOT v2.0 STARTING")
logger.info(f"DB_PATH: {DB_PATH}")
logger.info(f"ADMIN_USER_ID set: {bool(ADMIN_USER_ID)}")
logger.info(f"SECURITY_BOT_TOKEN set: {bool(SECURITY_BOT_TOKEN)}")
logger.info("=" * 50)

# ============ دوال قاعدة البيانات ============

def init_db():
    logger.info("Initializing DB...")
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                added_by TEXT
            )
        """)
        conn.commit()
        conn.close()
        logger.info("✅ DB initialized successfully")
    except Exception as e:
        logger.error(f"❌ DB init error: {e}")
        raise

def is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_USER_ID)

def is_authorized(user_id) -> bool:
    if is_admin(user_id):
        return True
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM authorized_users WHERE user_id = ?", (str(user_id),))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Auth check error: {e}")
        return False

def add_user(user_id, username=None, first_name=None, added_by=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO authorized_users (user_id, username, first_name, added_by)
        VALUES (?, ?, ?, ?)
    """, (str(user_id), username, first_name, str(added_by) if added_by else None))
    conn.commit()
    conn.close()

def remove_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM authorized_users WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()

def get_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, added_at FROM authorized_users ORDER BY added_at DESC")
    users = cursor.fetchall()
    conn.close()
    return users

def get_user_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM authorized_users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ============ دوال مساعدة ============

def clean_user_id(text: str) -> str:
    """تنظيف معرف المستخدم من الرموز الزائدة"""
    if not text:
        return ""
    # إزالة @ في البداية
    text = text.lstrip("@")
    # إزالة الشرطة المائلة في النهاية
    text = text.rstrip("/")
    # إزالة المسافات
    text = text.strip()
    # الاحتفاظ بالأرقام فقط
    cleaned = re.sub(r"[^0-9]", "", text)
    return cleaned

def format_user_info(user_id, username=None, first_name=None) -> str:
    """تنسيق معلومات المستخدم للعرض"""
    parts = [f"🆔 `{user_id}`"]
    if first_name:
        parts.append(f"👤 {first_name}")
    if username:
        parts.append(f"📱 @{username}")
    return " | ".join(parts)

# ============ الأوامر ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /start from user {update.effective_user.id}")
    user = update.effective_user
    user_id = user.id

    if is_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مستخدم", callback_data="menu_add")],
            [InlineKeyboardButton("🗑️ حذف مستخدم", callback_data="menu_remove")],
            [InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="menu_users")],
            [InlineKeyboardButton("🔍 التحقق من مستخدم", callback_data="menu_check")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        lines = [
            "🛡️ <b>بوت إدارة الأمان v2.0</b>",
            "",
            f"👑 مرحباً <b>{user.first_name}</b>!",
            f"🆔 معرفك: <code>{user_id}</code>",
            "",
            "✅ <b>أنت المشرف!</b>",
            "",
            "📋 <b>الأوامر المتاحة:</b>",
            "",
            "<b>🎯 الطريقة السهلة (بالأزرار):</b>",
            "اضغط على الأزرار أدناه 👇",
            "",
            "<b>⌨️ الطريقة التقليدية:</b>",
            "/id — عرض معرفك",
            "/adduser ID — إضافة مستخدم",
            "  💡 أو بالرد على رسالته: /adduser",
            "/removeuser ID — حذف مستخدم",
            "/users — قائمة المستخدمين",
            "/check ID — التحقق من مستخدم",
        ]
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    else:
        lines = [
            "🛡️ <b>بوت إدارة الأمان</b>",
            "",
            f"👤 مرحباً {user.first_name}!",
            f"🆔 معرفك: <code>{user_id}</code>",
            "",
            "📋 <b>الأوامر:</b>",
            "/id — عرض معرفك",
            "/check — التحقق من صلاحيتك",
        ]
        if is_authorized(user_id):
            lines.append("")
            lines.append("✅ <b>أنت مصرح لاستخدام بوت التداول!</b>")
        else:
            lines.append("")
            lines.append("⛔ <b>غير مصرح لك.</b>")
            lines.append("📩 تواصل مع المشرف للحصول على الصلاحية.")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = (
        "🆔 <b>معرفك:</b>
"
        f"<code>{user.id}</code>

"
        "📋 <b>ارسل هذا المعرف للمشرف</b> ليتم تفعيل حسابك."
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def adduser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
        return

    # حالة 1: بالرد على رسالة المستخدم
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = str(target_user.id)
        target_username = target_user.username
        target_first_name = target_user.first_name

        if is_authorized(target_id):
            await update.message.reply_text(
                f"⚠️ المستخدم موجود مسبقاً!

"
                f"{format_user_info(target_id, target_username, target_first_name)}",
                parse_mode="Markdown"
            )
            return

        add_user(target_id, target_username, target_first_name, user.id)

        # إشعار المشرف
        await update.message.reply_text(
            f"✅ <b>تمت الإضافة بنجاح!</b>

"
            f"{format_user_info(target_id, target_username, target_first_name)}

"
            f"🔓 يمكنه الآن استخدام بوت التداول.",
            parse_mode="HTML"
        )

        # إشعار المستخدم الجديد
        try:
            notify_msg = (
                "🎉 <b>تم تفعيل حسابك!</b>

"
                "✅ لديك الآن صلاحية استخدام بوت التداول.
"
                "اضغط /start في بوت التداول للبدء."
            )
            await context.bot.send_message(chat_id=target_id, text=notify_msg, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Notify error: {e}")
            await update.message.reply_text("⚠️ لم أتمكن من إرسال إشعار للمستخدم (ربما لم يبدأ محادثة مع البوت)")
        return

    # حالة 2: بكتابة المعرف مباشرة
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>طريقة الاستخدام:</b>

"
            "<b>الطريقة 1 (الأسهل):</b>
"
            "بالرد على رسالة المستخدم وكتابة: <code>/adduser</code>

"
            "<b>الطريقة 2:</b>
"
            "كتابة المعرف: <code>/adduser 123456789</code>

"
            "💡 <b>نصيحة:</b> الطريقة الأولى أسهل — اضغط "رد" على رسالة المستخدم ثم اكتب /adduser",
            parse_mode="HTML"
        )
        return

    # تنظيف المعرف
    raw_id = context.args[0]
    target_id = clean_user_id(raw_id)

    if not target_id:
        await update.message.reply_text(
            "❌ <b>معرف غير صالح!</b>

"
            f"القيمة المدخلة: <code>{raw_id}</code>
"
            "المعرف يجب أن يكون أرقاماً فقط.

"
            "💡 <b>جرب الطريقة السهلة:</b> بالرد على رسالة المستخدم واكتب /adduser",
            parse_mode="HTML"
        )
        return

    try:
        int(target_id)
    except ValueError:
        await update.message.reply_text("❌ المعرف يجب أن يكون رقماً!")
        return

    if is_authorized(target_id):
        await update.message.reply_text(
            f"⚠️ المستخدم <code>{target_id}</code> موجود مسبقاً.",
            parse_mode="HTML"
        )
        return

    add_user(target_id, added_by=user.id)

    await update.message.reply_text(
        f"✅ <b>تمت الإضافة!</b>

"
        f"🆔 المستخدم: <code>{target_id}</code>
"
        f"🔓 يمكنه الآن استخدام بوت التداول.",
        parse_mode="HTML"
    )

    try:
        notify_msg = (
            "🎉 <b>تم تفعيل حسابك!</b>

"
            "✅ لديك الآن صلاحية استخدام بوت التداول.
"
            "اضغط /start في بوت التداول للبدء."
        )
        await context.bot.send_message(chat_id=target_id, text=notify_msg, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Notify error: {e}")

async def removeuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>طريقة الاستخدام:</b>
"
            "<code>/removeuser 123456789</code>

"
            "أو استخدم الزر '🗑️ حذف مستخدم' من القائمة الرئيسية.",
            parse_mode="HTML"
        )
        return

    raw_id = context.args[0]
    target_id = clean_user_id(raw_id)

    if not target_id:
        await update.message.reply_text(
            "❌ <b>معرف غير صالح!</b>
"
            f"القيمة المدخلة: <code>{raw_id}</code>",
            parse_mode="HTML"
        )
        return

    if not is_authorized(target_id):
        await update.message.reply_text(
            f"⚠️ المستخدم <code>{target_id}</code> غير موجود في القائمة.",
            parse_mode="HTML"
        )
        return

    # تأكيد قبل الحذف
    keyboard = [
        [
            InlineKeyboardButton("✅ نعم، احذف", callback_data=f"confirm_remove_{target_id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel_remove")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⚠️ <b>تأكيد الحذف</b>

"
        f"هل أنت متأكد من حذف المستخدم <code>{target_id}</code>؟

"
        f"🗑️ سيتم إلغاء صلاحيته فوراً.",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
        return

    users = get_users()
    count = get_user_count()

    if not users:
        await update.message.reply_text("📭 لا يوجد مستخدمون مصرح لهم.")
        return

    lines = [f"📋 <b>المستخدمون المصرح لهم ({count}):</b>", ""]

    for idx, (uid, username, first_name, added_at) in enumerate(users, 1):
        name_display = first_name or (f"@{username}" if username else "بدون اسم")
        lines.append(f"{idx}. 👤 <b>{name_display}</b>")
        lines.append(f"   🆔 <code>{uid}</code>")
        lines.append(f"   📅 {added_at}")
        lines.append("")

    # أزرار للإدارة السريعة
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مستخدم جديد", callback_data="menu_add")],
        [InlineKeyboardButton("🔄 تحديث القائمة", callback_data="menu_users")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if context.args:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
            return

        raw_id = context.args[0]
        target_id = clean_user_id(raw_id)

        if not target_id:
            await update.message.reply_text("❌ معرف غير صالح!")
            return

        if is_admin(target_id):
            await update.message.reply_text(
                f"👑 المستخدم <code>{target_id}</code> هو <b>المشرف</b>!",
                parse_mode="HTML"
            )
        elif is_authorized(target_id):
            await update.message.reply_text(
                f"✅ المستخدم <code>{target_id}</code> <b>مصرح</b> لاستخدام بوت التداول.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⛔ المستخدم <code>{target_id}</code> <b>غير مصرح</b>.

"
                f"لإضافته: <code>/adduser {target_id}</code>",
                parse_mode="HTML"
            )
    else:
        if is_admin(user.id):
            await update.message.reply_text(
                "👑 <b>أنت المشرف!</b>

"
                f"🆔 معرفك: <code>{user.id}</code>",
                parse_mode="HTML"
            )
        elif is_authorized(user.id):
            await update.message.reply_text(
                "✅ <b>أنت مصرح لاستخدام بوت التداول.</b>

"
                f"🆔 معرفك: <code>{user.id}</code>",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                "⛔ <b>غير مصرح!</b>

"
                f"🆔 معرفك: <code>{user.id}</code>
"
                "📩 تواصل مع المشرف للحصول على الصلاحية.",
                parse_mode="HTML"
            )

# ============ معالجة الأزرار ============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not is_admin(user.id):
        await query.edit_message_text("⛔ هذا الأمر للمشرف فقط!")
        return

    data = query.data

    # قائمة الإضافة
    if data == "menu_add":
        await query.edit_message_text(
            "➕ <b>إضافة مستخدم جديد</b>

"
            "<b>الطريقة الأسهل:</b>
"
            "1️⃣ اذهب إلى بوت التداول
"
            "2️⃣ اضغط "رد" على رسالة المستخدم
"
            "3️⃣ اكتب: <code>/adduser</code>

"
            "<b>أو اكتب المعرف مباشرة:</b>
"
            "<code>/adduser 123456789</code>

"
            "💡 الطريقة الأولى أسهل ولا تحتاج لنسخ المعرف!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
            ]])
        )
        return

    # قائمة الحذف
    elif data == "menu_remove":
        users = get_users()
        if not users:
            await query.edit_message_text(
                "📭 لا يوجد مستخدمون لحذفهم.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
                ]])
            )
            return

        keyboard = []
        for uid, username, first_name, _ in users:
            name = first_name or (f"@{username}" if username else f"مستخدم {uid}")
            keyboard.append([InlineKeyboardButton(f"🗑️ {name}", callback_data=f"remove_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")])

        await query.edit_message_text(
            "🗑️ <b>اختر المستخدم للحذف:</b>

"
            "⚠️ سيتم إلغاء صلاحيته فوراً!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # تأكيد الحذف من القائمة
    elif data.startswith("remove_"):
        target_id = data.replace("remove_", "")
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، احذف", callback_data=f"confirm_remove_{target_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="menu_remove")
            ]
        ]
        await query.edit_message_text(
            f"⚠️ <b>تأكيد الحذف</b>

"
            f"هل أنت متأكد من حذف المستخدم <code>{target_id}</code>؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # تنفيذ الحذف
    elif data.startswith("confirm_remove_"):
        target_id = data.replace("confirm_remove_", "")

        if not is_authorized(target_id):
            await query.edit_message_text(
                f"⚠️ المستخدم <code>{target_id}</code> غير موجود.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
                ]])
            )
            return

        if is_admin(target_id):
            await query.edit_message_text(
                "⛔ <b>لا يمكن حذف المشرف!</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
                ]])
            )
            return

        remove_user(target_id)

        # إشعار المستخدم المحذوف
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="⛔ <b>تم إلغاء صلاحيتك.</b>

"
                     "لم تعد تستطيع استخدام بوت التداول.
"
                     "تواصل مع المشرف إذا كنت تعتقد أن هذا خطأ.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Notify remove error: {e}")

        await query.edit_message_text(
            f"🗑️ <b>تم الحذف بنجاح!</b>

"
            f"🆔 المستخدم: <code>{target_id}</code>
"
            f"⛔ تم إلغاء صلاحيته.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
            ]])
        )
        return

    # إلغاء الحذف
    elif data == "cancel_remove":
        await query.edit_message_text(
            "✅ <b>تم الإلغاء.</b>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
            ]])
        )
        return

    # قائمة المستخدمين
    elif data == "menu_users":
        users = get_users()
        count = get_user_count()

        if not users:
            await query.edit_message_text(
                "📭 لا يوجد مستخدمون مصرح لهم.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة مستخدم", callback_data="menu_add")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")]
                ])
            )
            return

        lines = [f"📋 <b>المستخدمون المصرح لهم ({count}):</b>", ""]
        for idx, (uid, username, first_name, added_at) in enumerate(users, 1):
            name_display = first_name or (f"@{username}" if username else "بدون اسم")
            lines.append(f"{idx}. 👤 <b>{name_display}</b>")
            lines.append(f"   🆔 <code>{uid}</code>")
            lines.append(f"   📅 {added_at}")
            lines.append("")

        keyboard = [
            [InlineKeyboardButton("➕ إضافة مستخدم جديد", callback_data="menu_add")],
            [InlineKeyboardButton("🗑️ حذف مستخدم", callback_data="menu_remove")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")]
        ]

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # التحقق من مستخدم
    elif data == "menu_check":
        await query.edit_message_text(
            "🔍 <b>التحقق من مستخدم</b>

"
            "اكتب المعرف: <code>/check 123456789</code>

"
            "أو للتحقق من نفسك فقط اكتب: <code>/check</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")
            ]])
        )
        return

    # الرجوع للقائمة الرئيسية
    elif data == "menu_main":
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مستخدم", callback_data="menu_add")],
            [InlineKeyboardButton("🗑️ حذف مستخدم", callback_data="menu_remove")],
            [InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="menu_users")],
            [InlineKeyboardButton("🔍 التحقق من مستخدم", callback_data="menu_check")],
        ]

        lines = [
            "🛡️ <b>بوت إدارة الأمان v2.0</b>",
            "",
            f"👑 مرحباً <b>{user.first_name}</b>!",
            f"🆔 معرفك: <code>{user.id}</code>",
            "",
            "✅ <b>أنت المشرف!</b>",
            "",
            "اختر خياراً من الأزرار أدناه 👇"
        ]

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

# ============ التشغيل ============

def main():
    logger.info("🔧 Starting Security Bot v2.0 main()...")

    if not SECURITY_BOT_TOKEN:
        logger.error("❌ SECURITY_BOT_TOKEN not set! Exiting.")
        sys.exit(1)
    logger.info("✅ SECURITY_BOT_TOKEN is set")

    if not ADMIN_USER_ID:
        logger.warning("⚠️ ADMIN_USER_ID not set - no one can manage users!")
    else:
        logger.info(f"👑 Admin ID: {ADMIN_USER_ID}")

    try:
        init_db()
    except Exception as e:
        logger.error(f"❌ Failed to init DB: {e}")
        sys.exit(1)

    try:
        logger.info("Building application...")
        application = Application.builder().token(SECURITY_BOT_TOKEN).build()
        logger.info("✅ Application built successfully")
    except Exception as e:
        logger.error(f"❌ Failed to build application: {e}")
        sys.exit(1)

    logger.info("Adding handlers...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("adduser", adduser_cmd))
    application.add_handler(CommandHandler("removeuser", removeuser_cmd))
    application.add_handler(CommandHandler("users", users_cmd))
    application.add_handler(CommandHandler("check", check_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.info("✅ Handlers added")

    logger.info("🚀 Starting polling...")
    try:
        application.run_polling(
            stop_signals=None,
            close_loop=False,
            poll_interval=1.0,
            timeout=10
        )
    except Exception as e:
        logger.error(f"❌ Polling error: {e}")
        raise

if __name__ == "__main__":
    main()
 
