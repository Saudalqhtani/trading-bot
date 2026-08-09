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
import sqlite3
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ============ الإعدادات ============
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
        logger.info("DB initialized successfully")
    except Exception as e:
        logger.error(f"DB init error: {e}")
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
        if is_authorized(user_id):
            text += "\n\n" + "انت مصرح لاستخدام بوت التداول!"
        else:
            text += "\n\n" + "غير مصرح. تواصل مع المشرف."
        await update.message.reply_text(text)

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = "معرفك:" + "\n" + str(user.id) + "\n\n" + "ارسل هذا المعرف للمشرف لتفعيل حسابك."
    await update.message.reply_text(msg)

async def adduser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("هذا الامر للمشرف فقط!")
        return
    
    # الحالة 1: بالرد على رسالة المستخدم
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = str(target_user.id)
        target_username = target_user.username
        target_first_name = target_user.first_name
        
        if is_authorized(target_id):
            await update.message.reply_text(
                "المستخدم موجود مسبقا!" + "\n\n" +
                format_user_info(target_id, target_username, target_first_name)
            )
            return
        
        add_user(target_id, target_username, target_first_name, user.id)
        
        await update.message.reply_text(
            "تمت الاضافة!" + "\n\n" +
            format_user_info(target_id, target_username, target_first_name) + "\n\n" +
            "يمكنه الان استخدام بوت التداول."
        )
        
        try:
            notify_msg = (
                "تم تفعيل حسابك!" + "\n\n" +
                "لديك الان صلاحية استخدام بوت التداول." + "\n" +
                "اضغط /start في بوت التداول للبدء."
            )
            await context.bot.send_message(chat_id=target_id, text=notify_msg)
        except Exception as e:
            logger.warning(f"Notify error: {e}")
            await update.message.reply_text("لم استطع ارسال اشعار للمستخدم")
        return
    
    # الحالة 2: كتابة المعرف مباشرة
    if not context.args:
        await update.message.reply_text(
            "الاستخدام:" + "\n\n" +
            "الاسهل: بالرد على رسالة المستخدم واكتب /adduser" + "\n\n" +
            "او اكتب المعرف: /adduser 123456789"
        )
        return
    
    raw_id = context.args[0]
    target_id = clean_user_id(raw_id)
    
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
    
    if is_authorized(target_id):
        await update.message.reply_text(f"المستخدم {target_id} موجود مسبقا.")
        return
    
    add_user(target_id, added_by=user.id)
    
    await update.message.reply_text(
        "تمت الاضافة!" + "\n\n" +
        f"المستخدم: {target_id}" + "\n" +
        "يمكنه الان استخدام بوت التداول."
    )
    
    try:
        notify_msg = (
            "تم تفعيل حسابك!" + "\n\n" +
            "لديك الان صلاحية استخدام بوت التداول." + "\n" +
            "اضغط /start في بوت التداول للبدء."
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
    
    if not is_authorized(target_id):
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
    
    users = get_users()
    count = get_user_count()
    
    if not users:
        await update.message.reply_text("لا يوجد مستخدمون مصرح لهم.")
        return
    
    lines_list = [f"المستخدمون المصرح لهم ({count}):", ""]
    
    for idx, (uid, username, first_name, added_at) in enumerate(users, 1):
        name_display = first_name or (f"@{username}" if username else f"مستخدم {uid}")
        lines_list.append(f"{idx}. {name_display}")
        lines_list.append(f"   المعرف: {uid}")
        lines_list.append(f"   تاريخ الاضافة: {added_at}")
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
        elif is_authorized(target_id):
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
        elif is_authorized(user.id):
            await update.message.reply_text(
                "انت مصرح لاستخدام بوت التداول." + "\n\n" +
                f"معرفك: {user.id}"
            )
        else:
            await update.message.reply_text(
                "غير مصرح!" + "\n\n" +
                f"معرفك: {user.id}" + "\n" +
                "تواصل مع المشرف للحصول على الصلاحية."
            )

# ============ معالجة الأزرار ============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    if not is_admin(user.id):
        await query.edit_message_text("هذا الامر للمشرف فقط!")
        return
    
    data = query.data
    
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
        users = get_users()
        if not users:
            keyboard = [[InlineKeyboardButton("رجوع", callback_data="menu_main")]]
            await query.edit_message_text(
                "لا يوجد مستخدمون للحذف.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        keyboard = []
        for uid, username, first_name, _ in users:
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
        
        if not is_authorized(target_id):
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
        
        remove_user(target_id)
        
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
        users = get_users()
        count = get_user_count()
        
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
        for idx, (uid, username, first_name, added_at) in enumerate(users, 1):
            name_display = first_name or (f"@{username}" if username else f"مستخدم {uid}")
            lines_list.append(f"{idx}. {name_display}")
            lines_list.append(f"   المعرف: {uid}")
            lines_list.append(f"   تاريخ الاضافة: {added_at}")
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
    
    if not ADMIN_USER_ID:
        logger.warning("ADMIN_USER_ID not set - no one can manage users!")
    else:
        logger.info(f"Admin ID: {ADMIN_USER_ID}")
    
    try:
        init_db()
    except Exception as e:
        logger.error(f"Failed to init DB: {e}")
        sys.exit(1)
    
    try:
        logger.info("Building application...")
        application = Application.builder().token(SECURITY_BOT_TOKEN).build()
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
    application.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Handlers added")
    
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
 
