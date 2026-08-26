import os
import subprocess
import asyncio
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from mutagen.id3 import ID3, TIT2, TPE1, APIC, error as MutagenError
from PIL import Image

from utils import (
    check_subscription, is_maintenance, DB_FILE, OWNER_ID, 
    MAX_FILE_SIZE, get_channel_cover, add_user, add_file_record,
    file_manager, db_manager, logger, FileValidator, AudioProcessor,
    CHANNEL_USERNAME
)

from keyboards import main_menu_keyboard, quality_keyboard, my_song_menu_keyboard

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_maintenance(update, context): 
        return
    
    user = update.effective_user
    user_id = user.id
    
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"أنت غير مشترك في القناة!\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"@{CHANNEL_USERNAME}\n\n"
            f"بعد الاشتراك، ارسل /start مرة أخرى."
        )
        return

    add_user(user_id, user.first_name)

    await update.message.reply_text(
        f"أهلاً بك {user.first_name} في بوت الخدمات الصوتية!\n\n"
        "اختر ما تريد فعله من الأزرار أدناه:",
        reply_markup=main_menu_keyboard()
    )

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    await query.answer()
    
    if not await check_subscription(user_id, context):
        await query.edit_message_text(
            f"أنت غير مشترك في القناة!\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"@{CHANNEL_USERNAME}"
        )
        return
    
    if data == "mysong_edit":
        context.user_data.clear()
        context.user_data['mode'] = 'mysong_edit'
        context.user_data['step'] = 'waiting_for_audio'
        await query.edit_message_text(
            "تعديل أغنية موجودة\n\n"
            "أرسل لي الآن الملف الصوتي (MP3) الذي تريد تعديله.\n\n"
            "الحد الأقصى للحجم: 70MB\n"
            "سأطلب منك الاسم والفنان والصورة بعد التحميل"
        )
    
    elif data == "mysong_extract":
        context.user_data.clear()
        context.user_data['mode'] = 'mysong_extract'
        context.user_data['step'] = 'waiting_for_video'
        await query.edit_message_text(
            "استخراج صوت من فيديو\n\n"
            "أرسل لي الآن ملف الفيديو (MP4) لاستخراج الصوت منه.\n\n"
            "الحد الأقصى للحجم: 70MB\n"
            "سأستخرج الصوت ثم أطلب الاسم والصورة"
        )
    
    elif data == "mysong_new":
        context.user_data.clear()
        context.user_data['mode'] = 'mysong_new'
        context.user_data['step'] = 'waiting_for_audio'
        await query.edit_message_text(
            "رفع ملف صوتي جديد\n\n"
            "أرسل لي الآن الملف الصوتي (MP3).\n\n"
            "الحد الأقصى للحجم: 70MB\n"
            "سأطلب منك الاسم والفنان والصورة بعد التحميل"
        )
    
    elif data.startswith("q_"):
        parts = data.split("_")
        quality = parts[1] + "k"
        action = parts[2]
        context.user_data['selected_quality'] = quality
        context.user_data['action_type'] = action
        
        if action == "edit":
            msg = "أرسل الآن الملف الصوتي (MP3) لتعديله:"
        else:
            msg = "أرسل الآن ملف الفيديو (MP4) لاستخراج الصوت منه:"
        
        await query.edit_message_text(
            f"تم اختيار جودة {quality}.\n\n{msg}\n\nالحد الأقصى للحجم: 70MB"
        )
    
    elif data == "cancel_action":
        context.user_data.clear()
        await query.edit_message_text("تم إلغاء العملية.")
        await query.message.delete()
    
    elif data == "my_stats":
        stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
        )
        files_count = stats[0][0] if stats else 0
        
        last_files = db_manager.execute_query(
            "SELECT title, artist, date FROM files WHERE user_id = ? ORDER BY date DESC LIMIT 5",
            (user_id,)
        )
        
        message = f"إحصائياتك الشخصية\n\n"
        message += f"عدد الأغاني المعالجة: {files_count}\n\n"
        
        if last_files:
            message += "آخر 5 ملفات:\n"
            for file in last_files:
                message += f"{file[0]} - {file[1]} ({file[2][:10]})\n"
        else:
            message += "لا توجد ملفات معالجة حتى الآن."
        
        await query.edit_message_text(message)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_maintenance(update, context): 
        return
    
    user_id = update.effective_user.id
    
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"أنت غير مشترك في القناة!\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"@{CHANNEL_USERNAME}"
        )
        return
    
    if context.user_data.get('mode') and context.user_data.get('step') == 'waiting_for_cover':
        
        wait_msg = await update.message.reply_text(
            "جاري معالجة الصورة...\n\nالرجاء الانتظار"
        )
        
        audio_path = context.user_data.get('audio_path')
        
        if not audio_path or not os.path.exists(audio_path):
            await wait_msg.edit_text(
                "حدث خطأ\n\nالملف الصوتي غير موجود. الرجاء البدء من جديد."
            )
            context.user_data.clear()
            return
        
        cover_path = None
        try:
            if update.message.photo:
                photo = update.message.photo[-1]
                cover_path = await file_manager.download_file(photo, f"cover_{user_id}")
                
            elif update.message.document:
                document = update.message.document
                mime_type = document.mime_type or ""
                file_name = document.file_name or ""
                
                is_image = (
                    mime_type.startswith('image/') or 
                    file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'))
                )
                
                if not is_image:
                    await wait_msg.edit_text(
                        "نوع الملف غير مدعوم\n\nالرجاء إرسال صورة بصيغة: JPG, PNG, GIF, WEBP, BMP, TIFF"
                    )
                    return
                
                cover_path = await file_manager.download_file(document, f"cover_{user_id}")
                
                if cover_path and os.path.exists(cover_path):
                    try:
                        from PIL import Image
                        img = Image.open(cover_path)
                        img.verify()
                    except Exception as e:
                        await wait_msg.edit_text(
                            f"الملف ليس صورة صالحة\n\nالخطأ: {str(e)}"
                        )
                        if cover_path and os.path.exists(cover_path):
                            os.remove(cover_path)
                        return
            
            else:
                await wait_msg.edit_text(
                    "لم ترسل صورة\n\nالرجاء إرسال صورة بأحد الطرق التالية:\n"
                    "ارسال صورة من الكاميرا\nارسال ملف صورة"
                )
                return
            
            if not cover_path or not os.path.exists(cover_path):
                await wait_msg.edit_text(
                    "فشل تحميل الصورة\n\nالرجاء المحاولة مرة أخرى."
                )
                context.user_data.clear()
                return
            
            try:
                from PIL import Image
                
                img = Image.open(cover_path)
                
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode == 'RGBA':
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                max_size = 2000
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                jpg_path = cover_path.replace(os.path.splitext(cover_path)[1], '.jpg')
                img.save(jpg_path, 'JPEG', quality=95, optimize=True)
                
                if os.path.exists(cover_path) and cover_path != jpg_path:
                    os.remove(cover_path)
                cover_path = jpg_path
                
                if os.path.getsize(cover_path) > 5 * 1024 * 1024:
                    img.save(jpg_path, 'JPEG', quality=70, optimize=True)
                    
                logger.info(f"تم تحويل الصورة إلى JPG: {cover_path}")
                
            except Exception as e:
                logger.error(f"خطأ في تحويل الصورة: {e}")
            
            title = context.user_data.get('title', 'غير معروف')
            artist = context.user_data.get('artist', 'غير معروف')
            
            processor = AudioProcessor()
            success = processor.add_metadata(audio_path, title, artist, cover_path)
            
            if not success:
                await wait_msg.edit_text(
                    "فشل إضافة البيانات\n\nحدث خطأ أثناء إضافة الصورة والبيانات."
                )
                for path in [cover_path, audio_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except:
                            pass
                context.user_data.clear()
                return
            
            try:
                with open(audio_path, "rb") as f:
                    await update.message.reply_audio(
                        audio=f,
                        title=title,
                        performer=artist,
                        caption=f"تم إنشاء الأغنية بنجاح!\n\nالاسم: {title}\nالفنان: {artist}"
                    )
                
                add_file_record(user_id, title, artist, audio_path)
                await wait_msg.delete()
                
            except Exception as e:
                logger.error(f"خطأ في إرسال الملف: {e}")
                await wait_msg.edit_text(
                    "فشل إرسال الملف\n\nحدث خطأ أثناء إرسال الأغنية."
                )
            
        except Exception as e:
            logger.error(f"خطأ في معالجة الصورة: {e}")
            await update.message.reply_text(
                f"حدث خطأ أثناء المعالجة\n\nالرجاء المحاولة مرة أخرى."
            )
        
        finally:
            for path in [cover_path, audio_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"تم حذف: {path}")
                    except Exception as e:
                        logger.warning(f"فشل حذف {path}: {e}")
            
            context.user_data.clear()
        return
    
    else:
        await update.message.reply_text(
            "لست في وضع إضافة صورة حالياً\n\nالرجاء استخدام الأزرار لبدء عملية جديدة."
        )

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_maintenance(update, context): 
        return
    
    user_id = update.effective_user.id
    mode = context.user_data.get('mode')
    step = context.user_data.get('step')
    
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"أنت غير مشترك في القناة!\n\n"
            f"يجب الاشتراك أولاً في القناة التالية:\n"
            f"@{CHANNEL_USERNAME}"
        )
        return
    
    if mode == 'mysong_extract' and step == 'waiting_for_video':
        
        video_obj = None
        if update.message.video:
            video_obj = update.message.video
        elif update.message.document:
            doc = update.message.document
            mime_type = doc.mime_type or ""
            file_name = doc.file_name or ""
            if (mime_type.startswith('video/') or 
                file_name.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv'))):
                video_obj = doc
        
        if not video_obj:
            await update.message.reply_text(
                "نوع الملف غير مدعوم\n\nالرجاء إرسال ملف فيديو بصيغة:\nMP4, MOV, AVI, MKV, WEBM, FLV"
            )
            return
        
        if video_obj.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"حجم الملف كبير جداً\n\nالحد الأقصى: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
            return
        
        wait_msg = await update.message.reply_text(
            "جاري تحميل الفيديو واستخراج الصوت...\n\nقد يستغرق هذا بضع ثوان"
        )
        
        video_path = await file_manager.download_file(video_obj, f"video_{user_id}")
        
        if not video_path or not os.path.exists(video_path):
            await wait_msg.edit_text(
                "فشل تحميل الفيديو\n\nالرجاء المحاولة مرة أخرى."
            )
            context.user_data.clear()
            return
        
        try:
            processor = AudioProcessor()
            quality = context.user_data.get('selected_quality', '192k')
            audio_path = await processor.extract_audio_from_video(video_path, quality)
            
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"تم حذف الفيديو: {video_path}")
            
            if not audio_path or not os.path.exists(audio_path):
                await wait_msg.edit_text(
                    "فشل استخراج الصوت\n\nقد يكون الفيديو تالفاً أو لا يحتوي على صوت."
                )
                context.user_data.clear()
                return
            
            is_valid, message = FileValidator.validate_audio_file(audio_path)
            if not is_valid:
                await wait_msg.edit_text(
                    f"الملف الصوتي غير صالح\n\n{message}"
                )
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                context.user_data.clear()
                return
            
            context.user_data['audio_path'] = audio_path
            context.user_data['step'] = 'waiting_for_title'
            await wait_msg.edit_text(
                f"تم استخراج الصوت بنجاح!\n\n{message}\n\nأرسل الآن اسم الأغنية:"
            )
            return
            
        except Exception as e:
            logger.error(f"خطأ في استخراج الصوت: {e}")
            await wait_msg.edit_text(
                "حدث خطأ أثناء استخراج الصوت\n\nالرجاء المحاولة مرة أخرى."
            )
            for path in [video_path, audio_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass
            context.user_data.clear()
            return
    
    elif mode in ['mysong_edit', 'mysong_new'] and step == 'waiting_for_audio':
        
        file_obj = None
        if update.message.audio:
            file_obj = update.message.audio
        elif update.message.document:
            doc = update.message.document
            mime_type = doc.mime_type or ""
            file_name = doc.file_name or ""
            if (mime_type.startswith('audio/') or 
                file_name.lower().endswith(('.mp3', '.m4a', '.aac', '.wav', '.ogg'))):
                file_obj = doc
        
        if not file_obj:
            await update.message.reply_text(
                "نوع الملف غير مدعوم\n\nالرجاء إرسال ملف صوتي بصيغة:\nMP3, M4A, AAC, WAV, OGG"
            )
            return
        
        if file_obj.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"حجم الملف كبير جداً\n\nالحد الأقصى: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
            return
        
        wait_msg = await update.message.reply_text(
            "جاري تحميل الملف الصوتي...\n\nالرجاء الانتظار"
        )
        
        audio_path = await file_manager.download_file(file_obj, f"audio_{user_id}")
        
        if not audio_path or not os.path.exists(audio_path):
            await wait_msg.edit_text(
                "فشل تحميل الملف\n\nالرجاء المحاولة مرة أخرى."
            )
            context.user_data.clear()
            return
        
        is_valid, message = FileValidator.validate_audio_file(audio_path)
        if not is_valid:
            await wait_msg.edit_text(
                f"الملف غير صالح\n\n{message}"
            )
            if os.path.exists(audio_path):
                os.remove(audio_path)
            context.user_data.clear()
            return
        
        context.user_data['audio_path'] = audio_path
        context.user_data['step'] = 'waiting_for_title'
        await wait_msg.edit_text(
            f"تم تحميل الملف بنجاح!\n\n{message}\n\nأرسل الآن اسم الأغنية:"
        )
        return
    
    else:
        action_type = context.user_data.get('action_type')
        quality = context.user_data.get('selected_quality', '192k')
        
        if not action_type:
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
                    "نوع الملف غير مدعوم\n\nالرجاء إرسال ملف صوتي MP3 للتعديل"
                )
                context.user_data.clear()
                return
                
        elif action_type == "extract":
            if update.message.video:
                file_obj = update.message.video
            
            if not file_obj:
                await update.message.reply_text(
                    "نوع الملف غير مدعوم\n\nالرجاء إرسال ملف فيديو MP4 لاستخراج الصوت"
                )
                context.user_data.clear()
                return
        
        if file_obj.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"حجم الملف كبير جداً\n\nالحد الأقصى: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
            context.user_data.clear()
            return
        
        wait_msg = await update.message.reply_text(
            "جاري التحميل والمعالجة...\n\nالرجاء الانتظار"
        )
        
        try:
            input_path = await file_manager.download_file(file_obj, f"input_{user_id}")
            
            if not input_path:
                await wait_msg.edit_text("فشل تحميل الملف\n\nالرجاء المحاولة مرة أخرى.")
                context.user_data.clear()
                return
            
            processor = AudioProcessor()
            output_path = await processor.process_audio(input_path, quality)
            
            if os.path.exists(input_path):
                os.remove(input_path)
            
            if not output_path:
                await wait_msg.edit_text(
                    "فشل معالجة الملف\n\nقد يكون الملف تالفاً أو غير مدعوم."
                )
                context.user_data.clear()
                return
            
            context.user_data["file_path"] = output_path
            context.user_data["step"] = "title"
            await wait_msg.edit_text(
                "تمت المعالجة بنجاح!\n\nأرسل الآن اسم الأغنية:"
            )
            
        except Exception as e:
            logger.error(f"خطأ في معالجة الملف: {e}")
            await wait_msg.edit_text(
                f"حدث خطأ أثناء المعالجة\n\nالرجاء المحاولة مرة أخرى."
            )
            context.user_data.clear()

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.effective_user.id
    
    if context.user_data.get('admin_step') == 'broadcasting':
        if user_id != OWNER_ID:
            context.user_data['admin_step'] = None
            return
        
        if not user_text or len(user_text.strip()) == 0:
            await update.message.reply_text("رسالة فارغة\n\nالرجاء إرسال نص صالح.")
            return
        
        users = db_manager.execute_query("SELECT user_id FROM users")
        
        if not users:
            await update.message.reply_text("لا يوجد مستخدمين\n\nلا يمكن إرسال الإذاعة.")
            context.user_data['admin_step'] = None
            return
        
        status_msg = await update.message.reply_text(
            f"جاري إرسال الإذاعة...\n\nعدد المستخدمين: {len(users)}"
        )
        
        success_count = 0
        fail_count = 0
        batch_size = 50
        
        for i in range(0, len(users), batch_size):
            batch = users[i:i+batch_size]
            tasks = []
            
            for user in batch:
                try:
                    tasks.append(
                        context.bot.send_message(
                            chat_id=user[0],
                            text=f"إذاعة من المطور\n\n{user_text}"
                        )
                    )
                except:
                    fail_count += 1
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count += sum(1 for r in results if not isinstance(r, Exception))
            fail_count += sum(1 for r in results if isinstance(r, Exception))
            
            await status_msg.edit_text(
                f"جاري إرسال الإذاعة...\n\nتم الإرسال: {success_count}\nفشل: {fail_count}"
            )
            
            await asyncio.sleep(0.5)
        
        await status_msg.edit_text(
            f"تمت الإذاعة بنجاح!\n\nتم الإرسال لـ: {success_count} مستخدم\nفشل الإرسال لـ: {fail_count} مستخدم"
        )
        
        context.user_data['admin_step'] = None
        return
    
    if user_text == "تشغيل البوت" or user_text == "▶️ تشغيل البوت":
        await start_handler(update, context)
        return
    
    elif user_text == "تعديل الأغنية" or user_text == "🎵 تعديل الأغنية":
        await update.message.reply_text(
            "تعديل أغنية\n\nاختر جودة الصوت المطلوبة:",
            reply_markup=quality_keyboard("edit")
        )
        return
    
    elif user_text == "استخراج صوت من فيديو" or user_text == "🎬 استخراج صوت من فيديو":
        await update.message.reply_text(
            "استخراج صوت من فيديو\n\nاختر جودة الصوت المطلوبة:",
            reply_markup=quality_keyboard("extract")
        )
        return
    
    elif user_text == "إنشاء أغنية كاملة (اسم + صورة + صوت)" or user_text == "🖼️ إنشاء أغنية كاملة (اسم + صورة + صوت)":
        await update.message.reply_text(
            "إنشاء أغنية كاملة\n\nاختر ما تريد فعله:",
            reply_markup=my_song_menu_keyboard()
        )
        return
    
    elif user_text == "إحصائياتي" or user_text == "📊 إحصائياتي":
        stats = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
        )
        files_count = stats[0][0] if stats else 0
        
        await update.message.reply_text(
            f"إحصائياتك الشخصية\n\nعدد الأغاني المعالجة: {files_count}\n\nاستخدم البوت لمعالجة المزيد من الأغاني!"
        )
        return
    
    elif user_text == "لوحة التحكم" or user_text == "🛠 لوحة التحكم":
        if user_id == OWNER_ID:
            from admin_panel import panel_handler
            await panel_handler(update, context)
        else:
            await update.message.reply_text("هذه الخاصية متاحة للمطور فقط.")
        return
    
    if context.user_data.get('mode'):
        step = context.user_data.get('step')
        
        if step == 'waiting_for_title':
            if len(user_text) > 100:
                await update.message.reply_text(
                    "اسم الأغنية طويل جداً\n\nالحد الأقصى: 100 حرف"
                )
                return
            context.user_data['title'] = user_text.strip()
            context.user_data['step'] = 'waiting_for_artist'
            await update.message.reply_text("أرسل الآن اسم الفنان:")
            return
        
        elif step == 'waiting_for_artist':
            if len(user_text) > 100:
                await update.message.reply_text(
                    "اسم الفنان طويل جداً\n\nالحد الأقصى: 100 حرف"
                )
                return
            context.user_data['artist'] = user_text.strip()
            context.user_data['step'] = 'waiting_for_cover'
            await update.message.reply_text(
                "أرسل الآن الصورة التي تريد استخدامها كغلاف\n\n"
                "الصيغ المدعومة: JPG, PNG, WEBP, GIF, BMP, TIFF\n"
                "الحجم الموصى به: 500x500 بكسل"
            )
            return
        
        elif step == 'waiting_for_cover':
            await update.message.reply_text(
                "أنا في انتظار صورة وليس نص\n\nالرجاء إرسال صورة."
            )
            return
    
    if "file_path" in context.user_data:
        step = context.user_data.get("step")
        file_path = context.user_data["file_path"]

        if step == "title":
            if len(user_text) > 100:
                await update.message.reply_text(
                    "اسم الأغنية طويل جداً\n\nالحد الأقصى: 100 حرف"
                )
                return
            context.user_data["title"] = user_text.strip()
            context.user_data["step"] = "artist"
            await update.message.reply_text("الآن أرسل اسم الفنان:")
        
        elif step == "artist":
            if len(user_text) > 100:
                await update.message.reply_text(
                    "اسم الفنان طويل جداً\n\nالحد الأقصى: 100 حرف"
                )
                return
            
            title = context.user_data["title"]
            artist = user_text.strip()
            
            wait_msg = await update.message.reply_text(
                "جاري إضافة البيانات وإرسال الملف...\n\nالرجاء الانتظار"
            )
            
            try:
                processor = AudioProcessor()
                success = processor.add_metadata(file_path, title, artist)
                
                if not success:
                    await wait_msg.edit_text(
                        "فشل إضافة البيانات\n\nحدث خطأ أثناء معالجة الملف."
                    )
                    return
                
                with open(file_path, "rb") as f:
                    await update.message.reply_audio(
                        audio=f,
                        title=title,
                        performer=artist,
                        caption="تم تعديل الأغنية بنجاح!"
                    )
                
                add_file_record(user_id, title, artist, file_path)
                await wait_msg.delete()
                
            except Exception as e:
                logger.error(f"خطأ في حفظ البيانات: {e}")
                await wait_msg.edit_text(
                    "حدث خطأ أثناء المعالجة\n\nالرجاء المحاولة مرة أخرى."
                )
            
            finally:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
                
                context.user_data.clear()
        
        return
    
    await update.message.reply_text(
        "عذراً، لم أفهم طلبك.\n\n"
        "الرجاء استخدام الأزرار المتاحة في القائمة.\n"
        "إذا كنت بحاجة للمساعدة، أرسل /start لإعادة تشغيل البوت."
    )
