FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY services/console_api/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

# Console API imports fusion's rule schema for PUT /rules validation.
COPY services/console_api/app /srv/app
COPY services/fusion/app      /srv/services/fusion/app
COPY services/fusion/__init__.py /srv/services/fusion/__init__.py
COPY shared                   /srv/shared

# Stub package init so `from services.fusion.app.rules import …` resolves.
RUN mkdir -p /srv/services && touch /srv/services/__init__.py

ENV PYTHONPATH=/srv

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
