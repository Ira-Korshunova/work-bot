# Work Bot (@DiV_executive_bot) — Telegram-бот: документы/фото/голос + база ВЭД
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Tesseract с рус/англ языками + poppler (преобразование PDF в картинки для OCR)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng poppler-utils \
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

CMD ["python", "work_bot.py"]