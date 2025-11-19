from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
from datetime import datetime

# =========================================================
#  TELEGRAM BOT TOKEN TỪ BIẾN MÔI TRƯỜNG
# =========================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# =========================================================
#  KẾT NỐI GOOGLE SHEET
# =========================================================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

if "GOOGLE_CREDENTIALS" in os.environ:
    # Trên Railway: dùng biến môi trường GOOGLE_CREDENTIALS (JSON)
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    # Local: dùng file service_account.json
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope
    )

client = gspread.authorize(creds)

SHEET_NAME = "77_Delivery_System"
menu_sheet = client.open(SHEET_NAME).worksheet("MENU")
orders_sheet = client.open(SHEET_NAME).worksheet("ORDERS")
settings_sheet = client.open(SHEET_NAME).worksheet("SETTINGS")

# =========================================================
#  CART & NGÔN NGỮ TRONG RAM
# =========================================================
CARTS = {}  # {user_id: [{"id": str, "name": str, "price": int, "qty": int}, ...]}

# =========================================================
#  ĐA NGÔN NGỮ
# =========================================================
MESSAGES = {
    "welcome": {
        "vi": "Xin chào! Vui lòng chọn ngôn ngữ / Please choose language:",
        "en": "Hello! Please choose your language:"
    },
    "lang_set_vi": {
        "vi": "✅ Bạn đã chọn Tiếng Việt.",
        "en": "✅ You switched to Vietnamese."
    },
    "lang_set_en": {
        "vi": "✅ Bạn đã chuyển sang English.",
        "en": "✅ You switched to English."
    },
    "menu_header": {
        "vi": "📋 MENU HÔM NAY:",
        "en": "📋 TODAY'S MENU:"
    },
    "empty_menu": {
        "vi": "Hiện chưa có món nào trong menu.",
        "en": "No items in the menu yet."
    },
    "add_usage": {
        "vi": "Cách dùng: /add <ID_món> [số_lượng]. Ví dụ: /add F01 2",
        "en": "Usage: /add <item_id> [qty]. Example: /add F01 2"
    },
    "item_not_found": {
        "vi": "❌ Không tìm thấy món với ID đó.",
        "en": "❌ Item not found with that ID."
    },
    "added_to_cart": {
        "vi": "✅ Đã thêm vào giỏ: {qty} x {name}",
        "en": "✅ Added to cart: {qty} x {name}"
    },
    "cart_empty": {
        "vi": "🛒 Giỏ hàng của bạn đang trống.",
        "en": "🛒 Your cart is empty."
    },
    "cart_header": {
        "vi": "🛒 Giỏ hàng hiện tại:",
        "en": "🛒 Your current cart:"
    },
    "order_start": {
        "vi": "📦 Bắt đầu đặt hàng. Vui lòng nhập SỐ ĐIỆN THOẠI:",
        "en": "📦 Start order. Please send your PHONE NUMBER:"
    },
    "ask_address": {
        "vi": "Vui lòng gửi ĐỊA CHỈ giao hàng:",
        "en": "Please send your DELIVERY ADDRESS:"
    },
    "order_summary": {
        "vi": "Xác nhận đơn:\n{items}\nTổng: {total}đ\nSĐT: {phone}\nĐịa chỉ: {address}\n\nGõ 'yes' để xác nhận, 'no' để hủy.",
        "en": "Order summary:\n{items}\nTotal: {total} VND\nPhone: {phone}\nAddress: {address}\n\nType 'yes' to confirm, 'no' to cancel."
    },
    "order_saved": {
        "vi": "✅ Đơn của bạn đã được ghi nhận! Mã đơn: {order_id}",
        "en": "✅ Your order has been placed! Order ID: {order_id}"
    },
    "order_cancelled": {
        "vi": "❌ Đã hủy đơn.",
        "en": "❌ Order cancelled."
    }
}

PHONE, ADDRESS, CONFIRM = range(3)

