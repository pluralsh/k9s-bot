# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY doggo.py .
COPY prompts ./prompts
COPY tools ./tools

# Run the application
CMD ["python", "doggo.py"]

