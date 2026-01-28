# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies and timezone data
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Bangkok
ENV TZ=Asia/Bangkok
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY discord-bot.py .
COPY api_bot.py .

# Create directory for credentials (will be mounted at runtime)
RUN mkdir -p /app/credentials

# Run the Discord bot
CMD ["python", "-u", "discord-bot.py"]
