"""
Security Bot - بوت إدارة الأمان
========================================================================
- بوت منفصل لإدارة صلاحيات المستخدمين
- يشارك نفس قاعدة البيانات مع بوت التداول الرئيسي
- يديره المشرف فقط (ADMIN_USER_ID)
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ============ الاعدادات ============
SECURITY_BOT_TOKEN = os.environ.get("SECURITY_BOT_TOKEN")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "")
SECURITY_DB_PATH = os.environ.get("DB_PATH", "/app/data/gold_bot.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============ قاعدة البيانات ============

def init_security_db():
    """تهيئة جدول المستخدمين المصرح لهم في قاعدة البيانات المشتركة"""
    os.makedirs(os.path.dirname(SECURITY_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            added_by TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("تم تهيئة قاعدة بيانات الأمان")

def is_admin(user_id: str) -> bool:
    """التحقق إذا كان المستخدم هو المشرف"""
    return str(user_id) == str(ADMIN_USER_ID)

def is_authorized(user_id: str) -> bool:
    """التحقق من صلاحية المستخدم في قاعدة البيانات المشتركة"""
    try:
        conn = sqlite3.connect(SECURITY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM authorized_users WHERE user_id = ?",
            (str(user_id),)
        )
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"خطأ في التحقق من الصلاحية: {e}")
        return False

def add_user_to_db(user_id: str, username: str = None, added_by: str = None):
    """إضافة مستخدم إلى قاعدة البيانات"""
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO authorized_users (user_id, username, added_by) VALUES (?, ?, ?)",
        (str(user_id), username, str(added_by) if added_by else None)
    )
    conn.commit()
    conn.close()

def remove_user_from_db(user_id: str):
    """حذف مستخدم من قاعدة البيانات"""
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM authorized_users WHERE user_id = ?",
        (str(user_id),)
    )
    conn.commit()
    conn.close()

def get_all_users():
    """جلب جميع المستخدمين المصرح لهم"""
    conn = sqlite3.connect(SECURITY_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, username, added_at, added_by FROM authorized_users ORDER BY added_at DESC"
    )
    users = cursor.fetchall()
    conn.close()
    return users

# ============ دوال المساعدة ============

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ============ معالجات الأوامر ============

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    keyboard = [
        [InlineKeyboardButton("عرض معرفي", callback_data="show_id")],
        [InlineKeyboardButton("حالة الصلاحية", callback_data="check_status")],
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("+ إضافة مستخدم", callback_data="add_user")])
        keyboard.append([InlineKeyboardButton("- حذف مستخدم", callback_data="remove_user")])
        keyboard.append([InlineKeyboardButton("قائمة المستخدمين", callback_data="list_users")])
    
    await update.message.reply_text(
        f"🛡️ <b>بوت إدارة الأمان</b>\n\n"
        f"👤 مرحباً {user.first_name}!\n"
        f"🆔 معرفك: <code>{user_id}</code>\n\n"
        f"اختر إحدى الخيارات:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 <b>معرف المستخدم الخاص بك:</b>\n\n"
        f"<code>{user.id}</code>\n\n"
        f"📋 انسخ هذا المعرف وأرسله للمشرف للحصول على الصلاحية.",
        parse_mode="HTML"
    )

async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text(
            "⛔ <b>غير مصرح!</b>\n\nهذا الأمر للمشرف فقط.",
            parse_mode="HTML"
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>الاستخدام:</b>\n"
            "<code>/adduser USER_ID</code>\n\n"
            "مثال: <code>/adduser 123456789</code>",
            parse_mode="HTML"
        )
        return
    
    target_id = context.args[0]
    
    try:
        int(target_id)
    except ValueError:
        await update.message.reply_text("❌ معرف المستخدم يجب أن يكون رقماً.")
        return
    
    if is_authorized(target_id):
        await update.message.reply_text(
            f"⚠️ المستخدم <code>{target_id}</code> موجود مسبقاً.",
            parse_mode="HTML"
        )
        return
    
    add_user_to_db(target_id, added_by=user.id)
    
    await update.message.reply_text(
        f"✅ <b>تمت الإضافة بنجاح!</b>\n\n"
        f"🆔 المستخدم: <code>{target_id}</code>\n"
        f"👤 أضيف بواسطة: {user.first_name}\n\n"
        f"🔓 يمكن للمستخدم الآن استخدام بوت التداول.",
        parse_mode="HTML"
    )
    
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="🎉 <b>تم تفعيل حسابك!</b>\n\n"
                 "✅ لديك الآن صلاحية استخدام بوت التداول.\n"
                 "اضغط /start في بوت التداول للبدء.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"لم يتم إرسال الإشعار للمستخدم {target_id}: {e}")

async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("⛔ غير مصرح!", parse_mode="HTML")
        return
    
    if not context.args:
        await update.message.reply_text(
            "⚠️ الاستخدام: <code>/removeuser USER_ID</code>",
            parse_mode="HTML"
        )
        return
    
    target_id = context.args[0]
    
    if not is_authorized(target_id):
        await update.message.reply_text(
            f"⚠️ المستخدم <code>{target_id}</code> غير موجود في القائمة.",
            parse_mode="HTML"
        )
        return
    
    remove_user_from_db(target_id)
    
    await update.message.reply_text(
        f"🗑️ <b>تم الحذف بنجاح!</b>\n\n"
        f"🆔 المستخدم: <code>{target_id}</code>\n"
        f"⛔ تم إلغاء صلاحيته من بوت التداول.",
        parse_mode="HTML"
    )

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("⛔ غير مصرح!", parse_mode="HTML")
        return
    
    users = get_all_users()
    
    if not users:
        await update.message.reply_text("📭 لا يوجد مستخدمون مصرح لهم حالياً.")
        return
    
    text = "📋 <b>قائمة المستخدمين المصرح لهم:</b>\n\n"
    for idx, (uid, username, added_at, added_by) in enumerate(users, 1):
        uname = f"@{username}" if username else "بدون اسم مستخدم"
        text += f"{idx}. 🆔 <code>{uid}</code> | {uname}\n"
        text += f"   📅 {added_at} | 👤 بواسطة: <code>{added_by}</code>\n\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

# ============ معالجات الأزرار ============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if data == "show_id":
        await query.edit_message_text(
            f"🆔 <b>معرفك:</b> <code>{user.id}</code>\n\n"
            f"📋 أرسل هذا المعرف للمشرف.",
            parse_mode="HTML"
        )
    
    elif data == "check_status":
        if is_admin(user.id):
            status = "👑 <b>أنت المشرف!</b>"
        elif is_authorized(user.id):
            status = "✅ <b>مصرح!</b>\n\nلديك صلاحية استخدام بوت التداول."
        else:
            status = (
                "⛔ <b>غير مصرح!</b>\n\n"
                "🔒 ليس لديك صلاحية استخدام بوت التداول.\n"
                f"🆔 معرفك: <code>{user.id}</code>\n"
                "📩 تواصل مع المشرف للحصول على الصلاحية."
            )
        await query.edit_message_text(status, parse_mode="HTML")
    
    elif data == "add_user":
        if not is_admin(user.id):
            await query.edit_message_text("⛔ غير مصرح!", parse_mode="HTML")
            return
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")]]
        await query.edit_message_text(
            "➕ <b>إضافة مستخدم جديد</b>\n\n"
            "📝 أرسل الآن معرف المستخدم (User ID) كرسالة نصية.\n\n"
            "مثال: <code>123456789</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data["waiting_for_user_id"] = "add"
    
    elif data == "remove_user":
        if not is_admin(user.id):
            await query.edit_message_text("⛔ غير مصرح!", parse_mode="HTML")
            return
        
        users = get_all_users()
        if not users:
            await query.edit_message_text("📭 لا يوجد مستخدمون لحذفهم.", parse_mode="HTML")
            return
        
        keyboard = []
        for uid, username, _, _ in users:
            name = f"@{username}" if username else uid
            keyboard.append([InlineKeyboardButton(f"🗑️ {name}", callback_data=f"del_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")])
        
        await query.edit_message_text(
            "➖ <b>اختر مستخدماً لحذفه:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "list_users":
        await cmd_users(update, context)
        keyboard = [
            [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_to_menu")]
        ]
        await context.bot.send_message(
            chat_id=user.id,
            text="👆 قائمة المستخدمين أعلاه.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "back_to_menu":
        keyboard = [
            [InlineKeyboardButton("🆔 عرض معرفي", callback_data="show_id")],
            [InlineKeyboardButton("📊 حالة الصلاحية", callback_data="check_status")],
        ]
        if is_admin(user.id):
            keyboard.append([InlineKeyboardButton("➕ إضافة مستخدم", callback_data="add_user")])
            keyboard.append([InlineKeyboardButton("➖ حذف مستخدم", callback_data="remove_user")])
            keyboard.append([InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="list_users")])
        
        await query.edit_message_text(
            f"🛡️ <b>بوت إدارة الأمان</b>\n\n"
            f"👤 مرحباً {user.first_name}!\n"
            f"🆔 معرفك: <code>{user.id}</code>\n\n"
            f"اختر إحدى الخيارات:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("del_"):
        if not is_admin(user.id):
            await query.edit_message_text("⛔ غير مصرح!", parse_mode="HTML")
            return
        
        target_id = data.replace("del_", "")
        remove_user_from_db(target_id)
        
        await query.edit_message_text(
            f"🗑️ <b>تم الحذف!</b>\n\n"
            f"🆔 المستخدم: <code>{target_id}</code>\n"
            f"⛔ تم إلغاء صلاحيته.",
            parse_mode="HTML"
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not is_admin(user.id):
        return
    
    if context.user_data.get("waiting_for_user_id") == "add":
        target_id = update.message.text.strip()
        
        try:
            int(target_id)
        except ValueError:
            await update.message.reply_text("❌ المعرف يجب أن يكون رقماً. حاول مرة أخرى.")
            return
        
        if is_authorized(target_id):
            await update.message.reply_text(
                f"⚠️ المستخدم <code>{target_id}</code> موجود مسبقاً.",
                parse_mode="HTML"
            )
        else:
            add_user_to_db(target_id, added_by=user.id)
            await update.message.reply_text(
                f"✅ <b>تمت الإضافة!</b>\n\n"
                f"🆔 المستخدم: <code>{target_id}</code>\n"
                f"🔓 يمكنه الآن استخدام بوت التداول.",
                parse_mode="HTML"
            )
            
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🎉 <b>تم تفعيل حسابك!</b>\n\n"
                         "✅ لديك الآن صلاحية استخدام بوت التداول.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"لم يتم الإشعار: {e}")
        
        context.user_data["waiting_for_user_id"] = None

# ============ التشغيل ============

def main():
    init_security_db()
    
    if not SECURITY_BOT_TOKEN:
        logger.error("❌ لم يتم تعيين SECURITY_BOT_TOKEN!")
        return
    
    if not ADMIN_USER_ID:
        logger.warning("⚠️ لم يتم تعيين ADMIN_USER_ID - لن يتمكن أحد من إدارة المستخدمين!")
    
    application = Application.builder().token(SECURITY_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("adduser", cmd_adduser))
    application.add_handler(CommandHandler("removeuser", cmd_removeuser))
    application.add_handler(CommandHandler("users", cmd_users))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("🚀 بوت الأمان يعمل...")
    application.run_polling()


if __name__ == "__main__":
    main() 
