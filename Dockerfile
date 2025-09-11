# Use official Python 3.11 image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Install system dependencies for Pillow and pytesseract
RUN apt-get update && \
    apt-get install -y \
        tesseract-ocr \
        libtesseract-dev \
        poppler-utils \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
        libpng-dev \
        git \
        && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the entire project
COPY . .

# Expose port (Render uses PORT env variable)
ENV PORT 10000
EXPOSE $PORT

# Start the app using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]
