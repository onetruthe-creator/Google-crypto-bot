# SOVEREIGN — Windows Startup Script
# Run this from PowerShell: .\start_sovereign.ps1
# Starts all four services in separate windows

param(
    [string]$SovereignDir = "$env:USERPROFILE\sovereign",
    [string]$SlackBotToken = $env:SLACK_BOT_TOKEN,
    [string]$SlackAppToken = $env:SLACK_APP_TOKEN,
    [string]$OllamaUrl    = "http://localhost:11434/api/generate",
    [string]$OllamaModel  = "llama3.2:1b"
)

$env:SOVEREIGN_DIR   = $SovereignDir
$env:SOVEREIGN_URL   = "http://localhost:8888"
$env:METACLAW_URL    = "http://localhost:5002"
$env:ZEROCLAW_URL    = "http://localhost:5001"
$env:SLACK_BRIDGE_URL= "http://localhost:5003"
$env:OLLAMA_URL      = $OllamaUrl
$env:OLLAMA_MODEL    = $OllamaModel

# Create the sovereign directory if it doesn't exist
New-Item -ItemType Directory -Force -Path $SovereignDir | Out-Null

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Start-Service($name, $script) {
    $args = "-NoExit -Command `"cd '$root'; `$env:SOVEREIGN_DIR='$SovereignDir'; `$env:SOVEREIGN_URL='http://localhost:8888'; `$env:METACLAW_URL='http://localhost:5002'; `$env:ZEROCLAW_URL='http://localhost:5001'; `$env:OLLAMA_URL='$OllamaUrl'; `$env:OLLAMA_MODEL='$OllamaModel'; python '$root\$script'`""
    Start-Process powershell -ArgumentList $args -WindowStyle Normal
    Write-Host "Started $name"
    Start-Sleep -Seconds 2
}

Write-Host "Starting SOVEREIGN on Windows..."
Write-Host "Data directory: $SovereignDir"
Write-Host ""

Start-Service "ZeroClaw   (port 5001)" "sovereign-executor.py"
Start-Service "MetaClaw   (port 5002)" "sovereign-brain.py"
Start-Service "SOVEREIGN  (port 8888)" "app.py"

# Only start the Slack bot if tokens are provided
if ($SlackBotToken -and $SlackAppToken) {
    $env:SLACK_BOT_TOKEN = $SlackBotToken
    $env:SLACK_APP_TOKEN = $SlackAppToken
    $botArgs = "-NoExit -Command `"cd '$root'; `$env:SOVEREIGN_DIR='$SovereignDir'; `$env:SOVEREIGN_URL='http://localhost:8888'; `$env:METACLAW_URL='http://localhost:5002'; `$env:SLACK_BOT_TOKEN='$SlackBotToken'; `$env:SLACK_APP_TOKEN='$SlackAppToken'; python '$root\sovereign_bot.py'`""
    Start-Process powershell -ArgumentList $botArgs -WindowStyle Normal
    Write-Host "Started  Slack Bot  (Socket Mode)"
} else {
    Write-Host ""
    Write-Host "Slack bot NOT started — set SLACK_BOT_TOKEN and SLACK_APP_TOKEN to enable it."
    Write-Host "Example:"
    Write-Host "  .\start_sovereign.ps1 -SlackBotToken xoxb-... -SlackAppToken xapp-..."
}

Write-Host ""
Write-Host "All services launching. Dashboard: http://localhost:8888/dashboard"
