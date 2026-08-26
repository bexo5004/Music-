FROM python:3.11-slim

WORKDIR /app

# تثبيت FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملفات المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY . .

# تشغيل البوت
CMD ["python", "main.py"]
