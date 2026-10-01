# Work Bot (@DiV_executive_bot) — Telegram-бот: документы/фото/голос + база ВЭД
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Tesseract с рус/англ языками + poppler (PDF→картинки для OCR) +
# ffmpeg (ogg/opus ↔ wav для голосового канала) + unzip (распаковка Vosk-модели)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng poppler-utils \
       ffmpeg unzip curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch: без него sentence-transformers тянет CUDA-колёса nvidia-* (~3 ГБ)
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Модули агентов лежат внутри образа (на сервере путей Mac нет)
ENV DOC_AGENT_PATH=/app/doc_agent \
    VISION_AGENT_PATH=/app/vision_agent

# ── Локальный голос: модель Vosk (STT, ~45 МБ) + предварительная загрузка Silero в кеш torch (TTS) ──
RUN curl -sL https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip -o /tmp/vosk.zip \
    && unzip -q /tmp/vosk.zip -d /app/models \
    && mv /app/models/vosk-model-small-ru-0.22 /app/models/vosk-small-ru \
    && rm /tmp/vosk.zip
RUN python -c "import torch; torch.hub.load('snakers4/silero-models', 'silero_tts', language='ru', speaker='v5_ru', trust_repo=True)" \
    || python -c "import torch; torch.hub.load('snakers4/silero-models', 'silero_tts', language='ru', speaker='v4_ru', trust_repo=True)"
ENV VOSK_MODEL_PATH=/app/models/vosk-small-ru

CMD ["python", "work_bot.py"]