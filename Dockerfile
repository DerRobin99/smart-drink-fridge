# syntax=docker/dockerfile:1

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
    util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .
# The wheels are bind-mounted from the builder stage rather than COPYed in. A
# COPY commits them to their own layer, and the `rm -rf` that used to follow
# could only write a whiteout on top of that layer -- it cannot remove a layer
# that is already committed, so the wheels shipped in every pull. A bind mount
# is never committed to a layer, so there is nothing left to remove.
RUN --mount=type=bind,from=builder,source=/tmp/wheels,target=/tmp/wheels \
    pip install --no-cache-dir \
    --no-index \
    --find-links=/tmp/wheels \
    -r requirements.txt

COPY . .

RUN cp -a translations translations-bundled \
    && mkdir -p /data

ENV DATABASE_PATH=/data/getraenke.db
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python3", "app.py"]
