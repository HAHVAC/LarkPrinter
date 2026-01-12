# Sử dụng Python 3.10-slim (như log bạn đang chạy)
FROM python:3.10-slim

WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết cho WeasyPrint/PDF
# Đã sửa lỗi libgdk-pixbuf-2.0-0
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-cffi \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements và cài thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Mở port
EXPOSE 8000

# Chạy app (Lưu ý: đảm bảo main.py chạy host='0.0.0.0')
CMD ["python", "main.py"]