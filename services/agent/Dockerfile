FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # sentence-transformers pulls torch; the default PyPI wheel bundles CUDA
    # (~2.5 GB with nvidia-* deps). MiniLM embeddings run fine on CPU, so
    # resolve torch from the CPU-only index (~200 MB).
    PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /srv

COPY services/agent/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

# Bake the MiniLM embedding model into the image (as vision bakes YOLO) so the
# agent never downloads from HuggingFace at runtime: sites may be offline, and
# CLAUDE.md forbids third-party endpoints at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY services/agent/app   /srv/app
COPY shared               /srv/shared
# Mount the knowledge_base as a top-level dir at the path the agent expects.
COPY shared/knowledge_base /srv/knowledge_base

ENV PYTHONPATH=/srv

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
