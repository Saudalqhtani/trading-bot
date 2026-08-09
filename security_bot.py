"""
Security Bot v2 - بوت إدارة الأمان
"""

import os
import sqlite3
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Settings
SECURITY_BOT_TOKEN = os.environ.get("SECURITY_BOT_TOKEN")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "")
DB_PATH = os.environ.get("DB_PATH", "/app/data/gold_bot.db")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS authorized_users (user_id TEXT PRIMARY KEY, username TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, added_by TEXT)")
        conn.commit()
        conn.close()
        logger.info("DB ready")
    except Exception as e:
        logger.error(f"DB error: {e}")

def is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_USER_ID)

def is_authorized(user_id) -> bool:
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

def add_user(user_id, username=None, added_by=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO authorized_users (user_id, username, added_by) VALUES (?, ?, ?)", (str(user_id), username, str(added_by) if added_by else None))
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
    cursor.execute("SELECT user_id, username, added_at FROM authorized_users ORDER BY added_at DESC")
    users = cursor.fetchall()
    conn.close()
    return users

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lines = ["🛡️ بوت إدارة الأمان", "", f"👤 مرحباً {user.first_name}!", f"🆔 معرفك: {user_id}", ""]
    if is_admin(user_id):
        lines.append("👑 أنت المشرف!")
        lines.append("")
        lines.append("الأوامر:")
        lines.append("/id - عرض معرفك")
        lines.append("/adduser ID - إضافة مستخدم")
        lines.append("/removeuser ID - حذف مستخدم")
        lines.append("/users - قائمة المستخدمين")
        lines.append("/check ID - التحقق من مستخدم")
    else:
        lines.append("📋 الأوامر:")
        lines.append("/id - عرض معرفك")
        lines.append("/check - التحقق من صلاحيتك")
    await update.message.reply_text("\n".join(lines))

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"🆔 معرفك: {user.id}\n\n📋 أرسل هذا المعرف للمشرف.")

async def adduser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
        return
    if not context.args:
        await update.message.reply_text("⚠️ الاستخدام: /adduser 123456789")
        return
    target_id = context.args[0]
    try:
        int(target_id)
    except ValueError:
        await update.message.reply_text("❌ المعرف يجب أن يكون رقماً!")
        return
    if is_authorized(target_id):
        await update.message.reply_text(f"⚠️ المستخدم {target_id} موجود مسبقاً.")
        return
    add_user(target_id, added_by=user.id)
    await update.message.reply_text(f"✅ تمت الإضافة!\n\n🆔 المستخدم: {target_id}\n🔓 يمكنه الآن استخدام بوت التداول.")
    try:
        await context.bot.send_message(chat_id=target_id, text="🎉 تم تفعيل حسابك!\n\n✅ لديك الآن صلاحية استخدام بوت التداول.\nاضغط /start في بوت التداول.")
    except Exception as e:
        logger.warning(f"Notify error: {e}")

async def removeuser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
        return
    if not context.args:
        await update.message.reply_text("⚠️ الاستخدام: /removeuser 123456789")
        return
    target_id = context.args[0]
    if not is_authorized(target_id):
        await update.message.reply_text(f"⚠️ المستخدم {target_id} غير موجود.")
        return
    remove_user(target_id)
    await update.message.reply_text(f"🗑️ تم حذف المستخدم {target_id}")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
        return
    users = get_users()
    if not users:
        await update.message.reply_text("📭 لا يوجد مستخدمون.")
        return
    lines = ["📋 المستخدمون المصرح لهم:", ""]
    for idx, (uid, username, added_at) in enumerate(users, 1):
        uname = f"@{username}" if username else "بدون اسم"
        lines.append(f"{idx}. 🆔 {uid} | {uname}")
        lines.append(f"   📅 {added_at}")
    await update.message.reply_text("\n".join(lines))

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if context.args:
        if not is_admin(user.id):
            await update.message.reply_text("⛔ هذا الأمر للمشرف فقط!")
            return
        target_id = context.args[0]
        if is_authorized(target_id):
            await update.message.reply_text(f"✅ المستخدم {target_id} مصرح.")
        else:
            await update.message.reply_text(f"⛔ المستخدم {target_id} غير مصرح.")
    else:
        if is_admin(user.id):
            await update.message.reply_text("👑 أنت المشرف!")
        elif is_authorized(user.id):
            await update.message.reply_text("✅ أنت مصرح لاستخدام بوت التداول.")
        else:
            await update.message.reply_text(f"⛔ غير مصرح!\n\n🆔 معرفك: {user.id}\n📩 تواصل مع المشرف.")

def main():
    init_db()
    if not SECURITY_BOT_TOKEN:
        logger.error("SECURITY_BOT_TOKEN missing!")
        return
    if not ADMIN_USER_ID:
        logger.warning("ADMIN_USER_ID missing!")
    else:
        logger.info(f"Admin: {ADMIN_USER_ID}")
    application = Application.builder().token(SECURITY_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("adduser", adduser_cmd))
    application.add_handler(CommandHandler("removeuser", removeuser_cmd))
    application.add_handler(CommandHandler("users", users_cmd))
    application.add_handler(CommandHandler("check", check_cmd))
    logger.info("🚀 Security bot starting...")
    application.run_polling()

if __name__ == "__main__":
    main() 
