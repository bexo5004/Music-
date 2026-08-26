import os
import asyncio
from datetime import datetime
from typing import Optional
from telegram import Update, Audio, Document, Video
from telegram.ext import ContextTypes

from utils import (
    check_subscription, is_maintenance, OWNER_ID, 
    MAX_FILE_SIZE, add_user, add_file_record,
    file_manager, db_manager, logger, cache,
    FileValidator, AudioProcessor
)

# ============================================
# دالة البداية المحسنة
# ============================================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج بداية البوت المحسن"""
    if await is_maintenance(update, context): 
        return
    
    user = update.effective_user
    user_id = user.id
    
    # التحقق من الاشتراك مع تخزين مؤقت
    cache_key = f"sub_{user_id}"
    if cache_key not in cache:
        if not await check_subscription(user_id, context):
            await update.message.reply_text(
                f"⚠️ **أنت غير مشترك في القناة!**\n\n"
                f"يجب الاشتراك أولاً في القناة التالية:\n"
                f"👉 @{CHANNEL_USERNAME}\n\n"
                f"بعد الاشتراك، ارسل /start مرة أخرى."
            )
            return
        cache[cache_key] = True
    
    # تسجيل المستخدم
    add_user(user_id, user.first_name, user.username)
    
    from keyboards import main_menu_keyboard
    
    await update.message.reply_text(
        f"🚀 **أهلاً بك {user.first_name}!**\n\n"
        f"📱 مرحباً بك في بوت الخدمات الصوتية المتقدم!\n\n"
        f"✨ يمكنك:\n"
        f"• 🎵 تعديل الأغاني وإضافة البيانات\n"
        f"• 🎬 استخراج الصوت من الفيديوهات\n"
        f"• 🖼️ إنشاء أغاني كاملة مع صور\n"
        f"• 📊 متابعة إحصائياتك\n\n"
        f"اختر ما تريد من الأزرار أدناه 👇",
        reply_markup=main_menu_keyboard()
    )

