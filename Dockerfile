FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for common Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements.txt from the correct subdirectory
COPY school-management-system/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy project
COPY . /app

# Set working dir to the django project folder
WORKDIR /app/school-management-system


ENV PORT=8000
EXPOSE 8000

CMD ["gunicorn", "bjs_management.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
