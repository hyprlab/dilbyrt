FROM python:3.12-slim

WORKDIR /srv

# tesseract-ocr provides the OCR engine pytesseract shells out to.
# libjpeg/zlib are Pillow runtime deps for reading phone photos.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libjpeg62-turbo zlib1g libtiff6 libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    DILBYRT_DATA_DIR=/data \
    DILBYRT_UPLOAD_DIR=/data/uploads

RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "120", "--access-logfile", "-", "run:app"]
