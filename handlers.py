import os
import subprocess
import asyncio
import sqlite3
import shutil
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from telegram import Update
from telegram.ext import ContextTypes

from utils import (
    check_subscription,
    is_maintenance,
    DB_FILE,
    OWNER_ID,
    MAX_FILE_SIZE,  # ✅ تم التأكيد على وجودها
    get_channel_cover,
    add_user,
    add_file_record,
)

# ============================================================
# 📋 إعدادات اللوغينغ
# ============================================================
logger = logging.getLogger(__name__)

# ============================================================
# 🎛️ إعدادات الأداء
# ============================================================
MAX_CONCURRENT_PROCESSES = 2
TELEGRAM_AUDIO_LIMIT = 50 * 1024 * 1024

# ============================================================
# 📂 مدير العمليات غير المتزامنة
# ============================================================
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROCESSES)

# ============================================================
# 📋 الصيغ المدعومة
# ============================================================
SUPPORTED_AUDIO_EXTENSIONS: Tuple[str, ...] = (
    '.mp3', '.m4a', '.aac', '.ogg', '.wav',
    '.flac', '.wma', '.opus', '.aiff', '.alac',
    '.ape', '.amr', '.3gp', '.mka', '.ac3', '.dts', '.midi'
)

SUPPORTED_AUDIO_MIME_TYPES: Tuple[str, ...] = (
    'audio/mpeg', 'audio/mp4', 'audio/aac', 'audio/ogg',
    'audio/wav', 'audio/flac', 'audio/x-wav', 'audio/opus',
    'audio/webm', 'audio/x-m4a', 'audio/aiff', 'audio/amr',
    'audio/ac3', 'audio/midi'
)

IMAGE_EXTENSIONS: Tuple[str, ...] = ('.jpg', '.jpeg', '.png', '.gif', '.webp')

AUDIO_QUALITIES: Tuple[Tuple[int, str], ...] = (
    (320, "320k"), (256, "256k"), (224, "224k"),
    (192, "192k"), (160, "160k"), (128, "128k"),
    (96, "96k"), (64, "64k"), (48, "48k"), (32, "32k")
)


# ============================================================
# 🧹 دالات إدارة الملفات
# ============================================================

def safe_remove(file_path: Optional[str]) -> bool:
    """حذف ملف بأمان مع التحقق من وجوده"""
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        os.remove(file_path)
        logger.debug(f"🗑️ تم حذف الملف: {file_path}")
        return True
    except OSError as e:
        logger.warning(f"⚠️ فشل حذف الملف {file_path}: {e}")
        return False


def safe_remove_many(file_paths: List[Optional[str]]) -> int:
    """حذف مجموعة من الملفات بأمان"""
    deleted = 0
    for file_path in file_paths:
        if safe_remove(file_path):
            deleted += 1
    return deleted


