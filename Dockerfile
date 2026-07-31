FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y \
    gcc \
    libpcsclite-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir \
    --wheel-dir /tmp/wheels \
    -r /tmp/requirements.txt

FROM python:3.11-slim
ENV TZ=Europe/Berlin

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    pcscd \
    && rm -rf /var/lib/apt/lists/*
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .
COPY --from=builder /tmp/wheels /tmp/wheels
RUN pip install --no-cache-dir \
    --no-index \
    --find-links=/tmp/wheels \
    -r requirements.txt \
    && rm -rf /tmp/wheels

COPY . .

RUN mkdir -p /data

ENV DATABASE_PATH=/data/getraenke.db
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python3", "app.py"]
