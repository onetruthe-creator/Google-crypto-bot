#!/usr/bin/env bash
# Sets up the 'zc' shortcut for ZeroClaw via MetaClaw proxy
set -euo pipefail

SCRIPT="$HOME/.zc"

cat > "$SCRIPT" << 'INNEREOF'
#!/usr/bin/env bash
exec zeroclaw agent --provider "custom:http://127.0.0.1:30000/v1" --model llama3.2 "$@"
INNEREOF

chmod +x "$SCRIPT"

# Remove any old zc alias
sed -i '/alias zc=/d' "$HOME/.bashrc"

echo 'alias zc="$HOME/.zc"' >> "$HOME/.bashrc"

echo "Done. Run: source ~/.bashrc && zc -m 'Hello!'"
