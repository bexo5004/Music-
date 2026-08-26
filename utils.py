import os
import sqlite3
import logging
import asyncio
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from telegram.ext import ContextTypes

# ============================================================
# 📋 إعدادات اللوغينغ
# ============================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# ⚙️ الإعدادات الأساسية
# ============================================================
DB_FILE = "bot_stats.db"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
DEFAULT_AUDIO_QUALITY = "192k"
COVER_CACHE = "channel_cover_cached.jpg"
CHANNEL_USERNAME = "BEXO50"
OWNER_ID = 8798182716
MAINTENANCE_MODE = False
TEMP_DIR = os.path.join(os.getcwd(), "temp_files")
os.makedirs(TEMP_DIR, exist_ok=True)


# ============================================================
# 📊 مدير قاعدة البيانات
# ============================================================
class DatabaseManager:
    """مدير قاعدة البيانات"""
    
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """تهيئة قاعدة البيانات"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # جدول المستخدمين
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        first_name TEXT,
                        join_date TEXT,
                        last_active TEXT
                    )
                ''')
                
                # جدول الملفات
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        title TEXT,
                        artist TEXT,
                        file_size INTEGER DEFAULT 0,
                        duration INTEGER DEFAULT 0,
                        quality TEXT DEFAULT '192k',
                        date TEXT,
                        status TEXT DEFAULT 'success'
                    )
                ''')
                
                # جدول الإحصائيات
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
                
                # إضافة فهارس
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_date ON files(date)')
                
                conn.commit()
                logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")
                
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
    
    def execute_query(self, query: str, params: tuple = ()) -> List[tuple]:
        """تنفيذ استعلام والعودة بالنتائج"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"❌ خطأ في الاستعلام: {e}")
            return []
    
    def execute_update(self, query: str, params: tuple = ()) -> bool:
        """تنفيذ تحديث في قاعدة البيانات"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ خطأ في التحديث: {e}")
            return False


# ============================================================
# 📂 مدير الملفات
# ============================================================
class FileManager:
    """مدير الملفات المؤقتة"""
    
    def __init__(self):
        self.temp_dir = TEMP_DIR
    
    async def download_file(self, file_obj, prefix: str = "") -> Optional[str]:
        """تحميل ملف من تيليجرام"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            safe_name = f"{prefix}_{timestamp}_{file_obj.file_id[:8]}"
            
            ext = self._get_extension(file_obj)
            file_path = os.path.join(self.temp_dir, f"{safe_name}{ext}")
            
            logger.info(f"بدء تحميل الملف إلى: {file_path}")
            
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
        """تحديد امتداد الملف"""
        if hasattr(file_obj, 'file_name') and file_obj.file_name:
            ext = os.path.splitext(file_obj.file_name)[1]
            if ext:
                return ext
        
        if hasattr(file_obj, 'mime_type') and file_obj.mime_type:
            mime = file_obj.mime_type
            if 'video' in mime:
                return '.mp4'
            elif 'audio' in mime:
                return '.mp3'
            elif 'image' in mime:
                return '.jpg'
        
        if hasattr(file_obj, 'duration'):
            return '.mp4'
        
        return '.bin'
    
    def cleanup(self, max_age_seconds: int = 3600):
        """تنظيف الملفات القديمة"""
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
        """حذف جميع الملفات المؤقتة"""
        try:
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)
            logger.info("تم تنظيف جميع الملفات المؤقتة")
        except Exception as e:
            logger.error(f"خطأ في تنظيف الملفات: {e}")


# ============================================================
# 🔧 إنشاء المديرين
# ============================================================
db_manager = DatabaseManager()  # ✅ هذا هو المطلوب
file_manager = FileManager()


# ============================================================
# 🎬 دوال التحقق
# ============================================================

async def is_maintenance(update, context):
    """التحقق من وضع الصيانة"""
    if MAINTENANCE_MODE:
        if update.effective_user.id == OWNER_ID:
            return False
        
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ عذراً، البوت في وضع الصيانة حالياً!\n\n"
                "نحن نقوم ببعض التحديثات، سنعود للعمل قريباً."
            )
        return True
    return False


async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من الاشتراك في القناة"""
    for attempt in range(3):
        try:
            member = await context.bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
            return member.status not in ["left", "kicked"]
        except Exception as e:
            logger.warning(f"محاولة {attempt+1} فشلت: {e}")
            await asyncio.sleep(1)
    return True


async def auto_clear_cache():
    """تنظيف الملفات المؤقتة بشكل دوري"""
    file_manager.cleanup()


async def get_channel_cover(context: ContextTypes.DEFAULT_TYPE):
    """جلب صورة القناة"""
    try:
        if os.path.exists(COVER_CACHE):
            if os.path.getsize(COVER_CACHE) > 0:
                file_age = datetime.now().timestamp() - os.path.getmtime(COVER_CACHE)
                if file_age < 86400:
                    return COVER_CACHE
                else:
                    os.remove(COVER_CACHE)
                    logger.info("تم حذف كاش صورة القناة القديم")
        
        chat = await context.bot.get_chat(f"@{CHANNEL_USERNAME}")
        if chat.photo:
            photo_file = await context.bot.get_file(chat.photo.big_file_id)
            await photo_file.download_to_drive(COVER_CACHE)
            
            if os.path.exists(COVER_CACHE) and os.path.getsize(COVER_CACHE) > 0:
                logger.info("تم تحديث صورة القناة")
                return COVER_CACHE
        return None
            
    except Exception as e:
        logger.error(f"خطأ جلب صورة القناة: {e}")
        if os.path.exists(COVER_CACHE) and os.path.getsize(COVER_CACHE) > 0:
            return COVER_CACHE
        return None


# ============================================================
# 📝 دوال قاعدة البيانات
# ============================================================

def add_user(user_id, first_name):
    """إضافة مستخدم جديد"""
    try:
        db_manager.execute_update(
            "INSERT OR IGNORE INTO users (user_id, first_name, join_date) VALUES (?, ?, ?)",
            (user_id, first_name, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        logger.info(f"تم تسجيل المستخدم {user_id}")
    except Exception as e:
        logger.error(f"خطأ في إضافة المستخدم: {e}")


def add_file_record(user_id, title, artist):
    """تسجيل عملية ناجحة"""
    try:
        db_manager.execute_update(
            "INSERT INTO files (user_id, title, artist, date) VALUES (?, ?, ?, ?)",
            (user_id, title, artist, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        logger.info(f"تم تسجيل ملف جديد: {title} - {artist}")
        return True
    except Exception as e:
        logger.error(f"خطأ في تسجيل الملف: {e}")
        return False


def get_user_stats(user_id):
    """الحصول على إحصائيات المستخدم"""
    try:
        files_count = db_manager.execute_query(
            "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
        )
        last_activity = db_manager.execute_query(
            "SELECT MAX(date) FROM files WHERE user_id = ?", (user_id,)
        )
        return {
            "files_count": files_count[0][0] if files_count else 0,
            "last_activity": last_activity[0][0] if last_activity and last_activity[0][0] else "لا يوجد"
        }
    except Exception as e:
        logger.error(f"خطأ في جلب إحصائيات المستخدم: {e}")
        return {"files_count": 0, "last_activity": "خطأ"}


def get_total_stats():
    """الحصول على إحصائيات البوت الكلية"""
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
