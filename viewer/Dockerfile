ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IMAGE_CACHE_DIR=/cache

WORKDIR /srv/viewer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin mbviewer \
    && mkdir /cache && chown 10001:10001 /cache
USER 10001

EXPOSE 8000
CMD ["uvicorn", "--factory", "app.main:app_factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
