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
from datetime import datetime
import os
import json

# ================== CẤU HÌNH TOKEN & GOOGLE SHEET ==================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# Nhóm admin / shipper (tùy chọn)
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # ví dụ: "-1001234567890"

# Kết nối Google Sheet bằng Service Account
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
else:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", SCOPE
    )

client = gspread.authorize(CREDS)

SHEET_NAME = "77_Delivery_System"
menu_sheet = client.open(SHEET_NAME).worksheet("MENU")
orders_sheet = client.open(SHEET_NAME).worksheet("ORDERS")
settings_sheet = client.open(SHEET_NAME).worksheet("SETTINGS")

# ================== TRẠNG THÁI VÀ ĐA NGÔN NGỮ ==================

# Cart trong RAM: {user_id: [{id, name, price, qty}, ...]}
CARTS: dict[int, list[dict]] = {}

# Các state cho ConversationHandler
PHONE, ADDRESS, CONFIRM = range(3)

# Bảng message đa ngôn ngữ
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
    "buttons_main_caption": {
        "vi": "➡️ Chọn thao tác:",
        "en": "➡️ Please choose an action:",
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
        "vi": "Cách dùng: /add <id_món> [số_lượng]. Ví dụ: /add 1 2",
        "en": "Usage: /add <item_id> [qty]. Example: /add 1 2",
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
        "vi": "Bạn có thể xem giỏ bằng /cart hoặc bấm nút bên dưới để tiếp tục.",
        "en": "You can view your cart with /cart or use the buttons below to continue.",
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
        "vi": "Xác nhận đơn:\n{items}\nTổng: {total}đ\nSĐT: {phone}\nĐịa chỉ: {address}\n\nVui lòng chọn:",
        "en": "Order summary:\n{items}\nTotal: {total} VND\nPhone: {phone}\nAddress: {address}\n\nPlease choose:",
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
            "🆘 *Hướng dẫn đặt đồ:*\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add <id> [số_lượng] - Thêm món vào giỏ (VD: /add 1 2)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n\n"
            "💡 Bạn cũng có thể dùng các nút bên dưới để thao tác nhanh."
        ),
        "en": (
            "🆘 *How to order:*\n\n"
            "/start - Choose language\n"
            "/help - Show help\n"
            "/menu - Show current menu\n"
            "/add <id> [qty] - Add item to cart (Ex: /add 1 2)\n"
            "/cart - View cart\n"
            "/order - Place order from cart\n"
            "/cancel - Cancel current ordering flow\n\n"
            "💡 You can also use the buttons below for quick actions."
        ),
    },
}


def get_default_lang() -> str:
    """Đọc ngôn ngữ mặc định từ sheet SETTINGS (key=language_default)."""
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key", "")).strip() == "language_default":
                val = str(row.get("value", "")).strip().lower()
                if val in ("vi", "en"):
                    return val
    except Exception:
        pass
    return "vi"


def get_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    lang = context.user_data.get("lang")
    if lang not in ("vi", "en"):
        lang = get_default_lang()
        context.user_data["lang"] = lang
    return lang


def t(context: ContextTypes.DEFAULT_TYPE, user_id: int, key: str, **kwargs) -> str:
    lang = get_lang(context, user_id)
    text = MESSAGES.get(key, {}).get(lang, "")
    if kwargs:
        text = text.format(**kwargs)
    return text


# ================== INLINE KEYBOARDS ==================


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Menu chính: Menu / Cart / Order / Help."""
    if lang == "vi":
        txt_menu = "📋 Menu"
        txt_cart = "🛒 Giỏ hàng"
        txt_order = "📦 Đặt hàng"
        txt_help = "❓ Hướng dẫn"
    else:
        txt_menu = "📋 Menu"
        txt_cart = "🛒 Cart"
        txt_order = "📦 Order"
        txt_help = "❓ Help"

    keyboard = [
        [
            InlineKeyboardButton(txt_menu, callback_data="main_menu"),
            InlineKeyboardButton(txt_cart, callback_data="main_cart"),
        ],
        [
            InlineKeyboardButton(txt_order, callback_data="order_start"),
            InlineKeyboardButton(txt_help, callback_data="main_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)
    caption = t(context, user.id, "buttons_main_caption")
    await update.effective_message.reply_text(
        caption, reply_markup=main_menu_keyboard(lang)
    )


# ================== HANDLER /start + chọn ngôn ngữ ==================


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
        text = t(context, user.id, "lang_set_vi")
    else:
        context.user_data["lang"] = "en"
        text = t(context, user.id, "lang_set_en")

    # Thông báo đổi ngôn ngữ
    await query.edit_message_text(text)
    # Gửi menu chính
    await query.message.reply_text(
        t(context, user.id, "buttons_main_caption"),
        reply_markup=main_menu_keyboard(get_lang(context, user.id)),
    )


# ================== HÀM ĐỌC MENU VÀ GIỎ ==================


def load_menu():
    """Đọc toàn bộ menu từ sheet MENU."""
    return menu_sheet.get_all_records()


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)
    records = load_menu()

    if not records:
        await update.effective_message.reply_text(
            t(context, user.id, "empty_menu")
        )
        return

    lines = [t(context, user.id, "menu_header"), ""]
    for item in records:
        # lọc status
        status_val = str(item.get("status", "")).lower()
        if status_val not in ("active", "sold_out", ""):
            continue

        # cột id, name_vi, name_en, price phải khớp với header trong sheet
        try:
            item_id = str(item["id"])
            price = int(item["price"])
        except Exception:
            # nếu không đúng format thì bỏ qua
            continue

        name = item["name_vi"] if lang == "vi" else item["name_en"]
        status_txt = " (hết / sold out)" if status_val == "sold_out" else ""
        lines.append(f"{item_id}. {name} - {price}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user.id, "add_usage"))

    await update.effective_message.reply_text("\n".join(lines))


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
        await update.effective_message.reply_text(
            t(context, user.id, "add_usage")
        )
        return

    try:
        item_id = int(args[0])
    except ValueError:
        await update.effective_message.reply_text(
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
        try:
            if int(item["id"]) == item_id:
                target = item
                break
        except Exception:
            continue

    if not target:
        await update.effective_message.reply_text(
            t(context, user.id, "item_not_found")
        )
        return

    name = target["name_vi"] if lang == "vi" else target["name_en"]
    price = int(target["price"])
    add_to_cart(user.id, {"id": item_id, "name": name, "price": price}, qty)

    text = t(context, user.id, "added_to_cart", qty=qty, name=name)
    text += "\n" + t(context, user.id, "after_add_hint")

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛒 Giỏ hàng", callback_data="main_cart"),
                InlineKeyboardButton("📦 Đặt hàng", callback_data="order_start"),
            ],
            [InlineKeyboardButton("📋 Menu", callback_data="main_menu")],
        ]
    )

    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cart_items = CARTS.get(user.id, [])

    if not cart_items:
        await update.effective_message.reply_text(
            t(context, user.id, "cart_empty")
        )
        return

    lines = [t(context, user.id, "cart_header"), ""]
    total = 0
    for row in cart_items:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📦 Đặt hàng", callback_data="order_start"),
                InlineKeyboardButton("📋 Menu", callback_data="main_menu"),
            ]
        ]
    )

    await update.effective_message.reply_text(
        "\n".join(lines), reply_markup=keyboard
    )


# ================== LUỒNG ĐẶT HÀNG (ConversationHandler) ==================


async def order_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry bằng lệnh /order."""
    user = update.effective_user
    cart_items = CARTS.get(user.id, [])
    if not cart_items:
        await update.effective_message.reply_text(
            t(context, user.id, "cart_empty")
        )
        return ConversationHandler.END

    await update.effective_message.reply_text(
        t(context, user.id, "order_start")
    )
    return PHONE


