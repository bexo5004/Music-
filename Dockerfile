FROM python:3.11-slim

# تثبيت ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# نسخ الملفات
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# تشغيل البوت
CMD ["python", "main.py"]
