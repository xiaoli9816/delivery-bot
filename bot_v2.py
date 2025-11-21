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

# ================== TOKEN & GROUP ADMIN ==================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# ID nhóm Admin & Shipper (Delivery Food & Coffee – Admin & Shipper)
# CẦN ĐẶT ENV: ADMIN_CHAT_ID = -100xxxxxxxxxx (số ID của nhóm)
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

# ================== KẾT NỐI GOOGLE SHEET ==================

SHEET_NAME = "77_Delivery_System"

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
menu_sheet = client.open(SHEET_NAME).worksheet("MENU")
orders_sheet = client.open(SHEET_NAME).worksheet("ORDERS")
settings_sheet = client.open(SHEET_NAME).worksheet("SETTINGS")

# ================== BIẾN LƯU CART TRONG RAM ==================

CARTS = {}  # {user_id: [{"id": str, "name": str, "price": int, "qty": int}, ...]}

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
        "vi": "📋 Chọn thao tác:",
        "en": "📋 Choose an action:",
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
        "vi": "✅ Đã thêm vào giỏ: {qty} x {name}\nDùng /cart để xem giỏ hoặc /order để đặt hàng.",
        "en": "✅ Added to cart: {qty} x {name}\nUse /cart to view cart or /order to checkout.",
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
    "order_saved": {
        "vi": "✅ Đơn của bạn đã được ghi nhận! Mã đơn: {order_id}",
        "en": "✅ Your order has been placed! Order ID: {order_id}",
    },
    "order_cancelled": {
        "vi": "❌ Đã hủy đơn.",
        "en": "❌ Order cancelled.",
    },
    "help": {
        "vi": (
            "🆘 Hướng dẫn đặt đồ:\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add <id> [số_lượng] - Thêm món vào giỏ (VD: /add F01 2)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ (ghi đơn vào Google Sheet)\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n\n"
            "💡 Gợi ý: Trong nhóm Delivery Food & Coffee – Order Now bạn có thể gửi hình món, ghi kèm ID món. "
            "Khách chỉ cần nhắn riêng bot và dùng /menu + /add + /order."
        ),
        "en": (
            "🆘 How to order:\n\n"
            "/start - Choose language\n"
            "/help - Show this help\n"
            "/menu - Show menu\n"
            "/add <id> [qty] - Add item to cart (Ex: /add F01 2)\n"
            "/cart - View cart\n"
            "/order - Place order using cart\n"
            "/cancel - Cancel current order flow."
        ),
    },
}

PHONE, ADDRESS, CONFIRM = range(3)

# ================== HÀM NGÔN NGỮ ==================


def get_default_lang() -> str:
    """Lấy ngôn ngữ default từ sheet SETTINGS (nếu có)."""
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key", "")).strip() == "language_default":
                return str(row.get("value", "vi")).strip() or "vi"
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


# ================== KEYBOARD PHỤ TRỢ ==================


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "vi":
        buttons = [
            [
                InlineKeyboardButton("📋 Menu", callback_data="action_menu"),
                InlineKeyboardButton("🛒 Giỏ hàng", callback_data="action_cart"),
            ],
            [
                InlineKeyboardButton("📦 Đặt hàng", callback_data="action_order"),
                InlineKeyboardButton("❓ Hướng dẫn", callback_data="action_help"),
            ],
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton("📋 Menu", callback_data="action_menu"),
                InlineKeyboardButton("🛒 Cart", callback_data="action_cart"),
            ],
            [
                InlineKeyboardButton("📦 Order", callback_data="action_order"),
                InlineKeyboardButton("❓ Help", callback_data="action_help"),
            ],
        ]
    return InlineKeyboardMarkup(buttons)


# ================== /start & chọn ngôn ngữ ==================


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

    lang = get_lang(context, user.id)
    await query.message.reply_text(
        t(context, user.id, "choose_action"), reply_markup=main_menu_keyboard(lang)
    )


# ================== /help ==================


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "help"))


# ================== MENU & GIỎ HÀNG (cho lệnh) ==================


def load_menu():
    return menu_sheet.get_all_records()


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý /menu qua text command."""
    await _send_menu(update.message, update.effective_user, context)


async def cart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý /cart qua text command."""
    await _send_cart(update.message, update.effective_user, context)


async def _send_menu(target_message, user, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context, user.id)
    records = load_menu()

    if not records:
        await target_message.reply_text(t(context, user.id, "empty_menu"))
        return

    lines = [t(context, user.id, "menu_header"), ""]
    for item in records:
        status = (
            str(item.get("status") or item.get("Status") or "")
            .strip()
            .lower()
        )
        if status not in ("active", "sold_out", ""):
            continue

        item_id = item.get("ID") or item.get("id") or ""
        name_vi = item.get("Name_VI") or item.get("name_vi") or ""
        name_en = item.get("Name_EN") or item.get("name_en") or ""
        price = item.get("Price") or item.get("price") or 0

        try:
            price = int(price)
        except Exception:
            price = 0

        name = name_vi if lang == "vi" else (name_en or name_vi)
        status_txt = " (hết / sold out)" if status == "sold_out" else ""
        lines.append(f"{item_id}. {name} - {price}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user.id, "add_usage"))

    await target_message.reply_text("\n".join(lines))


async def _send_cart(target_message, user, context: ContextTypes.DEFAULT_TYPE):
    cart_data = CARTS.get(user.id, [])

    if not cart_data:
        await target_message.reply_text(t(context, user.id, "cart_empty"))
        return

    lines = [t(context, user.id, "cart_header"), ""]
    total = 0
    for row in cart_data:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")
    lines.append("Dùng /order để tiến hành đặt hàng.")

    await target_message.reply_text("\n".join(lines))


# ================== /add ==================


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(t(context, user.id, "add_usage"))
        return

    item_code = args[0].strip()
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
        item_id = str(item.get("ID") or item.get("id") or "").strip()
        if item_id.lower() == item_code.lower():
            target = item
            break

    if not target:
        await update.message.reply_text(t(context, user.id, "item_not_found"))
        return

    name_vi = target.get("Name_VI") or target.get("name_vi") or ""
    name_en = target.get("Name_EN") or target.get("name_en") or ""
    price = target.get("Price") or target.get("price") or 0
    try:
        price = int(price)
    except Exception:
        price = 0

    name = name_vi if lang == "vi" else (name_en or name_vi)
    _add_to_cart(
        user.id,
        {"id": item_code, "name": name, "price": price},
        qty,
    )

    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
    )


