#!/usr/bin/env bash
set -e

VENV_DIR=".venv"

echo "Creating virtual environment in $VENV_DIR ..."
python3 -m venv "$VENV_DIR"

echo "Installing dependencies ..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example."
    echo "Open .env and fill in your ANTHROPIC_API_KEY and exchange credentials."
else
    echo ".env already exists — skipping copy."
fi

echo ""
echo "Setup complete. Run the bot with:"
echo "  .venv/bin/python bot.py"