def get_unique_filename(prefix: str, extension: str = '.mp3') -> str:
    """إنشاء اسم ملف فريد باستخدام UUID"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}{extension}"


def is_audio_file(file_name: Optional[str], mime_type: Optional[str]) -> bool:
    """التحقق مما إذا كان الملف صوتياً"""
    if file_name:
        ext = Path(file_name).suffix.lower()
        if ext in SUPPORTED_AUDIO_EXTENSIONS:
            return True
    if mime_type and (mime_type in SUPPORTED_AUDIO_MIME_TYPES or mime_type.startswith('audio/')):
        return True
    return False


def is_image_file(file_name: Optional[str], mime_type: Optional[str]) -> bool:
    """التحقق مما إذا كان الملف صورة"""
    if file_name:
        ext = Path(file_name).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return True
    if mime_type and mime_type.startswith('image/'):
        return True
    return False


# ============================================================
# 🎬 مدير FFmpeg
# ============================================================

class FFmpegManager:
    """مدير موحد لأوامر FFmpeg مع دعم غير متزامن"""

    DEFAULT_TIMEOUT = 600
    DEFAULT_QUALITY = "192k"
    SAMPLE_RATE = "44100"
    AUDIO_CHANNELS = 2

    @staticmethod
    async def run(
        cmd: List[str],
        timeout: int = DEFAULT_TIMEOUT,
        description: str = "FFmpeg process"
    ) -> Tuple[int, bytes, bytes]:
        """تشغيل أمر FFmpeg بشكل غير متزامن مع Timeout"""
        process = None
        try:
            async with _semaphore:
                logger.debug(f"▶️ بدء {description}: {' '.join(cmd)}")
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                if process.returncode == 0:
                    logger.debug(f"✅ نجاح {description}")
                else:
                    logger.warning(f"⚠️ فشل {description}: {stderr.decode('utf-8', errors='ignore')[:200]}")
                return process.returncode, stdout, stderr
        except asyncio.TimeoutError:
            if process:
                process.kill()
                await process.wait()
            logger.error(f"⏰ انتهت مهلة {description} بعد {timeout} ثانية")
            return -1, b'', f"Timeout after {timeout}s".encode()
        except Exception as e:
            logger.exception(f"❌ خطأ في {description}: {e}")
            return -1, b'', str(e).encode()

    @classmethod
    def build_convert_cmd(cls, input_path: str, output_path: str, quality: str = DEFAULT_QUALITY) -> List[str]:
        """بناء أمر تحويل أي ملف إلى MP3"""
        return [
            "ffmpeg", "-i", input_path,
            "-c:a", "libmp3lame",
            "-b:a", quality,
            "-ac", str(cls.AUDIO_CHANNELS),
            "-ar", cls.SAMPLE_RATE,
            output_path, "-y"
        ]

    @classmethod
    def build_merge_cover_cmd(
        cls,
        audio_path: str,
        cover_path: str,
        output_path: str,
        title: str,
        artist: str,
        quality: str = DEFAULT_QUALITY
    ) -> List[str]:
        """بناء أمر دمج الصورة مع الصوت"""
        return [
            "ffmpeg", "-i", audio_path,
            "-i", cover_path,
            "-map", "0:a",
            "-map", "1",
            "-c:a", "libmp3lame",
            "-b:a", quality,
            "-ar", cls.SAMPLE_RATE,
            "-id3v2_version", "3",
            "-metadata", f"title={title}",
            "-metadata", f"artist={artist}",
            output_path, "-y"
        ]

    @classmethod
    def build_extract_audio_cmd(cls, video_path: str, output_path: str, quality: str = DEFAULT_QUALITY) -> List[str]:
        """بناء أمر استخراج الصوت من الفيديو"""
        return [
            "ffmpeg", "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ac", str(cls.AUDIO_CHANNELS),
            "-b:a", quality,
            "-ar", cls.SAMPLE_RATE,
            output_path, "-y"
        ]

    @classmethod
    async def convert_to_mp3(cls, input_path: str, output_path: str, quality: str = DEFAULT_QUALITY) -> bool:
        """تحويل ملف صوتي إلى MP3"""
        cmd = cls.build_convert_cmd(input_path, output_path, quality)
        return_code, _, _ = await cls.run(cmd)
        return return_code == 0 and os.path.exists(output_path)

    @classmethod
    async def compress_audio(cls, input_path: str, output_path: str, target_size_mb: int = 48) -> bool:
        """ضغط ملف صوتي مع حساب تلقائي للجودة"""
        if not os.path.exists(input_path):
            return False

        current_size = os.path.getsize(input_path) / (1024 * 1024)
        if current_size <= target_size_mb:
            shutil.copy(input_path, output_path)
            return True

        duration = get_audio_duration(input_path)
        quality = calculate_quality(target_size_mb, duration)

        cmd = cls.build_convert_cmd(input_path, output_path, quality)
        return_code, _, _ = await cls.run(cmd)

        if return_code == 0 and os.path.exists(output_path):
            new_size = os.path.getsize(output_path) / (1024 * 1024)
            if new_size <= target_size_mb:
                return True

        # محاولة بجودة منخفضة
        fallback_cmd = cls.build_convert_cmd(input_path, output_path, "32k")
        fallback_cmd.extend(["-ac", "1", "-ar", "22050"])
        return_code, _, _ = await cls.run(fallback_cmd)
        return return_code == 0 and os.path.exists(output_path)


# ============================================================
# 📊 دالات استخراج المعلومات
# ============================================================

def get_audio_duration(file_path: str) -> float:
    """الحصول على مدة الملف الصوتي بالثواني"""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout:
            return float(result.stdout.strip())
    except Exception as e:
        logger.debug(f"فشل قراءة المدة: {e}")
    return 0.0


def calculate_quality(target_size_mb: int, duration_seconds: float) -> str:
    """حساب الجودة المطلوبة للوصول إلى الحجم المستهدف"""
    if duration_seconds <= 0:
        return "128k"
    target_bitrate = (target_size_mb * 8 * 1024) / duration_seconds
    for bitrate, quality in AUDIO_QUALITIES:
        if target_bitrate >= bitrate:
            return quality
    return "32k"


def get_audio_metadata(file_path: str) -> Dict[str, Any]:
    """استخراج معلومات الملف الصوتي"""
    metadata = {
        "duration": 0.0,
        "size_mb": 0.0,
        "bitrate": "غير معروف",
        "sample_rate": "غير معروف"
    }
    try:
        metadata["duration"] = get_audio_duration(file_path)
        metadata["size_mb"] = os.path.getsize(file_path) / (1024 * 1024)

        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=bit_rate,sample_rate",
            "-of", "default=noprint_wrappers=1",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith('bit_rate='):
                    bitrate = line.split('=')[1]
                    if bitrate and bitrate != 'N/A':
                        metadata["bitrate"] = f"{int(bitrate) // 1000}k"
                if line.startswith('sample_rate='):
                    sample_rate = line.split('=')[1]
                    if sample_rate and sample_rate != 'N/A':
                        metadata["sample_rate"] = f"{int(sample_rate) // 1000}kHz"
    except Exception as e:
        logger.debug(f"فشل قراءة Metadata: {e}")
    return metadata


def format_duration(seconds: float) -> str:
    """تنسيق المدة إلى دقائق وثواني"""
    if seconds <= 0:
        return "0ث"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes > 0:
        return f"{minutes}د {secs}ث"
    return f"{secs}ث"


# ============================================================
# 📝 معالج البداية
# ============================================================

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أمر /start"""
    if await is_maintenance(update, context):
        return

    from keyboards import main_menu_keyboard

    user = update.effective_user
    if not user:
        return

    if not await check_subscription(user.id, context):
        await update.message.reply_text(
            "⚠️ أنت غير مشترك في القناة!\n\n"
            "يجب الاشتراك أولاً في القناة التالية:\n"
            f"👉 @BEXO50\n\n"
            "بعد الاشتراك، ارسل /start مرة أخرى."
        )
        return

    add_user(user.id, user.first_name)

    await update.message.reply_text(
        f"🚀 أهلاً بك {user.first_name} في بوت الخدمات الصوتية!\n\n"
        "اختر ما تريد فعله من الأزرار أدناه:",
        reply_markup=main_menu_keyboard()
    )


