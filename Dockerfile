# 1. Chọn hệ điều hành cơ bản: Python 3.10 trên nền Linux nhẹ (Slim)
FROM python:3.10-slim

# 2. Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# 3. Cài đặt các thư viện hệ thống cần thiết cho WeasyPrint
# Đây là bước quan trọng nhất để fix lỗi "OSError: cannot load library" trên Linux/Docker
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
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy file requirements.txt vào trước để tận dụng cache của Docker
COPY requirements.txt .

# 5. Cài đặt các thư viện Python
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy toàn bộ code còn lại (main.py, templates, .env) vào container
COPY . .

# 7. Mở cổng 8000
EXPOSE 8000

# 8. Lệnh chạy server
# Lưu ý: host phải là "0.0.0.0" để bên ngoài truy cập được
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]