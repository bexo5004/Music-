import os
import sqlite3
import logging
import asyncio
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from functools import lru_cache
from cachetools import TTLCache
from telegram.ext import ContextTypes
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "bot_stats.db"
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 100 * 1024 * 1024))
DEFAULT_AUDIO_QUALITY = os.getenv("DEFAULT_QUALITY", "192k")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "BEXO50")
OWNER_ID = int(os.getenv("OWNER_ID", 8798182716))

TEMP_DIR = os.path.join(os.getcwd(), "temp_files")
os.makedirs(TEMP_DIR, exist_ok=True)

MAINTENANCE_MODE = False

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    'audio': ['.mp3', '.m4a', '.aac', '.wav', '.ogg', '.flac'],
    'video': ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.3gp', '.m4v', '.mpg', '.mpeg'],
    'image': ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff']
}

cache = TTLCache(maxsize=1000, ttl=300)


class DatabaseManager:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        first_name TEXT,
                        join_date TEXT,
                        last_active TEXT
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        title TEXT,
                        artist TEXT,
                        file_size INTEGER,
                        duration INTEGER,
                        quality TEXT,
                        date TEXT,
                        status TEXT DEFAULT 'success'
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT,
                        total_audio INTEGER DEFAULT 0,
                        total_video INTEGER DEFAULT 0,
                        total_users INTEGER DEFAULT 0,
                        total_errors INTEGER DEFAULT 0
                    )
                ''')
                
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_date ON files(date)')
                
                conn.commit()
                logger.info("تم تهيئة قاعدة البيانات بنجاح")
                
        except Exception as e:
            logger.error(f"خطأ في تهيئة قاعدة البيانات: {e}")
    
    def execute_query(self, query: str, params: tuple = ()) -> List[tuple]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"خطأ في الاستعلام: {e}")
            return []
    
    def execute_update(self, query: str, params: tuple = ()) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"خطأ في التحديث: {e}")
            return False


class FileValidator:
    @staticmethod
    def validate_audio_file(file_path: str) -> Tuple[bool, str]:
        try:
            if not os.path.exists(file_path):
                return False, "الملف غير موجود"
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return False, "الملف فارغ"
            if file_size > MAX_FILE_SIZE:
                return False, f"حجم الملف كبير جداً (الحد: {MAX_FILE_SIZE // (1024*1024)}MB)"
            
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in ALLOWED_TYPES['audio']:
                return False, f"نوع الملف غير مدعوم: {file_ext}"
            
            # استخدام FFmpeg للتحقق
            try:
                cmd = [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and result.stdout.strip():
                    duration = float(result.stdout.strip())
                    if duration < 1:
                        return False, "مدة الملف قصيرة جداً"
                    if duration > 3600:
                        return False, "مدة الملف طويلة جداً (أكثر من ساعة)"
                    return True, f"ملف صالح - المدة: {int(duration)} ثانية"
                return False, "الملف تالف"
            except:
                return True, "ملف صالح (تحقق محدود)"
                    
        except Exception as e:
            logger.error(f"خطأ في التحقق من الملف: {e}")
            return False, f"حدث خطأ: {str(e)}"
    
    @staticmethod
    def validate_video_file(file_path: str) -> Tuple[bool, str]:
        try:
            if not os.path.exists(file_path):
                return False, "الملف غير موجود"
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return False, "الملف فارغ"
            if file_size > MAX_FILE_SIZE:
                return False, f"حجم الملف كبير جداً (الحد: {MAX_FILE_SIZE // (1024*1024)}MB)"
            
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in ALLOWED_TYPES['video']:
                return False, f"نوع الملف غير مدعوم: {file_ext}"
            
            # استخدام FFmpeg للتحقق
            try:
                cmd = [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                has_audio = "audio" in result.stdout
                
                if not has_audio:
                    return False, "الفيديو لا يحتوي على صوت"
                
                cmd_duration = [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ]
                result_duration = subprocess.run(cmd_duration, capture_output=True, text=True, timeout=10)
                
                if result_duration.returncode == 0 and result_duration.stdout.strip():
                    duration = float(result_duration.stdout.strip())
                    if duration > 0:
                        return True, f"فيديو صالح - المدة: {int(duration)} ثانية"
                
                return True, "فيديو صالح"
                
            except subprocess.TimeoutExpired:
                return True, "فيديو صالح (تعذر التحقق)"
            except Exception as e:
                logger.warning(f"خطأ في ffprobe: {e}")
                return True, "فيديو صالح (تحقق محدود)"
                
        except Exception as e:
            logger.error(f"خطأ في التحقق من الفيديو: {e}")
            return False, f"حدث خطأ: {str(e)}"
    
    @staticmethod
    def validate_image_file(file_path: str) -> Tuple[bool, str]:
        try:
            if not os.path.exists(file_path):
                return False, "الملف غير موجود"
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return False, "الملف فارغ"
            
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in ALLOWED_TYPES['image']:
                return False, f"نوع الصورة غير مدعوم: {file_ext}"
            
            try:
                from PIL import Image
                img = Image.open(file_path)
                width, height = img.size
                if width < 50 or height < 50:
                    return False, "الصورة صغيرة جداً"
                return True, f"صورة صالحة - الأبعاد: {width}x{height}"
            except:
                return False, "الصورة تالفة"
                
        except Exception as e:
            logger.error(f"خطأ في التحقق من الصورة: {e}")
            return False, f"حدث خطأ: {str(e)}"


class AudioProcessor:
    def __init__(self):
        self.temp_dir = TEMP_DIR
    
    async def _run_ffmpeg(self, cmd: list) -> Tuple[int, str, str]:
        """تشغيل أمر FFmpeg وإرجاع النتيجة"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return process.returncode, stdout.decode(), stderr.decode()
        except Exception as e:
            return -1, "", str(e)
    
    async def process_audio(self, input_path: str, quality: str = "192k") -> Optional[str]:
        try:
            is_valid, _ = FileValidator.validate_audio_file(input_path)
            if not is_valid:
                return None
            
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            output_path = os.path.join(self.temp_dir, f"output_{timestamp}.mp3")
            
            # أمر FFmpeg محسن
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-ac", "2",
                "-b:a", quality,
                "-ar", "44100",
                "-f", "mp3",
                "-y",
                output_path
            ]
            
            logger.info(f"تشغيل FFmpeg: {' '.join(cmd)}")
            
            returncode, stdout, stderr = await self._run_ffmpeg(cmd)
            
            if returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"تمت معالجة الصوت بنجاح: {output_path}")
                return output_path
            
            logger.error(f"خطأ في FFmpeg: {stderr}")
            return None
            
        except Exception as e:
            logger.error(f"خطأ في معالجة الصوت: {e}")
            return None
    
    async def extract_audio_from_video(self, video_path: str, quality: str = "192k") -> Optional[str]:
        try:
            if not os.path.exists(video_path):
                logger.error("الملف غير موجود")
                return None
            
            file_size = os.path.getsize(video_path)
            if file_size == 0:
                logger.error("الملف فارغ")
                return None
            
            logger.info(f"بدء استخراج الصوت من: {video_path} - الحجم: {file_size} بايت")
            
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            output_path = os.path.join(self.temp_dir, f"extracted_{timestamp}.mp3")
            
            # ===== المحاولة 1: جودة عالية =====
            cmd1 = [
                "ffmpeg",
                "-i", video_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-ac", "2",
                "-b:a", quality,
                "-ar", "44100",
                "-f", "mp3",
                "-y",
                output_path
            ]
            
            logger.info(f"المحاولة 1: {' '.join(cmd1)}")
            
            returncode1, stdout1, stderr1 = await self._run_ffmpeg(cmd1)
            
            if returncode1 == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"تم استخراج الصوت بنجاح (جودة عالية): {output_path}")
                return output_path
            
            logger.warning(f"المحاولة 1 فشلت: {stderr1}")
            
            # ===== المحاولة 2: إعادة ترميز الفيديو أولاً =====
            temp_video = os.path.join(self.temp_dir, f"temp_video_{timestamp}.mp4")
            
            cmd_reencode = [
                "ffmpeg",
                "-i", video_path,
                "-c:v", "libx264",
                "-c:a", "aac",
                "-strict", "experimental",
                "-y",
                temp_video
            ]
            
            logger.info(f"إعادة ترميز الفيديو: {' '.join(cmd_reencode)}")
            
            returncode_re, stdout_re, stderr_re = await self._run_ffmpeg(cmd_reencode)
            
            if returncode_re == 0 and os.path.exists(temp_video) and os.path.getsize(temp_video) > 0:
                # استخراج الصوت من الفيديو المعاد ترميزه
                cmd2 = [
                    "ffmpeg",
                    "-i", temp_video,
                    "-vn",
                    "-acodec", "libmp3lame",
                    "-ac", "2",
                    "-b:a", quality,
                    "-ar", "44100",
                    "-f", "mp3",
                    "-y",
                    output_path
                ]
                
                logger.info(f"المحاولة 2: {' '.join(cmd2)}")
                
                returncode2, stdout2, stderr2 = await self._run_ffmpeg(cmd2)
                
                # تنظيف الفيديو المؤقت
                if os.path.exists(temp_video):
                    os.remove(temp_video)
                
                if returncode2 == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info(f"تم استخراج الصوت بنجاح (بعد إعادة الترميز): {output_path}")
                    return output_path
                
                logger.warning(f"المحاولة 2 فشلت: {stderr2}")
            
            # ===== المحاولة 3: جودة منخفضة =====
            cmd3 = [
                "ffmpeg",
                "-i", video_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-ac", "1",
                "-b:a", "64k",
                "-ar", "22050",
                "-f", "mp3",
                "-y",
                output_path
            ]
            
            logger.info(f"المحاولة 3: {' '.join(cmd3)}")
            
            returncode3, stdout3, stderr3 = await self._run_ffmpeg(cmd3)
            
            if returncode3 == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"تم استخراج الصوت بنجاح (جودة منخفضة): {output_path}")
                return output_path
            
            logger.warning(f"المحاولة 3 فشلت: {stderr3}")
            
            # ===== المحاولة 4: استخدام libav بدلاً من libmp3lame =====
            cmd4 = [
                "ffmpeg",
                "-i", video_path,
                "-vn",
                "-acodec", "libavcodec",
                "-ac", "2",
                "-b:a", "128k",
                "-ar", "44100",
                "-f", "mp3",
                "-y",
                output_path
            ]
            
            logger.info(f"المحاولة 4: {' '.join(cmd4)}")
            
            returncode4, stdout4, stderr4 = await self._run_ffmpeg(cmd4)
            
            if returncode4 == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"تم استخراج الصوت بنجاح (باستخدام libav): {output_path}")
                return output_path
            
            logger.warning(f"المحاولة 4 فشلت: {stderr4}")
            
            # ===== المحاولة 5: استخراج الصوت الخام =====
            raw_audio = os.path.join(self.temp_dir, f"raw_audio_{timestamp}.pcm")
            
            cmd5 = [
                "ffmpeg",
                "-i", video_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ac", "2",
                "-ar", "44100",
                "-f", "s16le",
                "-y",
                raw_audio
            ]
            
            logger.info(f"المحاولة 5: {' '.join(cmd5)}")
            
            returncode5, stdout5, stderr5 = await self._run_ffmpeg(cmd5)
            
            if returncode5 == 0 and os.path.exists(raw_audio) and os.path.getsize(raw_audio) > 0:
                # تحويل الصوت الخام إلى MP3
                cmd6 = [
                    "ffmpeg",
                    "-f", "s16le",
                    "-ar", "44100",
                    "-ac", "2",
                    "-i", raw_audio,
                    "-acodec", "libmp3lame",
                    "-b:a", quality,
                    "-y",
                    output_path
                ]
                
                logger.info(f"تحويل الصوت الخام: {' '.join(cmd6)}")
                
                returncode6, stdout6, stderr6 = await self._run_ffmpeg(cmd6)
                
                # تنظيف الصوت الخام
                if os.path.exists(raw_audio):
                    os.remove(raw_audio)
                
                if returncode6 == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info(f"تم استخراج الصوت بنجاح (من الصوت الخام): {output_path}")
                    return output_path
            
            # ===== فشل كل المحاولات =====
            logger.error("فشل استخراج الصوت من الفيديو بجميع المحاولات")
            
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass
            
            return None
            
        except Exception as e:
            logger.error(f"خطأ في استخراج الصوت: {e}")
            return None
    
    def add_metadata(self, audio_path: str, title: str, artist: str, cover_path: str = None) -> bool:
        try:
            from mutagen.id3 import ID3, TIT2, TPE1, APIC, TALB, TDRC, TCON
            
            try:
                audio = ID3(audio_path)
            except:
                audio = ID3()
            
            audio["TIT2"] = TIT2(encoding=3, text=title[:100])
            audio["TPE1"] = TPE1(encoding=3, text=artist[:100])
            audio["TALB"] = TALB(encoding=3, text=f"@{CHANNEL_USERNAME}")
            audio["TDRC"] = TDRC(encoding=3, text=str(datetime.now().year))
            audio["TCON"] = TCON(encoding=3, text="Various")
            
            if cover_path and os.path.exists(cover_path):
                try:
                    with open(cover_path, "rb") as img:
                        if "APIC" in audio:
                            del audio["APIC"]
                        audio["APIC"] = APIC(
                            encoding=3,
                            mime="image/jpeg",
                            type=3,
                            desc="Cover",
                            data=img.read()
                        )
                except Exception as e:
                    logger.warning(f"فشل إضافة الصورة: {e}")
            
            audio.save(audio_path, v2_version=3)
            return True
            
        except Exception as e:
            logger.error(f"خطأ في إضافة البيانات: {e}")
            return False


class FileManager:
    def __init__(self):
        self.temp_dir = TEMP_DIR
        self.processor = AudioProcessor()
    
    async def download_file(self, file_obj, prefix: str = "") -> Optional[str]:
        try:
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            safe_name = f"{prefix}_{timestamp}_{file_obj.file_id[:8]}"
            
            ext = self._get_extension(file_obj)
            file_path = os.path.join(self.temp_dir, f"{safe_name}{ext}")
            
            tg_file = await file_obj.get_file()
            await tg_file.download_to_drive(file_path)
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"تم تحميل الملف: {os.path.basename(file_path)} - الحجم: {os.path.getsize(file_path)} بايت")
                return file_path
            
            logger.error(f"فشل تحميل الملف: {file_path}")
            return None
            
        except Exception as e:
            logger.error(f"خطأ في تحميل الملف: {e}")
            return None
    
    def _get_extension(self, file_obj) -> str:
        if hasattr(file_obj, 'file_name') and file_obj.file_name:
            ext = os.path.splitext(file_obj.file_name)[1]
            if ext:
                return ext
        
        if hasattr(file_obj, 'mime_type') and file_obj.mime_type:
            mime = file_obj.mime_type
            if 'video/mp4' in mime:
                return '.mp4'
            elif 'video/quicktime' in mime:
                return '.mov'
            elif 'video/x-msvideo' in mime:
                return '.avi'
            elif 'video/x-matroska' in mime:
                return '.mkv'
            elif 'video/webm' in mime:
                return '.webm'
            elif 'video/flv' in mime:
                return '.flv'
            elif 'audio/mpeg' in mime or 'audio/mp3' in mime:
                return '.mp3'
            elif 'audio/m4a' in mime:
                return '.m4a'
            elif 'image/jpeg' in mime:
                return '.jpg'
            elif 'image/png' in mime:
                return '.png'
        
        if hasattr(file_obj, 'duration') and hasattr(file_obj, 'width') and hasattr(file_obj, 'height'):
            return '.mp4'
        
        if hasattr(file_obj, 'duration') and hasattr(file_obj, 'performer'):
            return '.mp3'
        
        return '.bin'
    
    def cleanup(self, max_age_seconds: int = 3600):
        try:
            current_time = datetime.now().timestamp()
            deleted = 0
            
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    if current_time - os.path.getmtime(file_path) > max_age_seconds:
                        os.remove(file_path)
                        deleted += 1
            
            if deleted > 0:
                logger.info(f"تم حذف {deleted} ملف مؤقت")
                
        except Exception as e:
            logger.error(f"خطأ في تنظيف الملفات: {e}")
    
    def cleanup_all(self):
        try:
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)
            logger.info("تم تنظيف جميع الملفات المؤقتة")
        except Exception as e:
            logger.error(f"خطأ في تنظيف الملفات: {e}")


file_manager = FileManager()
db_manager = DatabaseManager()


async def is_maintenance(update, context) -> bool:
    if MAINTENANCE_MODE and update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "عذراً، البوت في وضع الصيانة حالياً!\n\nنحن نقوم بتحسين الخدمة، سنعود للعمل قريباً."
        )
        return True
    return False


async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    for attempt in range(3):
        try:
            member = await context.bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
            is_subscribed = member.status not in ["left", "kicked"]
            if is_subscribed:
                cache[f"sub_{user_id}"] = True
                return True
            else:
                cache[f"sub_{user_id}"] = False
                return False
        except Exception as e:
            logger.warning(f"محاولة {attempt+1} فشلت: {e}")
            await asyncio.sleep(1)
    
    return cache.get(f"sub_{user_id}", False)


@lru_cache(maxsize=128)
def get_channel_cover() -> Optional[str]:
    try:
        cover_path = os.path.join(TEMP_DIR, "channel_cover.jpg")
        if os.path.exists(cover_path):
            file_age = datetime.now().timestamp() - os.path.getmtime(cover_path)
            if file_age < 86400 and os.path.getsize(cover_path) > 0:
                return cover_path
        return None
    except Exception as e:
        logger.error(f"خطأ في جلب صورة القناة: {e}")
        return None


def add_user(user_id: int, first_name: str):
    try:
        db_manager.execute_update(
            "INSERT OR REPLACE INTO users (user_id, first_name, join_date, last_active) VALUES (?, ?, ?, ?)",
            (user_id, first_name, datetime.now().strftime("%Y-%m-%d %H:%M"), 
             datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        logger.info(f"تم تسجيل المستخدم {user_id}")
    except Exception as e:
        logger.error(f"خطأ في إضافة المستخدم: {e}")


def add_file_record(user_id: int, title: str, artist: str, file_path: str = None, status: str = "success"):
    try:
        file_size = 0
        duration = 0
        if file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            try:
                cmd = [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and result.stdout.strip():
                    duration = int(float(result.stdout.strip()))
            except:
                pass
        
        db_manager.execute_update(
            "INSERT INTO files (user_id, title, artist, file_size, duration, quality, date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, title, artist, file_size, duration, DEFAULT_AUDIO_QUALITY, 
             datetime.now().strftime("%Y-%m-%d %H:%M"), status)
        )
        logger.info(f"تم تسجيل ملف جديد: {title} - {artist}")
        return True
    except Exception as e:
        logger.error(f"خطأ في تسجيل الملف: {e}")
        return False


async def auto_clear_cache():
    file_manager.cleanup()


def get_user_stats(user_id: int) -> Dict:
    try:
        files_count = db_manager.execute_query("SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,))
        last_activity = db_manager.execute_query("SELECT MAX(date) FROM files WHERE user_id = ?", (user_id,))
        return {
            "files_count": files_count[0][0] if files_count else 0,
            "last_activity": last_activity[0][0] if last_activity and last_activity[0][0] else "لا يوجد"
        }
    except Exception as e:
        logger.error(f"خطأ في جلب إحصائيات المستخدم: {e}")
        return {"files_count": 0, "last_activity": "خطأ"}


def get_total_stats() -> Dict:
    try:
        total_users = db_manager.execute_query("SELECT COUNT(*) FROM users")
        total_files = db_manager.execute_query("SELECT COUNT(*) FROM files")
        today = datetime.now().strftime("%Y-%m-%d")
        active_today = db_manager.execute_query(
            "SELECT COUNT(DISTINCT user_id) FROM files WHERE date LIKE ?", (f"{today}%",)
        )
        return {
            "total_users": total_users[0][0] if total_users else 0,
            "total_files": total_files[0][0] if total_files else 0,
            "active_today": active_today[0][0] if active_today else 0
        }
    except Exception as e:
        logger.error(f"خطأ في جلب الإحصائيات الكلية: {e}")
        return {"total_users": 0, "total_files": 0, "active_today": 0}