# ============================================================
# 📝 معالج الكولباك
# ============================================================

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أزرار الكولباك"""
    if not update.effective_user:
        return

    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    await query.answer()

    if data == "mysong_edit":
        context.user_data.clear()
        context.user_data.update({'mode': 'mysong_edit', 'step': 'waiting_for_audio'})
        await query.edit_message_text("🎵 تعديل أغنية موجودة\n\n📤 أرسل لي الآن الملف الصوتي.")

    elif data == "mysong_extract":
        context.user_data.clear()
        context.user_data.update({'mode': 'mysong_extract', 'step': 'waiting_for_video'})
        await query.edit_message_text("🎬 استخراج صوت من فيديو + إضافة صورة\n\n📤 أرسل لي الآن ملف الفيديو.")

    elif data == "mysong_new":
        context.user_data.clear()
        context.user_data.update({'mode': 'mysong_new', 'step': 'waiting_for_audio'})
        await query.edit_message_text("🆕 رفع ملف صوتي جديد + صورة\n\n📤 أرسل لي الآن الملف الصوتي.")

    elif data.startswith("q_"):
        parts = data.split("_")
        quality = parts[1] + "k"
        action = parts[2]
        context.user_data.update({'selected_quality': quality, 'action_type': action})
        msg = "🎵 أرسل الآن الملف الصوتي:" if action == "edit" else "🎬 أرسل الآن ملف الفيديو:"
        await query.edit_message_text(f"✅ تم اختيار جودة {quality}.\n\n{msg}")

    elif data == "cancel_action":
        context.user_data.clear()
        await query.edit_message_text("❌ تم إلغاء العملية.")

    elif data == "my_stats":
        with sqlite3.connect(DB_FILE) as conn:
            files_count = conn.execute("SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)).fetchone()[0]
        await query.edit_message_text(f"📊 إحصائياتك الشخصية\n\n✅ عدد الأغاني التي قمت بمعالجتها: {files_count}")


# ============================================================
# 🎵 معالج الملفات
# ============================================================

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الملفات الصوتية والفيديو"""
    if await is_maintenance(update, context):
        return

    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    mode = context.user_data.get('mode')
    step = context.user_data.get('step')

    temp_files: List[str] = []

    try:
        if mode and step:
            if step == 'waiting_for_audio' and mode in ('mysong_edit', 'mysong_new'):
                await _handle_audio_upload(update, context, user_id, temp_files)
            elif step == 'waiting_for_video' and mode == 'mysong_extract':
                await _handle_video_upload(update, context, user_id, temp_files)
            else:
                await update.message.reply_text("❌ الرجاء إرسال ملف مناسب.")
            return

        await _handle_normal_mode(update, context, user_id, temp_files)

    except Exception as e:
        logger.exception(f"خطأ في media_handler للمستخدم {user_id}: {e}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

    finally:
        keep_files = [context.user_data.get('audio_path'), context.user_data.get('file_path')]
        for file_path in temp_files:
            if file_path not in keep_files:
                safe_remove(file_path)


async def _handle_audio_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    user_id: int, temp_files: List[str]
) -> None:
    """معالجة رفع ملف صوتي (داخل وضع mysong)"""
    file_obj = None
    file_name = None
    mime_type = None

    if update.message.audio:
        file_obj = update.message.audio
        file_name = file_obj.file_name or "audio.mp3"
        mime_type = file_obj.mime_type or "audio/mpeg"
    elif update.message.document:
        doc = update.message.document
        file_name = doc.file_name or ""
        mime_type = doc.mime_type or ""
        if not is_audio_file(file_name, mime_type):
            await update.message.reply_text("❌ صيغة غير مدعومة.")
            return
        file_obj = doc

    if not file_obj:
        await update.message.reply_text("❌ من فضلك أرسل ملف صوتي.")
        return

    if file_obj.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("❌ حجم الملف كبير جداً.")
        return

    wait_msg = await update.message.reply_text("⏳ جاري تحميل الملف...")
    tg_file = await file_obj.get_file()

    unique_id = uuid.uuid4().hex[:12]
    ext = Path(file_name).suffix or '.mp3'
    original_path = get_unique_filename(f"original_{user_id}", ext)
    temp_files.append(original_path)

    await tg_file.download_to_drive(original_path)

    if not os.path.exists(original_path) or os.path.getsize(original_path) == 0:
        await wait_msg.edit_text("❌ فشل تحميل الملف.")
        return

    metadata = get_audio_metadata(original_path)
    info_text = (
        f"📁 {Path(file_name).name}\n"
        f"⏱️ {format_duration(metadata['duration'])}\n"
        f"📦 {metadata['size_mb']:.1f} MB"
    )
    await wait_msg.edit_text(info_text)

    audio_path = original_path
    if not original_path.lower().endswith('.mp3'):
        await wait_msg.edit_text("🔄 جاري التحويل إلى MP3...")
        mp3_path = get_unique_filename(f"converted_{user_id}")
        temp_files.append(mp3_path)
        if await FFmpegManager.convert_to_mp3(original_path, mp3_path):
            safe_remove(original_path)
            audio_path = mp3_path
        else:
            await wait_msg.edit_text("❌ فشل التحويل.")
            return

    if os.path.exists(audio_path) and os.path.getsize(audio_path) > TELEGRAM_AUDIO_LIMIT:
        await wait_msg.edit_text("⏳ جاري ضغط الملف...")
        compressed_path = get_unique_filename(f"compressed_{user_id}")
        temp_files.append(compressed_path)
        if await FFmpegManager.compress_audio(audio_path, compressed_path):
            safe_remove(audio_path)
            audio_path = compressed_path
            await wait_msg.edit_text("✅ تم ضغط الملف.")

    context.user_data['audio_path'] = audio_path
    context.user_data['step'] = 'waiting_for_title'
    await wait_msg.edit_text("📝 أرسل الآن اسم الأغنية:")


