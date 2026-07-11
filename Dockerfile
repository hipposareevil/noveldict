FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY noveldict_editor.py .
COPY . .

# Create output directory for master_dictionary.json
RUN mkdir -p /home/noveldict_output

# Expose the web UI port
EXPOSE 5001

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the editor with custom output directory pointing to a volume
CMD ["python3", "noveldict_editor.py", "--output-dir", "/home/noveldict_output", "--port", "5001", "--host", "0.0.0.0"]

