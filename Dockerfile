# Use Python 3.11 as the base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create necessary directories
RUN mkdir -p uploads

# Expose the port the app runs on
EXPOSE 8000

# Add a check for the environment variable
RUN echo "Checking environment variables..." && \
    if [ -z "$RAPID7_API_KEY" ]; then \
        echo "RAPID7_API_KEY is not set"; \
    else \
        echo "RAPID7_API_KEY is set"; \
    fi

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"] 