async def _handle_video_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    user_id: int, temp_files: List[str]
) -> None:
    """معالجة رفع فيديو (داخل وضع mysong)"""
    if not update.message.video:
        await update.message.reply_text("❌ من فضلك أرسل ملف فيديو.")
        return

    file_obj = update.message.video
    if file_obj.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("❌ حجم الملف كبير جداً.")
        return

    wait_msg = await update.message.reply_text("⏳ جاري تحميل الفيديو...")
    tg_file = await file_obj.get_file()

    unique_id = uuid.uuid4().hex[:12]
    video_path = get_unique_filename(f"video_{user_id}", '.mp4')
    temp_files.append(video_path)

    await tg_file.download_to_drive(video_path)

    audio_path = get_unique_filename(f"extracted_{user_id}")
    temp_files.append(audio_path)

    await wait_msg.edit_text("⏳ جاري استخراج الصوت...")

    cmd = FFmpegManager.build_extract_audio_cmd(video_path, audio_path)
    return_code, _, _ = await FFmpegManager.run(cmd)

    safe_remove(video_path)

    if return_code != 0:
        await wait_msg.edit_text("❌ حدث خطأ أثناء استخراج الصوت.")
        return

    if os.path.exists(audio_path) and os.path.getsize(audio_path) > TELEGRAM_AUDIO_LIMIT:
        await wait_msg.edit_text("⏳ جاري ضغط الصوت...")
        compressed_path = get_unique_filename(f"compressed_{user_id}")
        temp_files.append(compressed_path)
        if await FFmpegManager.compress_audio(audio_path, compressed_path):
            safe_remove(audio_path)
            audio_path = compressed_path

    context.user_data['audio_path'] = audio_path
    context.user_data['step'] = 'waiting_for_title'
    await wait_msg.edit_text("✅ تم استخراج الصوت.\n\n📝 أرسل الآن اسم الأغنية:")