# =========================================================
#  HÀM NGÔN NGỮ
# =========================================================
def get_default_lang() -> str:
    """Đọc ngôn ngữ mặc định từ sheet SETTINGS (key=language_default)."""
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key", "")).strip() == "language_default":
                return str(row.get("value", "vi")).strip()
    except Exception:
        pass
    return "vi"


def get_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    lang = context.user_data.get("lang")
    if not lang:
        lang = get_default_lang()
        context.user_data["lang"] = lang
    return lang


def t(context: ContextTypes.DEFAULT_TYPE, user_id: int, key: str, **kwargs) -> str:
    lang = get_lang(context, user_id)
    text = MESSAGES.get(key, {}).get(lang, "")
    if kwargs:
        text = text.format(**kwargs)
    return text

# =========================================================
#  HANDLERS /start + chọn ngôn ngữ
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.setdefault("lang", get_default_lang())

    keyboard = [
        [
            InlineKeyboardButton("🇻🇳 Tiếng Việt", callback_data="lang_vi"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        t(context, user.id, "welcome"),
        reply_markup=reply_markup
    )


async def lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "lang_vi":
        context.user_data["lang"] = "vi"
        await query.edit_message_text(
            t(context, user.id, "lang_set_vi")
        )
    elif query.data == "lang_en":
        context.user_data["lang"] = "en"
        await query.edit_message_text(
            t(context, user.id, "lang_set_en")
        )

# =========================================================
#  ĐỌC MENU TỪ GOOGLE SHEET
# =========================================================
def load_menu():
    """
    Đọc toàn bộ menu từ sheet MENU và chuẩn hóa key theo code.

    Sheet MENU: ID | Name_VI | Name_EN | Price | Category | Status
    (không cần đúng hoa thường 100%, mình xử lý bớt rồi)
    """
    try:
        records_raw = menu_sheet.get_all_records()
    except Exception as e:
        print("ERROR load_menu step1:", e)
        return []

    records = []
    for r in records_raw:
        try:
            # Chấp nhận nhiều kiểu header khác nhau
            item_id = (
                r.get("ID")
                or r.get("Id")
                or r.get("id")
                or r.get("Mã")
                or ""
            )
            item_id = str(item_id).strip()
            if not item_id:
                continue

            name_vi = (
                r.get("Name_VI")
                or r.get("NAME_VI")
                or r.get("Tên_VI")
                or r.get("Name Vi")
                or ""
            )
            name_en = (
                r.get("Name_EN")
                or r.get("NAME_EN")
                or r.get("Tên_EN")
                or r.get("Name En")
                or ""
            )

            # Price có thể là số, chuỗi có khoảng trắng, float...
            raw_price = (
                r.get("Price")
                or r.get("PRICE")
                or r.get("Giá")
                or 0
            )
            if raw_price in ("", None):
                price = 0
            else:
                try:
                    price = int(raw_price)
                except ValueError:
                    price = int(float(str(raw_price).replace(",", "")))

            status = (
                r.get("Status")
                or r.get("status")
                or r.get("Trạng thái")
                or "active"
            )
            status = str(status).strip().lower()

            records.append({
                "id": item_id,
                "name_vi": str(name_vi).strip(),
                "name_en": str(name_en).strip(),
                "price": price,
                "status": status,
            })
        except Exception as e:
            # Nếu 1 dòng lỗi thì bỏ qua, không làm sập cả /menu
            print("ERROR load_menu row:", r, "->", e)
            continue

    return records

# =========================================================
#  /menu
# =========================================================
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        lang = get_lang(context, user.id)
        records = load_menu()

        if not records:
            await update.message.reply_text(
                t(context, user.id, "empty_menu")
            )
            return

        lines = [t(context, user.id, "menu_header"), ""]
        for item in records:
            if item["status"] not in ("active", "sold_out"):
                continue

            name = item["name_vi"] if lang == "vi" else item["name_en"]
            status_txt = ""
            if item["status"] == "sold_out":
                status_txt = " (hết / sold out)"

            lines.append(f"{item['id']}. {name} - {item['price']}đ{status_txt}")

        lines.append("")
        lines.append(t(context, user.id, "add_usage"))

        await update.message.reply_text("\n".join(lines))

    except Exception as e:
        # Nếu còn lỗi gì nữa thì cũng trả lời cho user biết
        print("ERROR in /menu handler:", e)
        await update.message.reply_text(
            "🚫 Bot bị lỗi khi đọc MENU. Vui lòng kiểm tra lại Google Sheet hoặc xem logs trên Railway."
        )

# =========================================================
#  CART
# =========================================================
def add_to_cart(user_id: int, item: dict, qty: int):
    cart = CARTS.get(user_id, [])
    for row in cart:
        if row["id"] == item["id"]:
            row["qty"] += qty
            break
    else:
        cart.append({
            "id": item["id"],
            "name": item["name"],
            "price": item["price"],
            "qty": qty
        })
    CARTS[user_id] = cart


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            t(context, user.id, "add_usage")
        )
        return

    # ID dạng chuỗi: F01, f01, f02...
    item_id = args[0].strip().upper()

    qty = 1
    if len(args) >= 2:
        try:
            qty = int(args[1])
        except ValueError:
            qty = 1

    lang = get_lang(context, user.id)
    records = load_menu()
    target = None
    for item in records:
        if item["id"].upper() == item_id:
            target = item
            break

    if not target:
        await update.message.reply_text(
            t(context, user.id, "item_not_found")
        )
        return

    name = target["name_vi"] if lang == "vi" else target["name_en"]
    add_to_cart(
        user.id,
        {"id": target["id"], "name": name, "price": target["price"]},
        qty
    )

    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
    )


