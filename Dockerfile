# Use the official Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    build-essential \
    gcc \
    g++ \
    && apt-get clean

# Set up work directory
WORKDIR /app

# Install GDAL Python package with the correct version
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
RUN pip install --upgrade pip
RUN pip install GDAL==$(gdal-config --version) --global-option=build_ext --global-option="-I/usr/include/gdal"

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Django project files to the container
COPY ./resc /app/resc
COPY .env /app/.env

# Set PYTHONPATH environment variable
ENV PYTHONPATH=/app/resc

# Collect static files (optional step for production)
RUN python /app/resc/manage.py collectstatic --noinput

# Expose port 8000
EXPOSE 8000