async def _handle_normal_mode(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    user_id: int, temp_files: List[str]
) -> None:
    """معالجة الوضع العادي (تعديل أو استخراج)"""
    action_type = context.user_data.get('action_type')
    quality = context.user_data.get('selected_quality', '192k')

    if not action_type:
        return

    file_obj = None
    file_name = None

    if action_type == "edit":
        if update.message.audio:
            file_obj = update.message.audio
            file_name = file_obj.file_name or "audio.mp3"
        elif update.message.document:
            doc = update.message.document
            file_name = doc.file_name or ""
            mime_type = doc.mime_type or ""
            if is_audio_file(file_name, mime_type):
                file_obj = doc
        if not file_obj:
            await update.message.reply_text("❌ الرجاء إرسال ملف صوتي.")
            context.user_data.clear()
            return

    elif action_type == "extract":
        if update.message.video:
            file_obj = update.message.video
        else:
            await update.message.reply_text("❌ الرجاء إرسال ملف فيديو.")
            context.user_data.clear()
            return

    if file_obj.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("❌ حجم الملف كبير جداً.")
        context.user_data.clear()
        return

    wait_msg = await update.message.reply_text("⏳ جاري التحميل...")
    tg_file = await file_obj.get_file()

    unique_id = uuid.uuid4().hex[:12]
    ext = Path(file_name).suffix if file_name else '.mp3'
    input_path = get_unique_filename(f"input_{user_id}", ext)
    output_path = get_unique_filename(f"output_{user_id}")
    temp_files.extend([input_path, output_path])

    await tg_file.download_to_drive(input_path)

    if not input_path.lower().endswith('.mp3'):
        await wait_msg.edit_text("🔄 جاري التحويل إلى MP3...")
        converted_path = get_unique_filename(f"converted_{user_id}")
        temp_files.append(converted_path)
        if await FFmpegManager.convert_to_mp3(input_path, converted_path, quality):
            safe_remove(input_path)
            input_path = converted_path
        else:
            await wait_msg.edit_text("❌ فشل التحويل.")
            return

    if os.path.exists(input_path) and os.path.getsize(input_path) > TELEGRAM_AUDIO_LIMIT:
        await wait_msg.edit_text("⏳ جاري الضغط...")
        compressed_path = get_unique_filename(f"compressed_input_{user_id}")
        temp_files.append(compressed_path)
        if await FFmpegManager.compress_audio(input_path, compressed_path):
            safe_remove(input_path)
            input_path = compressed_path

    await wait_msg.edit_text("🎵 جاري معالجة الصوت...")
    cmd = FFmpegManager.build_convert_cmd(input_path, output_path, quality)
    return_code, _, _ = await FFmpegManager.run(cmd)

    safe_remove(input_path)

    if return_code != 0:
        await wait_msg.edit_text("❌ حدث خطأ أثناء المعالجة.")
        return

    if os.path.exists(output_path) and os.path.getsize(output_path) > TELEGRAM_AUDIO_LIMIT:
        await wait_msg.edit_text("⏳ جاري ضغط الملف النهائي...")
        final_path = get_unique_filename(f"final_compressed_{user_id}")
        temp_files.append(final_path)
        if await FFmpegManager.compress_audio(output_path, final_path):
            safe_remove(output_path)
            output_path = final_path

    context.user_data["file_path"] = output_path
    context.user_data["step"] = "title"
    await wait_msg.edit_text("📝 أرسل اسم الأغنية:")


