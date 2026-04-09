#!/usr/bin/env bash
# Converts VoltAgent/awesome-codex-subagents into ZeroClaw SKILL.md files
# Usage: bash install_voltagent_skills.sh
set -euo pipefail

REPO_URL="https://github.com/VoltAgent/awesome-codex-subagents.git"
SKILLS_DIR="${HOME}/.zeroclaw/workspace/skills"
TMP_DIR=$(mktemp -d)

info()  { echo "[INFO]  $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

command -v python3 &>/dev/null || die "python3 is required"

info "Cloning VoltAgent/awesome-codex-subagents..."
git clone --depth 1 "$REPO_URL" "$TMP_DIR/voltagent"

mkdir -p "$SKILLS_DIR"

# Python does the TOML parsing and SKILL.md generation
python3 - "$TMP_DIR/voltagent" "$SKILLS_DIR" <<'PYEOF'
import sys, os, re, glob

src_dir   = sys.argv[1]
skills_dir = sys.argv[2]

def parse_toml_simple(text):
    """Minimal TOML parser — handles the flat fields used by these agents."""
    result = {}
    # instructions.text block
    m = re.search(r'\[instructions\]\s*\ntext\s*=\s*"""(.*?)"""', text, re.DOTALL)
    if m:
        result['instructions'] = m.group(1).strip()
    # scalar string fields
    for key in ('name', 'description', 'model', 'sandbox_mode'):
        m = re.search(rf'^{key}\s*=\s*"([^"]*)"', text, re.MULTILINE)
        if m:
            result[key] = m.group(1)
    return result

toml_files = glob.glob(os.path.join(src_dir, '**', '*.toml'), recursive=True)
converted = 0
skipped   = 0

for path in sorted(toml_files):
    with open(path, encoding='utf-8', errors='replace') as f:
        raw = f.read()

    data = parse_toml_simple(raw)
    name = data.get('name') or os.path.splitext(os.path.basename(path))[0]
    desc = data.get('description', 'No description provided.')
    instructions = data.get('instructions', '')

    if not instructions:
        print(f"  [SKIP] {name} — no instructions block found")
        skipped += 1
        continue

    skill_dir = os.path.join(skills_dir, name)
    os.makedirs(skill_dir, exist_ok=True)
    skill_path = os.path.join(skill_dir, 'SKILL.md')

    with open(skill_path, 'w', encoding='utf-8') as f:
        f.write(f"# {name}\n\n")
        f.write(f"{desc}\n\n")
        f.write(instructions)
        f.write("\n")

    print(f"  [OK]   {name}")
    converted += 1

print(f"\nDone: {converted} skills installed, {skipped} skipped.")
PYEOF

rm -rf "$TMP_DIR"

info "Skills installed to $SKILLS_DIR"
info "Verify with: zeroclaw skills list"
