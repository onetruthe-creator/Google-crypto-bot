#!/usr/bin/env python3
"""Telegram → MetaClaw bridge (python-telegram-bot v20+)"""

import logging
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = "8560629842:AAFp6oQxXIA7X8Rut6pNHJPSlBZRlLJ7rRg"
METACLAW = "http://127.0.0.1:30000/v1/chat/completions"

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    print(f"📨 Received: {user_msg}")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(METACLAW, json={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": user_msg}]
            })
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        reply = f"❌ Error: {e}"

    print(f"📤 Replied: {reply[:100]}")
    await update.message.reply_text(reply)

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 Telegram bridge running...")
app.run_polling()
