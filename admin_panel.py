import os
import shutil
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from utils import OWNER_ID, db_manager, file_manager, logger, MAINTENANCE_MODE

# استيراد المتغير مباشرة
from utils import MAINTENANCE_MODE as maintenance_mode

async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فتح لوحة تحكم المالك المحسنة"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ **هذه الخاصية متاحة للمطور فقط.**")
        return

    from keyboards import admin_panel_keyboard
    
    # إحصائيات سريعة
    stats = db_manager.execute_query("SELECT COUNT(*) FROM users")
    users_count = stats[0][0] if stats else 0
    
    await update.message.reply_text(
        f"🛠 **لوحة تحكم المطور**\n\n"
        f"👤 المستخدمين: {users_count}\n"
        f"⚙️ وضع الصيانة: {'🟢 مفعل' if maintenance_mode else '🔴 غير مفعل'}\n\n"
        f"📌 اختر الإجراء المناسب:",
        reply_markup=admin_panel_keyboard(maintenance_mode)
    )

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """المعالجة الخاصة بأزرار لوحة التحكم المحسنة"""
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("🚫 غير مصرح لك!", show_alert=True)
        return

    from keyboards import admin_panel_keyboard

    if query.data == "admin_stats":
        # إحصائيات شاملة
        stats = db_manager.execute_query("SELECT COUNT(*) FROM users")
        users_count = stats[0][0] if stats else 0
        
        files_stats = db_manager.execute_query("SELECT COUNT(*) FROM files")
        files_count = files_stats[0][0] if files_stats else 0
        
        # الأخطاء
        error_stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE status = 'error'"
        )
        errors_count = error_stats[0][0] if error_stats else 0
        
        # آخر 24 ساعة
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE date LIKE ?", (f"{today}%",)
        )
        today_files = today_stats[0][0] if today_stats else 0
        
        await query.edit_message_text(
            f"📊 **إحصائيات البوت الشاملة**\n\n"
            f"👤 **المستخدمين:** {users_count}\n"
            f"📁 **العمليات الناجحة:** {files_count}\n"
            f"📁 **عمليات اليوم:** {today_files}\n"
            f"❌ **الأخطاء:** {errors_count}\n"
            f"⚙️ **وضع الصيانة:** {'🟢 مفعل' if maintenance_mode else '🔴 غير مفعل'}\n\n"
            f"💾 **حجم قاعدة البيانات:** {os.path.getsize('bot_stats.db') // 1024} KB",
            reply_markup=admin_panel_keyboard(maintenance_mode)
        )

    elif query.data == "toggle_maintenance":
        global maintenance_mode
        maintenance_mode = not maintenance_mode
        status_text = "تم تفعيل" if maintenance_mode else "تم إيقاف"
        
        await query.answer(f"✅ {status_text} وضع الصيانة")
        await query.edit_message_text(
            f"🛠 **{status_text} وضع الصيانة**\n\n"
            f"الحالة الحالية: {'🟢 البوت في وضع الصيانة' if maintenance_mode else '🔴 البوت يعمل طبيعياً'}\n\n"
            f"📌 جميع المستخدمين العاديين سيتم منعهم من استخدام البوت.",
            reply_markup=admin_panel_keyboard(maintenance_mode)
        )

    elif query.data == "admin_broadcast":
        context.user_data['admin_step'] = 'broadcasting'
        await query.edit_message_text(
            "📢 **الإذاعة (Broadcast)**\n\n"
            "📝 أرسل الآن الرسالة (نص فقط) ليتم إرسالها لجميع المستخدمين.\n\n"
            "⚠️ **تحذير:** لا يمكن التراجع عن هذه العملية.\n"
            f"📌 سيتم إرسالها لـ {db_manager.execute_query('SELECT COUNT(*) FROM users')[0][0]} مستخدم."
        )

    elif query.data == "admin_clean":
        # تنظيف الملفات المؤقتة
        deleted = 0
        try:
            # تنظيف باستخدام المدير
            file_manager.cleanup_all()
            deleted = 1  # تقريبي
        except:
            pass
        
        await query.answer("✅ تم تنظيف الملفات المؤقتة")
        await query.edit_message_text(
            f"🗑 **تنظيف الملفات المؤقتة**\n\n"
            f"✅ تم حذف الملفات المؤقتة بنجاح.\n\n"
            f"📌 يمكنك أيضاً تشغيل التنظيف التلقائي كل 30 دقيقة.",
            reply_markup=admin_panel_keyboard(maintenance_mode)
        )

    elif query.data == "admin_optimize":
        # تحسين قاعدة البيانات
        try:
            db_manager.execute_query("VACUUM")
            await query.answer("✅ تم تحسين قاعدة البيانات")
            await query.edit_message_text(
                f"⚡ **تحسين قاعدة البيانات**\n\n"
                f"✅ تم تحسين قاعدة البيانات بنجاح.\n\n"
                f"📌 أداء البوت أصبح أفضل.",
                reply_markup=admin_panel_keyboard(maintenance_mode)
            )
        except Exception as e:
            await query.answer("❌ فشل تحسين قاعدة البيانات")
            await query.edit_message_text(
                f"❌ **فشل تحسين قاعدة البيانات**\n\n"
                f"الخطأ: {str(e)}",
                reply_markup=admin_panel_keyboard(maintenance_mode)
            )

    elif query.data == "close_admin":
        await query.message.delete()