# ============================================================
# 🖼️ معالج الصور
# ============================================================

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الصور (إضافة غلاف للأغنية)"""
    if await is_maintenance(update, context):
        return

    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    mode = context.user_data.get('mode')
    step = context.user_data.get('step')

    if not mode or step != 'waiting_for_cover':
        await update.message.reply_text("❌ لست في وضع إضافة صورة.")
        return

    temp_files: List[str] = []
    wait_msg = None

    try:
        wait_msg = await update.message.reply_text("🖼️ جاري معالجة الصورة...")

        unique_id = uuid.uuid4().hex[:12]
        cover_path = get_unique_filename(f"cover_{user_id}", '')
        audio_path = context.user_data.get('audio_path')

        if update.message.photo:
            photo = update.message.photo[-1]
            tg_photo = await photo.get_file()
            cover_path += ".jpg"
            temp_files.append(cover_path)
            await tg_photo.download_to_drive(cover_path)

        elif update.message.document:
            doc = update.message.document
            file_name = doc.file_name or ""
            mime_type = doc.mime_type or ""
            if not is_image_file(file_name, mime_type):
                await wait_msg.edit_text("❌ الملف المرسل ليس صورة.")
                return
            tg_doc = await doc.get_file()
            ext = Path(file_name).suffix or '.jpg'
            cover_path += ext
            temp_files.append(cover_path)
            await tg_doc.download_to_drive(cover_path)

        else:
            await wait_msg.edit_text("❌ لم ترسل صورة.")
            return

        if not audio_path or not os.path.exists(audio_path):
            await wait_msg.edit_text("❌ الملف الصوتي غير موجود.")
            return

        title = context.user_data.get('title', 'غير معروف')
        artist = context.user_data.get('artist', 'غير معروف')

        final_path = get_unique_filename(f"final_{user_id}")
        temp_files.append(final_path)

        await wait_msg.edit_text("🎵 جاري دمج الصورة مع الصوت...")

        cmd = FFmpegManager.build_merge_cover_cmd(
            audio_path, cover_path, final_path, title, artist
        )
        return_code, _, _ = await FFmpegManager.run(cmd)

        if return_code != 0:
            await wait_msg.edit_text("❌ حدث خطأ أثناء الدمج.")
            return

        if os.path.exists(final_path) and os.path.getsize(final_path) > TELEGRAM_AUDIO_LIMIT:
            await wait_msg.edit_text("⏳ جاري ضغط الملف النهائي...")
            compressed_path = get_unique_filename(f"compressed_final_{user_id}")
            temp_files.append(compressed_path)
            if await FFmpegManager.compress_audio(final_path, compressed_path):
                safe_remove(final_path)
                final_path = compressed_path

        with open(final_path, "rb") as f:
            await update.message.reply_audio(
                audio=f,
                title=title,
                performer=artist,
                caption="✅ تم إنشاء الأغنية بنجاح!"
            )

        add_file_record(user_id, title, artist)
        await wait_msg.delete()

    except Exception as e:
        logger.exception(f"خطأ في photo_handler للمستخدم {user_id}: {e}")
        if wait_msg:
            await wait_msg.edit_text(f"❌ حدث خطأ: {str(e)}")

    finally:
        safe_remove_many(temp_files)
        context.user_data.clear()


# ============================================================
# 📝 معالج النصوص
# ============================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج النصوص والأوامر النصية"""
    if not update.message or not update.message.text:
        return

    if not update.effective_user:
        return

    user_text = update.message.text
    user_id = update.effective_user.id

    try:
        # ===== الإذاعة =====
        if context.user_data.get('admin_step') == 'broadcasting':
            if user_id != OWNER_ID:
                context.user_data['admin_step'] = None
                return

            with sqlite3.connect(DB_FILE) as conn:
                users = conn.execute("SELECT user_id FROM users").fetchall()

            success = 0
            for u in users:
                try:
                    await context.bot.send_message(
                        chat_id=u[0],
                        text=f"📢 **إذاعة من المطور**\n\n{user_text}"
                    )
                    success += 1
                except:
                    pass

            context.user_data['admin_step'] = None
            await update.message.reply_text(f"✅ تمت الإذاعة لـ {success} مستخدم.")
            return

        # ===== أزرار القائمة =====
        if user_text == "▶️ تشغيل البوت":
            await start_handler(update, context)
            return

        if user_text == "🎵 تعديل الأغنية":
            from keyboards import quality_keyboard
            await update.message.reply_text(
                "🎵 تعديل أغنية\n\nاختر جودة الصوت:",
                reply_markup=quality_keyboard("edit")
            )
            return

        if user_text == "🎬 استخراج صوت من فيديو":
            from keyboards import quality_keyboard
            await update.message.reply_text(
                "🎬 استخراج صوت من فيديو\n\nاختر جودة الصوت:",
                reply_markup=quality_keyboard("extract")
            )
            return

        if user_text == "🖼️ إنشاء أغنية كاملة (اسم + صورة + صوت)":
            from keyboards import my_song_menu_keyboard
            await update.message.reply_text(
                "🖼️ إنشاء أغنية كاملة\n\nاختر ما تريد:",
                reply_markup=my_song_menu_keyboard()
            )
            return

        if user_text == "📊 إحصائياتي":
            with sqlite3.connect(DB_FILE) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
                ).fetchone()[0]
            await update.message.reply_text(
                f"📊 إحصائياتك الشخصية\n\n✅ عدد الأغاني المعالجة: {count}"
            )
            return

        if user_text == "🛠 لوحة التحكم":
            if user_id == OWNER_ID:
                from admin_panel import panel_handler
                await panel_handler(update, context)
            else:
                await update.message.reply_text("❌ هذه الخاصية متاحة للمطور فقط.")
            return

        # ===== وضع mysong - نصوص =====
        if context.user_data.get('mode'):
            await _handle_mysong_text(update, context)
            return

        # ===== إكمال التعديل =====
        if "file_path" in context.user_data:
            await _handle_edit_text(update, context)
            return

        # ===== رسالة افتراضية =====
        await update.message.reply_text(
            "❓ عذراً، لم أفهم طلبك.\nالرجاء استخدام الأزرار."
        )

    except Exception as e:
        logger.exception(f"خطأ في text_handler للمستخدم {user_id}: {e}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")