def _add_to_cart(user_id: int, item: dict, qty: int):
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


# ================== ĐẶT HÀNG (Conversation) ==================


async def _order_start_common(target_message, user, context: ContextTypes.DEFAULT_TYPE):
    cart_data = CARTS.get(user.id, [])
    if not cart_data:
        await target_message.reply_text(t(context, user.id, "cart_empty"))
        return ConversationHandler.END

    await target_message.reply_text(t(context, user.id, "order_start"))
    return PHONE


async def order_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    return await _order_start_common(update.message, user, context)


async def order_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    return await _order_start_common(query.message, user, context)


async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["order_phone"] = update.message.text.strip()
    await update.message.reply_text(t(context, user.id, "ask_address"))
    return ADDRESS


async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["order_address"] = update.message.text.strip()

    cart_data = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart_data)
    lines = []
    for row in cart_data:
        lines.append(f"{row['qty']} x {row['name']} = {row['price'] * row['qty']}đ")

    items_text = "\n".join(lines)
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]

    context.user_data["pending_order"] = {
        "cart": cart_data,
        "total": total,
        "phone": phone,
        "address": address,
    }

    txt = (
        f"Xác nhận đơn:\n{items_text}\n"
        f"Tổng: {total}đ\n"
        f"SĐT: {phone}\n"
        f"Địa chỉ: {address}\n\n"
        f"Bạn xác nhận đặt đơn này chứ?"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="order_yes"),
            InlineKeyboardButton("❌ No", callback_data="order_no"),
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(txt, reply_markup=markup)
    return CONFIRM


async def order_confirm_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    choice = query.data

    pending = context.user_data.pop("pending_order", None)

    # Xóa nút YES/NO
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not pending:
        await query.message.reply_text(
            "❌ Không tìm thấy dữ liệu đơn hàng. Vui lòng /order lại."
        )
        return ConversationHandler.END

    if choice == "order_no":
        CARTS[user.id] = []
        await query.message.reply_text(t(context, user.id, "order_cancelled"))
        return ConversationHandler.END

    # YES -> ghi đơn
    cart_data = pending["cart"]
    total = pending["total"]
    phone = pending["phone"]
    address = pending["address"]
    lang = get_lang(context, user.id)

    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_text = ", ".join([f"{row['qty']}x {row['name']}" for row in cart_data])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            now,
            "pending",
        ]
    )

    CARTS[user.id] = []

    await query.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )

    # Gửi về nhóm Admin & Shipper
    if ADMIN_CHAT_ID != 0:
        admin_msg = (
            f"📦 ĐƠN HÀNG MỚI #{order_id}\n"
            f"👤 Khách: {user.full_name}\n"
            f"🆔 ID: {user.id}\n"
            f"📞 SĐT: {phone}\n"
            f"📍 Địa chỉ: {address}\n"
            f"🍱 Món: {items_text}\n"
            f"💰 Tổng: {total}đ\n"
            f"⏰ Thời gian: {now}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg)
        except Exception as e:
            print("Lỗi gửi group admin:", e)
    else:
        print("ADMIN_CHAT_ID = 0, không gửi được về nhóm admin")

    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "order_cancelled"))
    return ConversationHandler.END


# ================== XỬ LÝ NÚT MENU CHÍNH ==================


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút: Menu / Cart / Help (order xử lý riêng trong Conversation)."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data
    lang = get_lang(context, user.id)

    if data == "action_menu":
        await _send_menu(query.message, user, context)
    elif data == "action_cart":
        await _send_cart(query.message, user, context)
    elif data == "action_help":
        await query.message.reply_text(t(context, user.id, "help"))

    # Gợi ý thao tác tiếp
    await query.message.reply_text(
        t(context, user.id, "choose_action"), reply_markup=main_menu_keyboard(lang)
    )


# ================== main() ==================


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Lệnh cơ bản
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart_cmd))

    # Chọn ngôn ngữ
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))

    # Nút Menu / Cart / Help (KHÔNG gồm order)
    app.add_handler(
        CallbackQueryHandler(main_menu_callback, pattern="^action_(menu|cart|help)$")
    )

    # Conversation /order
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("order", order_start_cmd),
            CallbackQueryHandler(order_start_button, pattern="^action_order$"),
        ],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            CONFIRM: [
                CallbackQueryHandler(
                    order_confirm_button, pattern="^order_(yes|no)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
