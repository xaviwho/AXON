# ----------------------------------------------------------------------------
# Stage 1 — model builder.
# Uses ultralytics+torch to fetch YOLOv10-L .pt weights and export to .onnx.
# Throw-away stage; not present in the runtime image.
# ----------------------------------------------------------------------------
FROM python:3.11-slim AS model-builder

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        torch==2.4.1 \
        ultralytics==8.3.40 \
        onnxslim==0.1.42 \
        onnx==1.17.0

WORKDIR /build

# Trigger Ultralytics auto-download of yolov10l.pt and export to ONNX.
# `imgsz=640 dynamic=False simplify=True` matches our runtime preprocess.
RUN python -c "from ultralytics import YOLO; YOLO('yolov10l.pt').export(format='onnx', imgsz=640, dynamic=False, simplify=True)"

# Fetch the MediaPipe Pose Landmarker (Full) task model.
RUN wget -q -O /build/pose_landmarker_full.task \
        https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task

# Extract Ultralytics' bundled test photographs (zidane.jpg, bus.jpg) — they
# ship with the pip package as standard test fixtures. We use them as the
# baked-in still-image source for the mock_movement scenario so the demo
# pipeline produces real YOLO + MediaPipe detections without requiring a
# user-supplied video clip. License: AGPL-3.0 (Ultralytics), used here in
# the same testing/fair-use spirit as the upstream project.
RUN cp /usr/local/lib/python3.11/site-packages/ultralytics/assets/zidane.jpg /build/zidane.jpg \
 && cp /usr/local/lib/python3.11/site-packages/ultralytics/assets/bus.jpg    /build/bus.jpg


# ----------------------------------------------------------------------------
# Stage 2 — runtime.
# Slim Python + onnxruntime + opencv + mediapipe. No torch, no ultralytics.
# ----------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY services/vision/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt

COPY --from=model-builder /build/yolov10l.onnx           /srv/models/yolov10l.onnx
COPY --from=model-builder /build/pose_landmarker_full.task /srv/models/pose_landmarker_full.task
COPY --from=model-builder /build/zidane.jpg              /srv/assets/zidane.jpg
COPY --from=model-builder /build/bus.jpg                 /srv/assets/bus.jpg

COPY services/vision/app    /srv/app
COPY shared                 /srv/shared

ENV PYTHONPATH=/srv

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
