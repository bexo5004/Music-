FROM python:3.11-slim

WORKDIR /app

# تثبيت FFmpeg مع الحزم المتوفرة فقط
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

# التحقق من تثبيت FFmpeg
RUN ffmpeg -version

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