# ============================================
# معالج الكولباك المحسن
# ============================================
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار المحسن"""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    await query.answer()
    
    # التحقق من الاشتراك
    if not await check_subscription(user_id, context):
        await query.edit_message_text(
            f"⚠️ **أنت غير مشترك في القناة!**\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"👉 @{CHANNEL_USERNAME}"
        )
        return
    
    # ===== أزرار وضع "أغنيتي" =====
    if data == "mysong_edit":
        context.user_data.clear()
        context.user_data['mode'] = 'mysong_edit'
        context.user_data['step'] = 'waiting_for_audio'
        await query.edit_message_text(
            "🎵 **تعديل أغنية موجودة**\n\n"
            "📤 أرسل لي الآن الملف الصوتي (MP3) الذي تريد تعديله.\n\n"
            "⚠️ الحد الأقصى للحجم: 70MB\n"
            "✅ سأطلب منك الاسم والفنان والصورة بعد التحميل"
        )
    
    elif data == "mysong_extract":
        context.user_data.clear()
        context.user_data['mode'] = 'mysong_extract'
        context.user_data['step'] = 'waiting_for_video'
        await query.edit_message_text(
            "🎬 **استخراج صوت من فيديو**\n\n"
            "📤 أرسل لي الآن ملف الفيديو (MP4) لاستخراج الصوت منه.\n\n"
            "⚠️ الحد الأقصى للحجم: 70MB\n"
            "✅ سأستخرج الصوت ثم أطلب الاسم والصورة"
        )
    
    elif data == "mysong_new":
        context.user_data.clear()
        context.user_data['mode'] = 'mysong_new'
        context.user_data['step'] = 'waiting_for_audio'
        await query.edit_message_text(
            "🆕 **رفع ملف صوتي جديد**\n\n"
            "📤 أرسل لي الآن الملف الصوتي (MP3).\n\n"
            "⚠️ الحد الأقصى للحجم: 70MB\n"
            "✅ سأطلب منك الاسم والفنان والصورة بعد التحميل"
        )
    
    # ===== أزرار اختيار الجودة =====
    elif data.startswith("q_"):
        parts = data.split("_")
        quality = parts[1] + "k"
        action = parts[2]
        context.user_data['selected_quality'] = quality
        context.user_data['action_type'] = action
        
        if action == "edit":
            msg = "🎵 أرسل الآن الملف الصوتي (MP3) لتعديله:"
        else:
            msg = "🎬 أرسل الآن ملف الفيديو (MP4) لاستخراج الصوت منه:"
        
        await query.edit_message_text(
            f"✅ تم اختيار جودة {quality}.\n\n"
            f"{msg}\n\n"
            f"⚠️ الحد الأقصى للحجم: 70MB"
        )
    
    elif data == "cancel_action":
        context.user_data.clear()
        await query.edit_message_text("❌ تم إلغاء العملية.")
        await query.message.delete()
    
    # ===== أزرار الإحصائيات =====
    elif data == "my_stats":
        stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
        )
        files_count = stats[0][0] if stats else 0
        
        # آخر 5 ملفات
        last_files = db_manager.execute_query(
            "SELECT title, artist, date FROM files WHERE user_id = ? ORDER BY date DESC LIMIT 5",
            (user_id,)
        )
        
        message = f"📊 **إحصائياتك الشخصية**\n\n"
        message += f"✅ عدد الأغاني المعالجة: {files_count}\n\n"
        
        if last_files:
            message += "📝 **آخر 5 ملفات:**\n"
            for file in last_files:
                message += f"• {file[0]} - {file[1]} ({file[2][:10]})\n"
        else:
            message += "لا توجد ملفات معالجة حتى الآن."
        
        await query.edit_message_text(message)

# ============================================
# معالج الملفات المحسن (الصوت والفيديو)
# ============================================
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الملفات المحسن مع التحقق من الصحة"""
    if await is_maintenance(update, context): 
        return
    
    user_id = update.effective_user.id
    mode = context.user_data.get('mode')
    step = context.user_data.get('step')
    
    # التحقق من الاشتراك
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"⚠️ **أنت غير مشترك في القناة!**\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"👉 @{CHANNEL_USERNAME}"
        )
        return
    
    # ===== وضع mysong =====
    if mode and step:
        # استقبال الملف الصوتي
        if step == 'waiting_for_audio' and mode in ['mysong_edit', 'mysong_new']:
            file_obj = None
            if update.message.audio:
                file_obj = update.message.audio
            elif update.message.document:
                doc = update.message.document
                if doc.mime_type == 'audio/mpeg' or (doc.file_name and doc.file_name.endswith('.mp3')):
                    file_obj = doc
            
            if not file_obj:
                await update.message.reply_text(
                    "❌ **نوع الملف غير مدعوم**\n\n"
                    "الرجاء إرسال ملف صوتي بصيغة MP3."
                )
                return
            
            if file_obj.file_size > MAX_FILE_SIZE:
                await update.message.reply_text(
                    f"❌ **حجم الملف كبير جداً**\n\n"
                    f"الحد الأقصى: {MAX_FILE_SIZE // (1024*1024)}MB"
                )
                return
            
            wait_msg = await update.message.reply_text(
                "⏳ **جاري تحميل الملف الصوتي...**\n\n"
                "الرجاء الانتظار"
            )
            
            # تحميل الملف باستخدام المدير المحسن
            file_path = await file_manager.download_file(file_obj, f"audio_{user_id}")
            
            if not file_path:
                await wait_msg.edit_text(
                    "❌ **فشل تحميل الملف**\n\n"
                    "الرجاء المحاولة مرة أخرى."
                )
                return
            
            # التحقق من صحة الملف
            is_valid, message = FileValidator.validate_audio_file(file_path)
            if not is_valid:
                await wait_msg.edit_text(f"❌ **الملف غير صالح**\n\n{message}")
                # تنظيف الملف
                if os.path.exists(file_path):
                    os.remove(file_path)
                return
            
            context.user_data['audio_path'] = file_path
            context.user_data['step'] = 'waiting_for_title'
            await wait_msg.edit_text(
                f"✅ **تم تحميل الملف بنجاح!**\n\n"
                f"{message}\n\n"
                f"📝 **أرسل الآن اسم الأغنية:**"
            )
            return
        
        # استقبال ملف الفيديو
        elif step == 'waiting_for_video' and mode == 'mysong_extract':
            if not update.message.video and not update.message.document:
                await update.message.reply_text(
                    "❌ **نوع الملف غير مدعوم**\n\n"
                    "الرجاء إرسال ملف فيديو (MP4)."
                )
                return
            
            file_obj = update.message.video or update.message.document
            if file_obj.file_size > MAX_FILE_SIZE:
                await update.message.reply_text(
                    f"❌ **حجم الملف كبير جداً**\n\n"
                    f"الحد الأقصى: {MAX_FILE_SIZE // (1024*1024)}MB"
                )
                return
            
            wait_msg = await update.message.reply_text(
                "⏳ **جاري تحميل الفيديو واستخراج الصوت...**\n\n"
                "قد يستغرق هذا بضع ثوانٍ"
            )
            
            # تحميل الفيديو
            video_path = await file_manager.download_file(file_obj, f"video_{user_id}")
            
            if not video_path:
                await wait_msg.edit_text(
                    "❌ **فشل تحميل الفيديو**\n\n"
                    "الرجاء المحاولة مرة أخرى."
                )
                return
            
            # استخراج الصوت
            processor = AudioProcessor()
            audio_path = await processor.extract_audio_from_video(
                video_path, 
                context.user_data.get('selected_quality', '192k')
            )
            
            # تنظيف الفيديو
            if os.path.exists(video_path):
                os.remove(video_path)
            
            if not audio_path:
                await wait_msg.edit_text(
                    "❌ **فشل استخراج الصوت**\n\n"
                    "قد يكون الفيديو تالفاً أو لا يحتوي على صوت."
                )
                return
            
            context.user_data['audio_path'] = audio_path
            context.user_data['step'] = 'waiting_for_title'
            await wait_msg.edit_text(
                "✅ **تم استخراج الصوت بنجاح!**\n\n"
                "📝 **أرسل الآن اسم الأغنية:**"
            )
            return
        
        # إذا كان المستخدم في وضع mysong لكنه أرسل ملف غير مناسب
        else:
            if mode == 'mysong_extract':
                await update.message.reply_text("❌ الرجاء إرسال ملف فيديو MP4")
            elif mode in ['mysong_edit', 'mysong_new']:
                await update.message.reply_text("❌ الرجاء إرسال ملف صوتي MP3")
            return
    
    # ===== الوضع العادي =====
    action_type = context.user_data.get('action_type')
    quality = context.user_data.get('selected_quality', '192k')
    
    if not action_type:
        # إذا لم يتم تحديد نوع العملية، تجاهل الملف
        return
    
    file_obj = None
    if action_type == "edit":
        if update.message.audio:
            file_obj = update.message.audio
        elif update.message.document:
            doc = update.message.document
            if doc.mime_type == 'audio/mpeg' or (doc.file_name and doc.file_name.endswith('.mp3')):
                file_obj = doc
        
        if not file_obj:
            await update.message.reply_text(
                "❌ **نوع الملف غير مدعوم**\n\n"
                "الرجاء إرسال ملف صوتي MP3 للتعديل"
            )
            context.user_data.clear()
            return
            
    elif action_type == "extract":
        if update.message.video:
            file_obj = update.message.video
        
        if not file_obj:
            await update.message.reply_text(
                "❌ **نوع الملف غير مدعوم**\n\n"
                "الرجاء إرسال ملف فيديو MP4 لاستخراج الصوت"
            )
            context.user_data.clear()
            return
    
    if file_obj.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ **حجم الملف كبير جداً**\n\n"
            f"الحد الأقصى: {MAX_FILE_SIZE // (1024*1024)}MB"
        )
        context.user_data.clear()
        return
    
    wait_msg = await update.message.reply_text(
        "⏳ **جاري التحميل والمعالجة...**\n\n"
        "الرجاء الانتظار"
    )
    
    try:
        # تحميل الملف
        input_path = await file_manager.download_file(file_obj, f"input_{user_id}")
        
        if not input_path:
            await wait_msg.edit_text("❌ **فشل تحميل الملف**\n\nالرجاء المحاولة مرة أخرى.")
            context.user_data.clear()
            return
        
        # معالجة الصوت
        processor = AudioProcessor()
        output_path = await processor.process_audio(input_path, quality)
        
        # تنظيف ملف الإدخال
        if os.path.exists(input_path):
            os.remove(input_path)
        
        if not output_path:
            await wait_msg.edit_text(
                "❌ **فشل معالجة الملف**\n\n"
                "قد يكون الملف تالفاً أو غير مدعوم."
            )
            context.user_data.clear()
            return
        
        context.user_data["file_path"] = output_path
        context.user_data["step"] = "title"
        await wait_msg.edit_text(
            "✅ **تمت المعالجة بنجاح!**\n\n"
            "📝 **أرسل الآن اسم الأغنية:**"
        )
        
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة الملف: {e}")
        await wait_msg.edit_text(
            f"❌ **حدث خطأ أثناء المعالجة**\n\n"
            f"الرجاء المحاولة مرة أخرى."
        )
        context.user_data.clear()

