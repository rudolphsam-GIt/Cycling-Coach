#!/bin/bash
set -e

echo ""
echo "======================================"
echo "  Cycling Coach — Setup"
echo "======================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found."
    echo "   Install it from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python $PYTHON_VER found"

# Create virtualenv
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

echo "📦 Installing packages (this takes ~1 minute)..."
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
echo "✅ Packages installed"

# Copy .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ Created .env file"
fi

# Create data dir
mkdir -p data

echo ""
echo "======================================"
echo "  ✅ Setup complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Open the file '.env' in a text editor"
echo "     and fill in your Strava, Garmin, and Claude API keys."
echo "     (Instructions are in the file itself)"
echo ""
echo "  2. Start the app:"
echo "     ./venv/bin/streamlit run app.py"
echo ""
echo "  Or run this shortcut next time:"
echo "     bash start.sh"
echo ""

# Create a convenient start script
cat > start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
./venv/bin/streamlit run app.py
EOF
chmod +x start.sh
echo "✅ Created start.sh — just double-click or run 'bash start.sh' to launch the app anytime."
echo ""
