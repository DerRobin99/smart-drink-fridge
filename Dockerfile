FROM python:3.11-slim
ENV TZ=Europe/Berlin

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV DATABASE_PATH=/data/getraenke.db
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python3", "app.py"]
