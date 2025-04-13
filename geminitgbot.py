import os
import json
import base64
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
credentials_base64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
CREDENTIALS = json.loads(base64.b64decode(credentials_base64).decode('utf-8')) if credentials_base64 else None

async def translate_test(update: Update, context):
    try:
        print(f"尝试访问: {CREDENTIALS_FILE}") # 故意访问不存在的变量
        await context.bot.send_message(chat_id=update.effective_chat.id, text="测试翻译")
    except NameError as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"发生 NameError: {e}")

async def start(update: Update, context):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Bot 已启动")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translate_test))
    app.run_polling()

if __name__ == '__main__':
    main()
