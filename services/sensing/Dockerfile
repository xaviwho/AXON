FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# opencv-python-headless needs libGL stubs even in headless mode for runtime loading.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY services/sensing/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

COPY services/sensing/app /srv/app
COPY shared /srv/shared

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
