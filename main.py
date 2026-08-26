import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# تحميل متغيرات البيئة
load_dotenv()

# استيراد المعالجات
from handlers import start_handler, media_handler, text_handler, callback_query_handler, photo_handler
from admin_panel import panel_handler, admin_callback_handler
from utils import auto_clear_cache, logger

# إعدادات الـ Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.environ.get("BOT_TOKEN")

def main():
    if not TOKEN:
        print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
        return

    # بناء تطبيق البوت
    app = Application.builder().token(TOKEN).build()

    # المهام الدورية - تنظيف الملفات المؤقتة كل 30 دقيقة
    if app.job_queue:
        app.job_queue.run_repeating(
            lambda _: asyncio.create_task(auto_clear_cache()), 
            interval=1800,  # 30 دقيقة
            first=60  # بعد 60 ثانية من التشغيل
        )
        logger.info("🔄 تم تفعيل التنظيف التلقائي للملفات المؤقتة")

    # === ترتيب المعالجات (من الأخص إلى الأعم) ===
    
    # 1. الأوامر الأساسية
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("panel", panel_handler))
    
    # 2. أزرار الكولباك
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(admin_|toggle_|close_admin|admin_)"))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # 3. معالج الصور (يجب أن يأتي قبل الوسائط)
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.Document.IMAGE, photo_handler))
    
    # 4. معالج الوسائط (صوت وفيديو)
    app.add_handler(MessageHandler(filters.AUDIO, media_handler))
    app.add_handler(MessageHandler(filters.VIDEO, media_handler))
    app.add_handler(MessageHandler(filters.Document.AUDIO, media_handler))
    app.add_handler(MessageHandler(filters.Document.VIDEO, media_handler))
    
    # 5. معالج النصوص (يأتي أخيراً)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("🤖 البوت يعمل الآن بنجاح مع التحسينات الكاملة...")
    print("🤖 البوت يعمل الآن بنجاح مع التحسينات الكاملة...")
    app.run_polling()

if __name__ == "__main__":
    main()
