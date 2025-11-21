from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
from datetime import datetime

# ================== TOKEN & ENV ==================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# Chat ID của nhóm admin (Delivery Food & Coffee – Admin & Shipper)
# Lấy ID nhóm rồi set ADMIN_CHAT_ID trong Railway
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

# ================== GOOGLE SHEETS ==================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope
    )

client = gspread.authorize(creds)

SHEET_NAME = "77_Delivery_System"
menu_sheet = client.open(SHEET_NAME).worksheet("MENU")
orders_sheet = client.open(SHEET_NAME).worksheet("ORDERS")
settings_sheet = client.open(SHEET_NAME).worksheet("SETTINGS")

# ================== CART & STATE ==================

CARTS = {}  # {user_id: [{"id": str, "name": str, "price": int, "qty": int}, ...]}

PHONE, ADDRESS, CONFIRM = range(3)

# ================== ĐA NGÔN NGỮ ==================

MESSAGES = {
    "welcome": {
        "vi": "Xin chào! Vui lòng chọn ngôn ngữ / Please choose language:",
        "en": "Hello! Please choose your language:",
    },
    "lang_set_vi": {
        "vi": "✅ Bạn đã chọn Tiếng Việt.",
        "en": "✅ You switched to Vietnamese.",
    },
    "lang_set_en": {
        "vi": "✅ Bạn đã chuyển sang English.",
        "en": "✅ You switched to English.",
    },
    "choose_action": {
        "vi": "👉 Chọn thao tác:",
        "en": "👉 Choose an action:",
    },
    "menu_header": {
        "vi": "📋 MENU HÔM NAY:",
        "en": "📋 TODAY'S MENU:",
    },
    "empty_menu": {
        "vi": "Hiện chưa có món nào trong menu.",
        "en": "No items in the menu yet.",
    },
    "add_usage": {
        "vi": "Cách dùng: /add <id_món> [số_lượng]. Ví dụ: /add F01 2",
        "en": "Usage: /add <item_id> [qty]. Example: /add F01 2",
    },
    "item_not_found": {
        "vi": "❌ Không tìm thấy món với ID đó.",
        "en": "❌ Item not found with that ID.",
    },
    "added_to_cart": {
        "vi": "✅ Đã thêm vào giỏ: {qty} x {name}",
        "en": "✅ Added to cart: {qty} x {name}",
    },
    "after_add_hint": {
        "vi": "\n\nBạn có thể xem giỏ bằng /cart hoặc đặt hàng bằng /order.",
        "en": "\n\nYou can view your cart with /cart or place an order with /order.",
    },
    "cart_empty": {
        "vi": "🛒 Giỏ hàng của bạn đang trống.",
        "en": "🛒 Your cart is empty.",
    },
    "cart_header": {
        "vi": "🛒 Giỏ hàng hiện tại:",
        "en": "🛒 Your current cart:",
    },
    "order_start": {
        "vi": "📦 Bắt đầu đặt hàng. Vui lòng nhập SỐ ĐIỆN THOẠI:",
        "en": "📦 Start order. Please send your PHONE NUMBER:",
    },
    "ask_address": {
        "vi": "Vui lòng gửi ĐỊA CHỈ giao hàng:",
        "en": "Please send your DELIVERY ADDRESS:",
    },
    "order_summary": {
        "vi": "Xác nhận đơn:\n{items}\nTổng: {total}đ\nSĐT: {phone}\nĐịa chỉ: {address}",
        "en": "Order summary:\n{items}\nTotal: {total} VND\nPhone: {phone}\nAddress: {address}",
    },
    "order_ask_confirm": {
        "vi": "\n\nBạn xác nhận đặt đơn này chứ?",
        "en": "\n\nDo you confirm this order?",
    },
    "order_saved": {
        "vi": "✅ Đơn của bạn đã được ghi nhận! Mã đơn: {order_id}",
        "en": "✅ Your order has been placed! Order ID: {order_id}",
    },
    "order_cancelled": {
        "vi": "❌ Đã hủy đơn.",
        "en": "❌ Order cancelled.",
    },
    "help_text": {
        "vi": (
            "🆘 Hướng dẫn đặt đồ:\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add <id> [số_lượng] - Thêm món vào giỏ (VD: /add F01 2)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ hiện tại\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n"
        ),
        "en": (
            "🆘 Order guide:\n\n"
            "/start - Choose language\n"
            "/help - Show help\n"
            "/menu - Show current menu\n"
            "/add <id> [qty] - Add item to cart (ex: /add F01 2)\n"
            "/cart - View cart\n"
            "/order - Place order from current cart\n"
            "/cancel - Cancel current order flow\n"
        ),
    },
    "order_button_hint": {
        "vi": "🧾 Bắt đầu đặt hàng bằng lệnh /order.",
        "en": "🧾 Start ordering with command /order.",
    },
}

