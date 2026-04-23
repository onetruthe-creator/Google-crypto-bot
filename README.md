# Google-crypto-bot

A cryptocurrency trading bot.

## Prerequisites

This project requires **Node.js** (which includes `npm`). If you see the error:

```
'npm' is not recognized as an internal or external command, operable program or batch file.
```

Node.js is not installed or not added to your system PATH. Follow the steps below for your OS.

---

## Setup

### Windows

1. **Download Node.js** from [https://nodejs.org/](https://nodejs.org/)
   - Choose the **LTS** version (recommended for most users)

2. **Run the installer** — accept the defaults, and make sure **"Add to PATH"** is checked during installation.

3. **Restart your terminal** (Command Prompt or PowerShell) after installation.

4. **Verify installation:**
   ```cmd
   node --version
   npm --version
   ```

5. **Now run the install command:**
   ```cmd
   npm install -g openclaw@latest
   ```

#### Alternative: Install via winget (Windows Package Manager)
```cmd
winget install OpenJS.NodeJS.LTS
```
Then restart your terminal and retry.

#### Alternative: Install via nvm-windows (recommended for managing multiple Node versions)
1. Download [nvm-windows](https://github.com/coreybutler/nvm-windows/releases) and install it.
2. Then run:
   ```cmd
   nvm install lts
   nvm use lts
   ```

---

### macOS

```bash
# Using Homebrew
brew install node

# Verify
node --version
npm --version
```

### Linux

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y nodejs npm

# Or use NodeSource for a newer version:
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
```

---

## Installation

Once Node.js is installed and `npm` is recognized:

```bash
npm install
```

## Usage

```bash
npm start
```

## Troubleshooting

**`npm` still not recognized after installing Node.js (Windows)?**

1. Open **System Properties** → **Advanced** → **Environment Variables**
2. Under **System variables**, find `Path` and click **Edit**
3. Confirm these entries exist (adjust version number as needed):
   - `C:\Program Files\nodejs\`
4. Click OK, then **restart your terminal completely** (close and reopen)

**Using PowerShell and getting a script execution policy error?**

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
