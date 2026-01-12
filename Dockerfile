FROM python:3.10-slim

WORKDIR /app

# (1) System deps for WeasyPrint + fonts for Vietnamese rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fontconfig \
    fonts-dejavu-core \
    fonts-noto-core \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# (2) Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# (3) Copy app
COPY . .

EXPOSE 8000

# (4) Run production server (recommended)
# Nếu bạn vẫn muốn chạy python main.py thì đổi CMD lại như cũ.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