async def _handle_mysong_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة النصوص في وضع mysong"""
    step = context.user_data.get('step')
    user_text = update.message.text

    if step == 'waiting_for_title':
        if len(user_text) > 100:
            await update.message.reply_text("❌ اسم طويل جداً.")
            return
        context.user_data['title'] = user_text
        context.user_data['step'] = 'waiting_for_artist'
        await update.message.reply_text("🎤 أرسل اسم الفنان:")

    elif step == 'waiting_for_artist':
        if len(user_text) > 100:
            await update.message.reply_text("❌ اسم طويل جداً.")
            return
        context.user_data['artist'] = user_text
        context.user_data['step'] = 'waiting_for_cover'
        await update.message.reply_text("🖼️ أرسل الصورة:")

    elif step == 'waiting_for_cover':
        await update.message.reply_text("❌ أنا في انتظار صورة.")


async def _handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة النصوص في وضع التعديل العادي"""
    step = context.user_data.get("step")
    file_path = context.user_data["file_path"]
    user_id = update.effective_user.id
    user_text = update.message.text

    if step == "title":
        context.user_data["title"] = user_text
        context.user_data["step"] = "artist"
        await update.message.reply_text("🎤 أرسل اسم الفنان:")

    elif step == "artist":
        title = context.user_data["title"]
        artist = user_text
        unique_id = uuid.uuid4().hex[:12]
        temp_files: List[str] = []

        try:
            final_path = get_unique_filename(f"final_{user_id}")
            temp_files.append(final_path)

            cover = await get_channel_cover(context)

            if cover and os.path.exists(cover):
                cmd = FFmpegManager.build_merge_cover_cmd(
                    file_path, cover, final_path, title, artist
                )
            else:
                cmd = FFmpegManager.build_convert_cmd(
                    file_path, final_path, "192k"
                )
                # إضافة Metadata
                cmd.extend([
                    "-metadata", f"title={title}",
                    "-metadata", f"artist={artist}"
                ])

            await update.message.reply_text("🎵 جاري معالجة الملف...")

            return_code, _, _ = await FFmpegManager.run(cmd)

            if return_code != 0:
                await update.message.reply_text("❌ حدث خطأ.")
                return

            if os.path.exists(final_path) and os.path.getsize(final_path) > TELEGRAM_AUDIO_LIMIT:
                await update.message.reply_text("⏳ جاري الضغط...")
                compressed_path = get_unique_filename(f"compressed_final_{user_id}")
                temp_files.append(compressed_path)
                if await FFmpegManager.compress_audio(final_path, compressed_path):
                    safe_remove(final_path)
                    final_path = compressed_path

            with open(final_path, "rb") as f:
                await update.message.reply_audio(
                    audio=f,
                    title=title,
                    performer=artist,
                    caption="✅ تم تعديل الأغنية بنجاح!"
                )

            with sqlite3.connect(DB_FILE) as conn:
                conn.execute(
                    "INSERT INTO files (user_id, title, artist, date) VALUES (?, ?, ?, ?)",
                    (user_id, title, artist, datetime.now().strftime("%Y-%m-%d %H:%M"))
                )

        except Exception as e:
            logger.exception(f"خطأ في _handle_edit_text: {e}")
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

        finally:
            safe_remove_many(temp_files)
            safe_remove(file_path)
            context.user_data.clear()
