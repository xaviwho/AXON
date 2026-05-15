FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY services/vlm/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

COPY services/vlm/app /srv/app
COPY shared           /srv/shared

ENV PYTHONPATH=/srv

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
