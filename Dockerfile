# Use Python 3.11 slim image
FROM python:3.11-slim

# Install system dependencies for Pillow and pytesseract
RUN apt-get update && apt-get install -y \
    libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expose port (adjust if your app runs on another port)
EXPOSE 10000

# Run the app using gunicorn
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:10000"]