# ============================================
# معالج الصور المحسن
# ============================================
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الصور المحسن مع التحقق من الصحة"""
    if await is_maintenance(update, context): 
        return
    
    user_id = update.effective_user.id
    
    # التحقق من الاشتراك
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"⚠️ **أنت غير مشترك في القناة!**\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"👉 @{CHANNEL_USERNAME}"
        )
        return
    
    if context.user_data.get('mode') and context.user_data.get('step') == 'waiting_for_cover':
        
        wait_msg = await update.message.reply_text(
            "🖼️ **جاري معالجة الصورة...**\n\n"
            "الرجاء الانتظار"
        )
        
        audio_path = context.user_data.get('audio_path')
        
        if not audio_path or not os.path.exists(audio_path):
            await wait_msg.edit_text(
                "❌ **حدث خطأ**\n\n"
                "الملف الصوتي غير موجود. الرجاء البدء من جديد."
            )
            context.user_data.clear()
            return
        
        # تحميل الصورة
        cover_path = None
        try:
            if update.message.photo:
                photo = update.message.photo[-1]
                cover_path = await file_manager.download_file(photo, f"cover_{user_id}")
            
            elif update.message.document:
                document = update.message.document
                mime_type = document.mime_type or ""
                file_name = document.file_name or ""
                
                if not (mime_type.startswith('image/') or file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))):
                    await wait_msg.edit_text(
                        "❌ **نوع الملف غير مدعوم**\n\n"
                        "الرجاء إرسال صورة بصيغة JPG, PNG, أو WEBP."
                    )
                    return
                
                cover_path = await file_manager.download_file(document, f"cover_{user_id}")
            
            else:
                await wait_msg.edit_text("❌ **لم ترسل صورة**\n\nالرجاء إرسال صورة.")
                return
            
            if not cover_path:
                await wait_msg.edit_text("❌ **فشل تحميل الصورة**\n\nالرجاء المحاولة مرة أخرى.")
                return
            
            # التحقق من صحة الصورة
            is_valid, message = FileValidator.validate_image_file(cover_path)
            if not is_valid:
                await wait_msg.edit_text(f"❌ **الصورة غير صالحة**\n\n{message}")
                if os.path.exists(cover_path):
                    os.remove(cover_path)
                return
            
            # إضافة البيانات الوصفية
            title = context.user_data.get('title', 'غير معروف')
            artist = context.user_data.get('artist', 'غير معروف')
            
            processor = AudioProcessor()
            success = processor.add_metadata(audio_path, title, artist, cover_path)
            
            if not success:
                await wait_msg.edit_text(
                    "❌ **فشل إضافة البيانات**\n\n"
                    "حدث خطأ أثناء إضافة الصورة والبيانات."
                )
                # تنظيف الملفات
                if os.path.exists(cover_path):
                    os.remove(cover_path)
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                context.user_data.clear()
                return
            
            # إرسال الملف النهائي
            with open(audio_path, "rb") as f:
                await update.message.reply_audio(
                    audio=f,
                    title=title,
                    performer=artist,
                    caption="✅ **تم إنشاء الأغنية بنجاح!** 🎉\n\n"
                           f"🎵 **الاسم:** {title}\n"
                           f"🎤 **الفنان:** {artist}"
                )
            
            # تسجيل العملية
            add_file_record(user_id, title, artist, audio_path)
            
            await wait_msg.delete()
            
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة الصورة: {e}")
            await update.message.reply_text(
                "❌ **حدث خطأ أثناء المعالجة**\n\n"
                "الرجاء المحاولة مرة أخرى."
            )
        
        finally:
            # تنظيف الملفات المؤقتة
            for path in [cover_path, audio_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass
            
            context.user_data.clear()
        return
    
    else:
        # إذا أرسل صورة خارج السياق
        await update.message.reply_text(
            "❌ **لست في وضع إضافة صورة حالياً**\n\n"
            "الرجاء استخدام الأزرار لبدء عملية جديدة."
        )

# ============================================
# معالج النصوص المحسن
# ============================================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج النصوص المحسن"""
    user_text = update.message.text
    user_id = update.effective_user.id
    
    # ===== الإذاعة للأدمن =====
    if context.user_data.get('admin_step') == 'broadcasting':
        if user_id != OWNER_ID:
            context.user_data['admin_step'] = None
            return
        
        # التحقق من وجود رسالة
        if not user_text or len(user_text.strip()) == 0:
            await update.message.reply_text("❌ **رسالة فارغة**\n\nالرجاء إرسال نص صالح.")
            return
        
        # إرسال الإذاعة على دفعات
        users = db_manager.execute_query("SELECT user_id FROM users")
        
        if not users:
            await update.message.reply_text("❌ **لا يوجد مستخدمين**\n\nلا يمكن إرسال الإذاعة.")
            context.user_data['admin_step'] = None
            return
        
        status_msg = await update.message.reply_text(
            f"📢 **جاري إرسال الإذاعة...**\n\n"
            f"👤 عدد المستخدمين: {len(users)}"
        )
        
        success_count = 0
        fail_count = 0
        batch_size = 50
        
        # إرسال على دفعات
        for i in range(0, len(users), batch_size):
            batch = users[i:i+batch_size]
            tasks = []
            
            for user in batch:
                try:
                    tasks.append(
                        context.bot.send_message(
                            chat_id=user[0],
                            text=f"📢 **إذاعة من المطور**\n\n{user_text}"
                        )
                    )
                except:
                    fail_count += 1
            
            # انتظار إرسال الدفعة
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count += sum(1 for r in results if not isinstance(r, Exception))
            fail_count += sum(1 for r in results if isinstance(r, Exception))
            
            # تحديث الحالة
            await status_msg.edit_text(
                f"📢 **جاري إرسال الإذاعة...**\n\n"
                f"✅ تم الإرسال: {success_count}\n"
                f"❌ فشل: {fail_count}"
            )
            
            # تجنب الحظر
            await asyncio.sleep(0.5)
        
        await status_msg.edit_text(
            f"✅ **تمت الإذاعة بنجاح!**\n\n"
            f"📨 تم الإرسال لـ: {success_count} مستخدم\n"
            f"❌ فشل الإرسال لـ: {fail_count} مستخدم"
        )
        
        context.user_data['admin_step'] = None
        return

    # ===== أزرار القائمة الرئيسية =====
    
    # ▶️ زر تشغيل البوت
    if user_text == "▶️ تشغيل البوت":
        await start_handler(update, context)
        return
    
    # 🎵 زر تعديل الأغنية
    elif user_text == "🎵 تعديل الأغنية":
        from keyboards import quality_keyboard
        await update.message.reply_text(
            "🎵 **تعديل أغنية**\n\n"
            "اختر جودة الصوت المطلوبة:",
            reply_markup=quality_keyboard("edit")
        )
        return
    
    # 🎬 زر استخراج صوت من فيديو
    elif user_text == "🎬 استخراج صوت من فيديو":
        from keyboards import quality_keyboard
        await update.message.reply_text(
            "🎬 **استخراج صوت من فيديو**\n\n"
            "اختر جودة الصوت المطلوبة:",
            reply_markup=quality_keyboard("extract")
        )
        return
    
    # 🖼️ زر إنشاء أغنية كاملة
    elif user_text == "🖼️ إنشاء أغنية كاملة (اسم + صورة + صوت)":
        from keyboards import my_song_menu_keyboard
        await update.message.reply_text(
            "🖼️ **إنشاء أغنية كاملة**\n\n"
            "اختر ما تريد فعله:",
            reply_markup=my_song_menu_keyboard()
        )
        return
    
    # 📊 زر إحصائياتي
    elif user_text == "📊 إحصائياتي":
        stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
        )
        files_count = stats[0][0] if stats else 0
        
        await update.message.reply_text(
            f"📊 **إحصائياتك الشخصية**\n\n"
            f"✅ عدد الأغاني المعالجة: {files_count}\n\n"
            f"💡 استخدم البوت لمعالجة المزيد من الأغاني!"
        )
        return
    
    # 🛠 زر لوحة التحكم
    elif user_text == "🛠 لوحة التحكم":
        if user_id == OWNER_ID:
            from admin_panel import panel_handler
            await panel_handler(update, context)
        else:
            await update.message.reply_text("❌ **هذه الخاصية متاحة للمطور فقط.**")
        return

    # ===== وضع mysong - استقبال النصوص =====
    if context.user_data.get('mode'):
        step = context.user_data.get('step')
        
        if step == 'waiting_for_title':
            if len(user_text) > 100:
                await update.message.reply_text(
                    "❌ **اسم الأغنية طويل جداً**\n\n"
                    "الحد الأقصى: 100 حرف"
                )
                return
            context.user_data['title'] = user_text.strip()
            context.user_data['step'] = 'waiting_for_artist'
            await update.message.reply_text(
                "🎤 **أرسل الآن اسم الفنان:**"
            )
            return
        
        elif step == 'waiting_for_artist':
            if len(user_text) > 100:
                await update.message.reply_text(
                    "❌ **اسم الفنان طويل جداً**\n\n"
                    "الحد الأقصى: 100 حرف"
                )
                return
            context.user_data['artist'] = user_text.strip()
            context.user_data['step'] = 'waiting_for_cover'
            await update.message.reply_text(
                "🖼️ **أرسل الآن الصورة التي تريد استخدامها كغلاف**\n\n"
                "📌 الصيغ المدعومة: JPG, PNG, WEBP\n"
                "📌 الحجم الموصى به: 500x500 بكسل"
            )
            return
        
        elif step == 'waiting_for_cover':
            await update.message.reply_text(
                "❌ **أنا في انتظار صورة وليس نص**\n\n"
                "الرجاء إرسال صورة."
            )
            return

    # ===== إكمال عملية التعديل العادي =====
    if "file_path" in context.user_data:
        step = context.user_data.get("step")
        file_path = context.user_data["file_path"]

        if step == "title":
            if len(user_text) > 100:
                await update.message.reply_text(
                    "❌ **اسم الأغنية طويل جداً**\n\n"
                    "الحد الأقصى: 100 حرف"
                )
                return
            context.user_data["title"] = user_text.strip()
            context.user_data["step"] = "artist"
            await update.message.reply_text(
                "🎤 **الآن أرسل اسم الفنان:**"
            )
        
        elif step == "artist":
            if len(user_text) > 100:
                await update.message.reply_text(
                    "❌ **اسم الفنان طويل جداً**\n\n"
                    "الحد الأقصى: 100 حرف"
                )
                return
            
            title = context.user_data["title"]
            artist = user_text.strip()
            
            wait_msg = await update.message.reply_text(
                "🔄 **جاري إضافة البيانات وإرسال الملف...**\n\n"
                "الرجاء الانتظار"
            )
            
            try:
                # إضافة البيانات الوصفية
                processor = AudioProcessor()
                success = processor.add_metadata(file_path, title, artist)
                
                if not success:
                    await wait_msg.edit_text(
                        "❌ **فشل إضافة البيانات**\n\n"
                        "حدث خطأ أثناء معالجة الملف."
                    )
                    return
                
                # إرسال الملف
                with open(file_path, "rb") as f:
                    await update.message.reply_audio(
                        audio=f,
                        title=title,
                        performer=artist,
                        caption="✅ **تم تعديل الأغنية بنجاح!** 🎉"
                    )
                
                # تسجيل العملية
                add_file_record(user_id, title, artist, file_path)
                
                await wait_msg.delete()
                
            except Exception as e:
                logger.error(f"❌ خطأ في حفظ البيانات: {e}")
                await wait_msg.edit_text(
                    "❌ **حدث خطأ أثناء المعالجة**\n\n"
                    "الرجاء المحاولة مرة أخرى."
                )
            
            finally:
                # تنظيف الملفات
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
                
                context.user_data.clear()
        
        return
    
    # رسالة افتراضية للنصوص غير المعروفة
    await update.message.reply_text(
        "❓ **عذراً، لم أفهم طلبك.**\n\n"
        "الرجاء استخدام الأزرار المتاحة في القائمة.\n"
        "إذا كنت بحاجة للمساعدة، أرسل /start لإعادة تشغيل البوت."
    )
