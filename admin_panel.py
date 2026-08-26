import os
import shutil
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from utils import OWNER_ID, db_manager, file_manager, logger, MAINTENANCE_MODE
from keyboards import admin_panel_keyboard

async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("هذه الخاصية متاحة للمطور فقط.")
        return

    stats = db_manager.execute_query("SELECT COUNT(*) FROM users")
    users_count = stats[0][0] if stats else 0
    
    await update.message.reply_text(
        f"لوحة تحكم المطور\n\n"
        f"المستخدمين: {users_count}\n"
        f"وضع الصيانة: {'مفعل' if MAINTENANCE_MODE else 'غير مفعل'}\n\n"
        f"اختر الإجراء المناسب:",
        reply_markup=admin_panel_keyboard(MAINTENANCE_MODE)
    )

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("غير مصرح لك!", show_alert=True)
        return

    import utils
    from keyboards import admin_panel_keyboard

    if query.data == "admin_stats":
        stats = db_manager.execute_query("SELECT COUNT(*) FROM users")
        users_count = stats[0][0] if stats else 0
        
        files_stats = db_manager.execute_query("SELECT COUNT(*) FROM files")
        files_count = files_stats[0][0] if files_stats else 0
        
        error_stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE status = 'error'"
        )
        errors_count = error_stats[0][0] if error_stats else 0
        
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE date LIKE ?", (f"{today}%",)
        )
        today_files = today_stats[0][0] if today_stats else 0
        
        await query.edit_message_text(
            f"إحصائيات البوت الشاملة\n\n"
            f"المستخدمين: {users_count}\n"
            f"العمليات الناجحة: {files_count}\n"
            f"عمليات اليوم: {today_files}\n"
            f"الأخطاء: {errors_count}\n"
            f"وضع الصيانة: {'مفعل' if MAINTENANCE_MODE else 'غير مفعل'}\n\n"
            f"حجم قاعدة البيانات: {os.path.getsize('bot_stats.db') // 1024} KB",
            reply_markup=admin_panel_keyboard(MAINTENANCE_MODE)
        )

    elif query.data == "toggle_maintenance":
        utils.MAINTENANCE_MODE = not utils.MAINTENANCE_MODE
        status_text = "تم تفعيل" if utils.MAINTENANCE_MODE else "تم إيقاف"
        
        await query.answer(f"{status_text} وضع الصيانة")
        await query.edit_message_text(
            f"{status_text} وضع الصيانة\n\n"
            f"الحالة الحالية: {'البوت في وضع الصيانة' if utils.MAINTENANCE_MODE else 'البوت يعمل طبيعياً'}\n\n"
            f"جميع المستخدمين العاديين سيتم منعهم من استخدام البوت.",
            reply_markup=admin_panel_keyboard(utils.MAINTENANCE_MODE)
        )

    elif query.data == "admin_broadcast":
        context.user_data['admin_step'] = 'broadcasting'
        users_count = db_manager.execute_query("SELECT COUNT(*) FROM users")
        count = users_count[0][0] if users_count else 0
        
        await query.edit_message_text(
            f"الإذاعة (Broadcast)\n\n"
            f"أرسل الآن الرسالة (نص فقط) ليتم إرسالها لجميع المستخدمين.\n\n"
            f"تحذير: لا يمكن التراجع عن هذه العملية.\n"
            f"سيتم إرسالها لـ {count} مستخدم."
        )

    elif query.data == "admin_clean":
        try:
            file_manager.cleanup_all()
            await query.answer("تم تنظيف الملفات المؤقتة")
        except Exception as e:
            await query.answer("فشل تنظيف الملفات")
            
        await query.edit_message_text(
            f"تنظيف الملفات المؤقتة\n\n"
            f"تم حذف الملفات المؤقتة بنجاح.\n\n"
            f"يمكنك أيضاً تشغيل التنظيف التلقائي كل 30 دقيقة.",
            reply_markup=admin_panel_keyboard(MAINTENANCE_MODE)
        )

    elif query.data == "admin_optimize":
        try:
            db_manager.execute_query("VACUUM")
            await query.answer("تم تحسين قاعدة البيانات")
            await query.edit_message_text(
                f"تحسين قاعدة البيانات\n\n"
                f"تم تحسين قاعدة البيانات بنجاح.\n\n"
                f"أداء البوت أصبح أفضل.",
                reply_markup=admin_panel_keyboard(MAINTENANCE_MODE)
            )
        except Exception as e:
            await query.answer("فشل تحسين قاعدة البيانات")
            await query.edit_message_text(
                f"فشل تحسين قاعدة البيانات\n\n"
                f"الخطأ: {str(e)}",
                reply_markup=admin_panel_keyboard(MAINTENANCE_MODE)
            )

    elif query.data == "close_admin":
        await query.message.delete()
