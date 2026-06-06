#!/bin/bash
# ================================================================
# RSS Digest — One-command VPS deployment script
# Run this ON YOUR VPS (not your local machine)
# ================================================================
set -e

echo "========================================"
echo " RSS Digest — VPS Setup"
echo "========================================"
echo ""

# ── 1. Update system ──────────────────────────────────────────
echo "[1/5] Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

# ── 2. Install Docker ─────────────────────────────────────────
echo "[2/5] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable docker --now

# ── 3. Set up project directory ───────────────────────────────
echo "[3/5] Setting up project..."
mkdir -p /opt/rss-digest/data
cd /opt/rss-digest

# ── 4. Create .env from example ───────────────────────────────
if [ ! -f .env ]; then
    echo "[4/5] You need to create your .env file."
    echo ""
    echo "  Copy-paste your .env contents now (from your local machine):"
    echo "  nano /opt/rss-digest/.env"
    echo ""
    echo "  Your .env should have at least:"
    echo "    GEMINI_API_KEY=..."
    echo "    GROQ_API_KEY=..."
    echo ""
    echo "  Then re-run this script."
    exit 1
fi

# ── 5. Start with Docker Compose ──────────────────────────────
echo "[5/5] Starting RSS Digest..."
docker compose up -d --build

echo ""
echo "========================================"
echo " Deployment complete!"
echo ""
echo " Check status:  docker compose ps"
echo " View logs:     docker compose logs -f"
echo " Health check:  curl localhost:8000/health"
echo ""
echo " Your digest will be auto-generated daily at 8:00 PM IST."
echo "========================================"