async def cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cart = CARTS.get(user.id, [])

    if not cart:
        await update.message.reply_text(
            t(context, user.id, "cart_empty")
        )
        return

    lines = [t(context, user.id, "cart_header"), ""]
    total = 0
    for row in cart:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")

    await update.message.reply_text("\n".join(lines))

# =========================================================
#  FLOW /order
# =========================================================
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cart = CARTS.get(user.id, [])
    if not cart:
        await update.message.reply_text(
            t(context, user.id, "cart_empty")
        )
        return ConversationHandler.END

    await update.message.reply_text(
        t(context, user.id, "order_start")
    )
    return PHONE


async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["order_phone"] = update.message.text.strip()
    await update.message.reply_text(
        t(context, user.id, "ask_address")
    )
    return ADDRESS


async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["order_address"] = update.message.text.strip()

    cart = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart)
    lines = []
    for row in cart:
        lines.append(f"{row['qty']} x {row['name']} = {row['price'] * row['qty']}đ")

    items_text = "\n".join(lines)
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]

    await update.message.reply_text(
        t(
            context, user.id, "order_summary",
            items=items_text, total=total, phone=phone, address=address
        )
    )
    return CONFIRM


async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()
    if text not in ["yes", "y", "có", "ok", "đồng ý"]:
        await update.message.reply_text(
            t(context, user.id, "order_cancelled")
        )
        return ConversationHandler.END

    cart = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart)
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]
    lang = get_lang(context, user.id)

    # order_id đơn giản = số dòng hiện tại + 10001
    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_text = ", ".join([f"{row['qty']}x {row['name']}" for row in cart])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Ghi vào sheet ORDERS
    orders_sheet.append_row([
        order_id,
        user.id,
        user.username or "",
        phone,
        items_text,
        total,
        address,
        lang,
        now_str,
        "pending"
    ])

    # Xóa cart
    CARTS[user.id] = []

    await update.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )
    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        t(context, user.id, "order_cancelled")
    )
    return ConversationHandler.END

# =========================================================
#  MAIN
# =========================================================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /start + chọn ngôn ngữ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))

    # Menu & cart
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart))

    # Conversation /order
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

