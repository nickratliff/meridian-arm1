# Meridian Arm 1 — Railway Dockerfile
# Node 20 + Python 3 + requests/beautifulsoup (no browser needed for PVA)
# Playwright + Chromium kept for generate_pptx.py

FROM node:20-bookworm

# Install Python and pip
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Node dependencies
COPY package*.json ./
RUN npm install --omit=dev

# Copy all project files
COPY . .

# Install Python dependencies
RUN pip3 install requests beautifulsoup4 playwright python-pptx --break-system-packages

# Install Playwright Chromium for presentation generation only
RUN playwright install --with-deps chromium

EXPOSE 3000

CMD ["node", "server.js"]
