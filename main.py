import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

load_dotenv()

from handlers import start_handler, media_handler, text_handler, callback_query_handler, photo_handler
from admin_panel import panel_handler, admin_callback_handler
from utils import auto_clear_cache, logger

TOKEN = os.environ.get("BOT_TOKEN")

def main():
    if not TOKEN:
        print("خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
        return

    try:
        app = Application.builder().token(TOKEN).build()

        async def error_handler(update, context):
            logger.error(f"خطأ: {context.error}")
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى."
                    )
                except:
                    pass

        app.add_error_handler(error_handler)

        if app.job_queue:
            app.job_queue.run_repeating(
                lambda _: asyncio.create_task(auto_clear_cache()), 
                interval=1800,
                first=60
            )
            logger.info("تم تفعيل التنظيف التلقائي")

        app.add_handler(CommandHandler("start", start_handler))
        app.add_handler(CommandHandler("panel", panel_handler))
        
        app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(admin_|toggle_|close_admin)"))
        app.add_handler(CallbackQueryHandler(callback_query_handler))
        
        app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
        app.add_handler(MessageHandler(filters.Document.IMAGE, photo_handler))
        
        app.add_handler(MessageHandler(filters.AUDIO, media_handler))
        app.add_handler(MessageHandler(filters.VIDEO, media_handler))
        app.add_handler(MessageHandler(filters.Document.AUDIO, media_handler))
        app.add_handler(MessageHandler(filters.Document.VIDEO, media_handler))
        
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

        logger.info("البوت يعمل الآن...")
        print("البوت يعمل الآن...")
        app.run_polling()
        
    except Exception as e:
        logger.error(f"فشل تشغيل البوت: {e}")
        print(f"فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
