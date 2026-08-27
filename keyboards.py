from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


# ============================================================
# ألوان أزرار Telegram الجديدة
# ============================================================

PRIMARY = "primary"   # 🔵 أزرق
SUCCESS = "success"   # 🟢 أخضر
DANGER = "danger"     # 🔴 أحمر


# ============================================================
# القائمة الرئيسية
# ============================================================

def main_menu_keyboard():
    keyboard = [
        [
            KeyboardButton(
                "▶️ تشغيل البوت",
                style=SUCCESS,
            )
        ],

        [
            KeyboardButton(
                "🎵 تعديل الأغنية",
                style=PRIMARY,
            ),
            KeyboardButton(
                "🎬 استخراج صوت من فيديو",
                style=PRIMARY,
            ),
        ],

        [
            KeyboardButton(
                "🖼️ إنشاء أغنية كاملة (اسم + صورة + صوت)",
                style=PRIMARY,
            )
        ],

        [
            KeyboardButton(
                "📊 إحصائياتي",
                style=PRIMARY,
            ),
            KeyboardButton(
                "🛠 لوحة التحكم",
                style=PRIMARY,
            ),
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


# ============================================================
# قائمة أغنيتي
# ============================================================

def my_song_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "📝 تعديل اسم وصورة أغنية",
                callback_data="mysong_edit",
                style=PRIMARY,
            )
        ],

        [
            InlineKeyboardButton(
                "🎬 استخراج صوت من فيديو + إضافة صورة",
                callback_data="mysong_extract",
                style=PRIMARY,
            )
        ],

        [
            InlineKeyboardButton(
                "🆕 رفع ملف صوتي جديد + صورة",
                callback_data="mysong_new",
                style=SUCCESS,
            )
        ],

        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="cancel_action",
                style=DANGER,
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# اختيار جودة الصوت
# ============================================================

def quality_keyboard(action_type):
    keyboard = [
        [
            InlineKeyboardButton(
                "🎵 128kbps",
                callback_data=f"q_128_{action_type}",
                style=PRIMARY,
            ),
            InlineKeyboardButton(
                "🎵 192kbps",
                callback_data=f"q_192_{action_type}",
                style=PRIMARY,
            ),
        ],

        [
            InlineKeyboardButton(
                "🎵 256kbps",
                callback_data=f"q_256_{action_type}",
                style=PRIMARY,
            ),
            InlineKeyboardButton(
                "🎵 320kbps",
                callback_data=f"q_320_{action_type}",
                style=SUCCESS,
            ),
        ],

        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data="cancel_action",
                style=DANGER,
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# لوحة التحكم
# ============================================================

def admin_panel_keyboard(maintenance_status):
    if maintenance_status:
        m_text = "🔴 إيقاف الصيانة"
        m_style = DANGER
    else:
        m_text = "🟢 تفعيل الصيانة"
        m_style = SUCCESS

    keyboard = [
        [
            InlineKeyboardButton(
                "📊 إحصائيات البوت",
                callback_data="admin_stats",
                style=PRIMARY,
            )
        ],

        [
            InlineKeyboardButton(
                m_text,
                callback_data="toggle_maintenance",
                style=m_style,
            )
        ],

        [
            InlineKeyboardButton(
                "📢 إذاعة (Broadcast)",
                callback_data="admin_broadcast",
                style=PRIMARY,
            )
        ],

        [
            InlineKeyboardButton(
                "🗑 تنظيف الملفات المؤقتة",
                callback_data="admin_clean",
                style=DANGER,
            )
        ],

        [
            InlineKeyboardButton(
                "⚡ تحسين قاعدة البيانات",
                callback_data="admin_optimize",
                style=SUCCESS,
            )
        ],

        [
            InlineKeyboardButton(
                "❌ إغلاق اللوحة",
                callback_data="close_admin",
                style=DANGER,
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# زر إلغاء العملية
# ============================================================

def cancel_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "❌ إلغاء العملية",
                callback_data="cancel_action",
                style=DANGER,
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)