# ================== HÀM ĐA NGÔN NGỮ ==================


def get_default_lang() -> str:
    """Đọc ngôn ngữ mặc định từ sheet SETTINGS (key, value)."""
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key")).strip() == "language_default":
                val = str(row.get("value")).strip().lower()
                return "en" if val == "en" else "vi"
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


# ================== HỖ TRỢ MENU CHÍNH ==================


def build_main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "vi":
        menu_text = "📋 Menu"
        cart_text = "🛒 Giỏ hàng"
        order_text = "📦 Đặt hàng"
        help_text = "❓ Hướng dẫn"
    else:
        menu_text = "📋 Menu"
        cart_text = "🛒 Cart"
        order_text = "📦 Order"
        help_text = "❓ Help"

    keyboard = [
        [
            InlineKeyboardButton(menu_text, callback_data="action_menu"),
            InlineKeyboardButton(cart_text, callback_data="action_cart"),
        ],
        [
            InlineKeyboardButton(order_text, callback_data="action_order_hint"),
            InlineKeyboardButton(help_text, callback_data="action_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_main_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    lang = get_lang(context, user_id)
    await message.reply_text(
        t(context, user_id, "choose_action"),
        reply_markup=build_main_menu_keyboard(lang),
    )


# ================== ĐỌC MENU TỪ GOOGLE SHEET ==================


def load_menu():
    """Đọc toàn bộ menu từ sheet và chuẩn hóa tên cột."""
    raw_records = menu_sheet.get_all_records()
    menu = []

    for row in raw_records:
        # ID có thể là 'id' hoặc 'ID'
        item_id = row.get("id") or row.get("ID") or row.get("Id")

        # Tên món 2 ngôn ngữ
        name_vi = row.get("name_vi") or row.get("Name_VI") or row.get("Tên_VI")
        name_en = row.get("name_en") or row.get("Name_EN") or row.get("Tên_EN")

        # Giá
        price = row.get("price") or row.get("Price")

        # Trạng thái
        status = row.get("status") or row.get("Status") or "active"
        status = str(status).strip().lower()

        if not item_id or not name_vi or not price:
            continue  # hàng thiếu dữ liệu thì bỏ

        # Chỉ lấy món active / sold_out
        if status not in ("active", "sold_out"):
            continue

        menu.append(
            {
                "id": str(item_id),
                "name_vi": str(name_vi),
                "name_en": str(name_en or name_vi),
                "price": int(price),
                "status": status,
            }
        )

    return menu


# ================== CÁC HÀM GỬI NỘI DUNG CHUNG ==================


async def send_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    lang = get_lang(context, user_id)
    records = load_menu()

    if not records:
        await message.reply_text(t(context, user_id, "empty_menu"))
        return

    lines = [t(context, user_id, "menu_header"), ""]
    for item in records:
        name = item["name_vi"] if lang == "vi" else item["name_en"]
        status_txt = ""
        if item["status"] == "sold_out":
            status_txt = " (hết / sold out)"
        lines.append(f"{item['id']}. {name} - {item['price']}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user_id, "add_usage"))

    await message.reply_text("\n".join(lines))


async def send_cart(message, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    cart = CARTS.get(user_id, [])

    if not cart:
        await message.reply_text(t(context, user_id, "cart_empty"))
        return

    lines = [t(context, user_id, "cart_header"), ""]
    total = 0
    for row in cart:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")

    await message.reply_text("\n".join(lines))


async def send_help(message, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    await message.reply_text(t(context, user_id, "help_text"))


# ================== HANDLER: /start & CHỌN NGÔN NGỮ ==================


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
        t(context, user.id, "welcome"), reply_markup=reply_markup
    )


async def lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "lang_vi":
        context.user_data["lang"] = "vi"
        await query.edit_message_text(t(context, user.id, "lang_set_vi"))
    elif query.data == "lang_en":
        context.user_data["lang"] = "en"
        await query.edit_message_text(t(context, user.id, "lang_set_en"))

    # Gửi menu chính sau khi chọn ngôn ngữ
    await show_main_menu(query.message, context, user.id)


# ================== HANDLER: MENU CHÍNH (INLINE BUTTONS) ==================


async def main_menu_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "action_menu":
        await send_menu(query.message, context, user.id)
    elif data == "action_cart":
        await send_cart(query.message, context, user.id)
    elif data == "action_help":
        await send_help(query.message, context, user.id)
    elif data == "action_order_hint":
        # chỉ hướng dẫn dùng /order để bắt đầu
        await query.message.reply_text(t(context, user.id, "order_button_hint"))


# ================== HANDLER: /menu /cart /help ==================


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await send_menu(update.message, context, user.id)


async def cart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await send_cart(update.message, context, user.id)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await send_help(update.message, context, user.id)


# ================== CART ==================


def add_to_cart(user_id: int, item: dict, qty: int):
    cart = CARTS.get(user_id, [])
    for row in cart:
        if row["id"] == item["id"]:
            row["qty"] += qty
            break
    else:
        cart.append(
            {
                "id": item["id"],
                "name": item["name"],
                "price": item["price"],
                "qty": qty,
            }
        )
    CARTS[user_id] = cart


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(t(context, user.id, "add_usage"))
        return

    # ID món: có thể là '1' hoặc 'F03' → giữ nguyên dạng chuỗi
    item_id = args[0].strip()

    qty = 1
    if len(args) >= 2:
        try:
            qty = int(args[1])
        except ValueError:
            qty = 1

    lang = get_lang(context, user.id)
    records = load_menu()

    target = None    # tìm món theo id (so sánh không phân biệt hoa thường)
    for item in records:
        if str(item["id"]).lower() == item_id.lower():
            target = item
            break

    if not target:
        await update.message.reply_text(t(context, user.id, "item_not_found"))
        return

    name = target["name_vi"] if lang == "vi" else target["name_en"]
    add_to_cart(
        user.id,
        {"id": target["id"], "name": name, "price": target["price"]},
        qty,
    )

    msg = t(context, user.id, "added_to_cart", qty=qty, name=name)
    msg += t(context, user.id, "after_add_hint")
    await update.message.reply_text(msg)


# ================== ORDER CONVERSATION ==================


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cart = CARTS.get(user.id, [])
    if not cart:
        await update.message.reply_text(t(context, user.id, "cart_empty"))
        return ConversationHandler.END

    await update.message.reply_text(t(context, user.id, "order_start"))
    return PHONE


async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["order_phone"] = update.message.text.strip()
    await update.message.reply_text(t(context, user.id, "ask_address"))
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

    summary = t(
        context,
        user.id,
        "order_summary",
        items=items_text,
        total=total,
        phone=phone,
        address=address,
    ) + t(context, user.id, "order_ask_confirm")

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="order_confirm_yes"),
            InlineKeyboardButton("❌ No", callback_data="order_confirm_no"),
        ]
    ]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM


async def order_confirm_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "order_confirm_no":
        await query.message.reply_text(t(context, user.id, "order_cancelled"))
        return ConversationHandler.END

    # Nếu chọn YES
    cart = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart)
    phone = context.user_data.get("order_phone", "")
    address = context.user_data.get("order_address", "")
    lang = get_lang(context, user.id)

    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_text = ", ".join([f"{row['qty']}x {row['name']}" for row in cart])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Ghi vào sheet ORDERS
    orders_sheet.append_row(
        [
            order_id,
            user.id,
            user.username or "",
            phone,
            items_text,
            total,
            address,
            lang,
            now_str,
            "pending",
        ]
    )

    # Xóa cart
    CARTS[user.id] = []

    # Thông báo cho người dùng
    await query.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )

    # Thông báo cho nhóm admin (nếu có)
    if ADMIN_CHAT_ID:
        try:
            admin_text = (
                f"🆕 New order #{order_id}\n"
                f"User: {user.full_name} (@{user.username}) / {user.id}\n"
                f"Phone: {phone}\n"
                f"Address: {address}\n"
                f"Items: {items_text}\n"
                f"Total: {total}đ\n"
                f"Time: {now_str}"
            )
            await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_text)
        except Exception:
            pass

    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "order_cancelled"))
    return ConversationHandler.END


# ================== MAIN ==================


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Ngôn ngữ & menu chính
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(main_menu_actions, pattern="^action_"))

    # Lệnh cơ bản
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("cart", cart_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add_cmd))

    # Conversation /order
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            CONFIRM: [
                CallbackQueryHandler(order_confirm_button, pattern="^order_confirm_")
            ],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
