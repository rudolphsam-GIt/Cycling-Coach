#!/bin/bash
set -e

echo ""
echo "======================================"
echo "  Cycling Coach — Setup"
echo "======================================"
echo ""

# The Garmin library needs Python 3.12+. uv installs it without touching the system Python.
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
if [ ! -x "$UV" ]; then
    echo "📦 Installing uv (Python manager, no admin password needed)..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
    UV="$HOME/.local/bin/uv"
fi

# Create virtualenv on Python 3.12
if [ ! -x "venv/bin/python" ] || ! venv/bin/python -c "import sys; sys.exit(sys.version_info < (3, 12))"; then
    echo "📦 Creating a Python 3.12 environment..."
    rm -rf venv
    "$UV" venv --python 3.12 venv
fi
echo "✅ $(venv/bin/python --version) ready"

echo "📦 Installing packages (this takes ~1 minute)..."
"$UV" pip install --quiet --python venv/bin/python -r requirements.txt
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
echo "     and add your Claude API key. (Connect Garmin later from Settings.)"
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
