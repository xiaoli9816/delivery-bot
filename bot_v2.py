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

# ==== KẾT NỐI TELEGRAM TOKEN TỪ BIẾN MÔI TRƯỜNG ====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# ==== KẾT NỐI GOOGLE SHEET ====
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

if "GOOGLE_CREDENTIALS" in os.environ:
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

# ==== GIỮ CART & NGÔN NGỮ TRONG RAM ====
CARTS = {}  # {user_id: [{"id": id, "name": str, "price": int, "qty": int}, ...]}

# ==== ĐA NGÔN NGỮ ====
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
        "vi": "Cách dùng: /add <id_món> [số_lượng]. Ví dụ: /add 1 2",
        "en": "Usage: /add <item_id> [qty]. Example: /add 1 2"
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


def get_default_lang() -> str:
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if row["key"] == "language_default":
                return row["value"]
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


# ==== HANDLERS ====

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


def load_menu():
    """Đọc toàn bộ menu từ sheet."""
    return menu_sheet.get_all_records()


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)
    records = load_menu()

    if not records:
        await update.message.reply_text(
            t(context, user.id, "empty_menu")
        )
        return

    lines = [t(context, user.id, "menu_header"), ""]
    for item in records:
        if item.get("status", "").lower() not in ("active", "sold_out"):
            continue
        name = item["name_vi"] if lang == "vi" else item["name_en"]
        status = item.get("status", "active")
        status_txt = ""
        if status == "sold_out":
            status_txt = " (hết / sold out)"
        lines.append(f"{item['id']}. {name} - {item['price']}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user.id, "add_usage"))

    await update.message.reply_text("\n".join(lines))


def add_to_cart(user_id: int, item: dict, qty: int):
    cart = CARTS.get(user_id, [])
    # nếu món đã có, cộng dồn
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

    try:
        item_id = int(args[0])
    except ValueError:
        await update.message.reply_text(
            t(context, user.id, "add_usage")
        )
        return

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
        if int(item["id"]) == item_id:
            target = item
            break

    if not target:
        await update.message.reply_text(
            t(context, user.id, "item_not_found")
        )
        return

    name = target["name_vi"] if lang == "vi" else target["name_en"]
    add_to_cart(user.id, {"id": item_id, "name": name, "price": int(target["price"])}, qty)

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


# ==== /order Conversation ====

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

    # Tạo order_id đơn giản = số dòng hiện tại + 10001
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


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))

    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart))

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
