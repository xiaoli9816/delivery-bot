from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json

# 🚨 Lưu ý:
# - Trên Railway: BOT_TOKEN sẽ lấy từ biến môi trường BOT_TOKEN
# - Trên máy local: bạn có thể đặt BOT_TOKEN trực tiếp hoặc cũng dùng biến môi trường

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("Thiếu BOT_TOKEN trong biến môi trường!")

# Kết nối Google Sheet
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Trên Railway: dùng biến môi trường GOOGLE_CREDENTIALS
if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    # Chạy local: dùng file service_account.json trong cùng thư mục
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope
    )

client = gspread.authorize(creds)

# Mở file Google Sheet và sheet MENU
sheet = client.open("77_Delivery_System").worksheet("MENU")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = sheet.get_all_records()
    await update.message.reply_text(
        f"✅ Bot đã kết nối Google Sheet thành công!\n"
        f"Hiện có {len(data)} món trong MENU."
    )


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling(drop_pending_updates=True)