async def order_start_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry khi bấm nút Đặt hàng."""
    user = update.effective_user
    cart_items = CARTS.get(user.id, [])
    if not cart_items:
        await update.effective_message.reply_text(
            t(context, user.id, "cart_empty")
        )
        return ConversationHandler.END

    await update.effective_message.reply_text(
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

    cart_items = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart_items)
    lines = []
    for row in cart_items:
        lines.append(f"{row['qty']} x {row['name']} = {row['price'] * row['qty']}đ")
    items_text = "\n".join(lines)

    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]

    # Nút xác nhận YES / NO
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data="order_yes"),
                InlineKeyboardButton("❌ No", callback_data="order_no"),
            ]
        ]
    )

    await update.message.reply_text(
        t(
            context,
            user.id,
            "order_summary",
            items=items_text,
            total=total,
            phone=phone,
            address=address,
        ),
        reply_markup=keyboard,
    )
    return CONFIRM


async def order_confirm_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data  # order_yes hoặc order_no

    if data == "order_no":
        await query.message.reply_text(
            t(context, user.id, "order_cancelled")
        )
        return ConversationHandler.END

    # == YES: lưu đơn ==
    cart_items = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart_items)
    phone = context.user_data.get("order_phone", "")
    address = context.user_data.get("order_address", "")
    lang = get_lang(context, user.id)

    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_plain = ", ".join(
        [f"{row['qty']}x {row['name']}" for row in cart_items]
    )
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Ghi vào sheet
    orders_sheet.append_row(
        [
            order_id,
            user.id,
            user.username or "",
            phone,
            items_plain,
            total,
            address,
            lang,
            now_str,
            "pending",
        ]
    )

    # Gửi sang nhóm admin (nếu có)
    if ADMIN_CHAT_ID:
        admin_text = (
            f"🆕 *New Order* #{order_id}\n"
            f"👤 User: {user.full_name} (id={user.id}, @{user.username})\n"
            f"📞 Phone: {phone}\n"
            f"📍 Address: {address}\n"
            f"🧺 Items:\n{items_plain}\n"
            f"💰 Total: {total}đ\n"
            f"⏰ Time: {now_str}\n"
            f"🌐 Lang: {lang}\n"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_text,
                parse_mode="Markdown",
            )
        except Exception:
            pass

    # Xóa cart
    CARTS[user.id] = []

    await query.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )
    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.effective_message.reply_text(
        t(context, user.id, "order_cancelled")
    )
    return ConversationHandler.END


# ================== MAIN MENU CALLBACK (Menu / Cart / Help) ==================


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút main_menu, main_cart, main_help (KHÔNG bao gồm order_start)."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await menu(update, context)
    elif data == "main_cart":
        await cart(update, context)
    elif data == "main_help":
        await help_cmd(update, context)


# ================== /help ==================


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = t(context, user.id, "help_text")
    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard(get_lang(context, user.id))
    )


# ================== MAIN ==================


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /start + chọn ngôn ngữ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lang_button, pattern=r"^lang_"))

    # Menu chính (Menu / Cart / Help)
    app.add_handler(
        CallbackQueryHandler(main_menu_handler, pattern=r"^main_")
    )

    # Lệnh cơ bản
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart))
    app.add_handler(CommandHandler("help", help_cmd))

    # Conversation đặt hàng
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("order", order_start_cmd),
            CallbackQueryHandler(order_start_from_button, pattern=r"^order_start$"),
        ],
        states={
            PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, order_phone
                )
            ],
            ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, order_address
                )
            ],
            CONFIRM: [
                CallbackQueryHandler(
                    order_confirm_btn, pattern=r"^order_(yes|no)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
        per_chat=True,
        per_user=True,
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
