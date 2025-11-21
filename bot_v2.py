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

# ================== CẤU HÌNH TOKEN & ADMIN ==================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

ADMIN_CHAT_ID_RAW = os.environ.get("ADMIN_CHAT_ID", "").strip()
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW) if ADMIN_CHAT_ID_RAW else None
except ValueError:
    ADMIN_CHAT_ID = None

# ================== KẾT NỐI GOOGLE SHEET ==================

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

# ================== TRẠNG THÁI CONVERSATION ==================

PHONE, ADDRESS, CONFIRM = range(3)

# ================== BỘ NHỚ TẠM ==================

# {user_id: [{"id": str, "name": str, "price": int, "qty": int, "image_url": str}, ...]}
CARTS = {}

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
        "vi": "📌 Chọn thao tác:",
        "en": "📌 Choose an action:",
    },
    "btn_menu": {"vi": "📋 Menu", "en": "📋 Menu"},
    "btn_cart": {"vi": "🛒 Giỏ hàng", "en": "🛒 Cart"},
    "btn_order": {"vi": "📦 Đặt hàng", "en": "📦 Order"},
    "btn_help": {"vi": "❓ Hướng dẫn", "en": "❓ Help"},
    "menu_header": {"vi": "📋 MENU HÔM NAY:", "en": "📋 TODAY'S MENU:"},
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
    "cart_empty": {
        "vi": "🛒 Giỏ hàng của bạn đang trống.",
        "en": "🛒 Your cart is empty.",
    },
    "cart_header": {
        "vi": "🛒 Giỏ hàng hiện tại:",
        "en": "🛒 Your current cart:",
    },
    "cart_next_actions": {
        "vi": "Bạn có thể xem giỏ bằng /cart hoặc đặt hàng bằng /order.",
        "en": "You can check cart with /cart or place order with /order.",
    },
    "help_text": {
        "vi": (
            "🆘 Hướng dẫn đặt đồ:\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add <id> [số_lượng] - Thêm món vào giỏ (VD: /add F01 2)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n\n"
            "💡 Gợi ý: Bạn có thể xem ảnh món + ID món trong nhóm menu, "
            "sau đó dùng /add để đặt nhanh."
        ),
        "en": (
            "🆘 How to order:\n\n"
            "/start - Choose language\n"
            "/help - Show help\n"
            "/menu - Show current menu\n"
            "/add <id> [qty] - Add item to cart (Ex: /add F01 2)\n"
            "/cart - View cart\n"
            "/order - Place order by cart\n"
            "/cancel - Cancel current ordering\n\n"
            "💡 Tip: Check dish photos + IDs in the menu group, then use /add."
        ),
    },
    "order_start": {
        "vi": "📦 Bắt đầu đặt hàng. Vui lòng nhập SỐ ĐIỆN THOẠI:",
        "en": "📦 Start order. Please send your PHONE NUMBER:",
    },
    "ask_address": {
        "vi": "Vui lòng gửi ĐỊA CHỈ giao hàng:",
        "en": "Please send your DELIVERY ADDRESS:",
    },
    "order_summary_title": {
        "vi": "Xác nhận đơn:",
        "en": "Order summary:",
    },
    "order_cancelled": {
        "vi": "❌ Đã hủy đơn.",
        "en": "❌ Order cancelled.",
    },
    "order_saved": {
        "vi": "✅ Đơn của bạn đã được ghi nhận! Mã đơn: {order_id}",
        "en": "✅ Your order has been placed! Order ID: {order_id}",
    },
    "order_btn_order_hint": {
        "vi": "📦 Bấm /order để bắt đầu đặt hàng.",
        "en": "📦 Type /order to start ordering.",
    },
}


def get_default_lang() -> str:
    """Đọc SETTINGS.language_default nếu có, mặc định 'vi'."""
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key", "")).strip() == "language_default":
                value = str(row.get("value", "")).strip().lower()
                return value if value in ("vi", "en") else "vi"
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


# ================== HÀM PHỤ TRỢ ==================


def main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Inline keyboard 4 nút sau khi chọn ngôn ngữ."""
    lang = get_lang(context, user_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    MESSAGES["btn_menu"][lang], callback_data="main_menu_menu"
                ),
                InlineKeyboardButton(
                    MESSAGES["btn_cart"][lang], callback_data="main_menu_cart"
                ),
            ],
            [
                InlineKeyboardButton(
                    MESSAGES["btn_order"][lang], callback_data="main_menu_order"
                ),
                InlineKeyboardButton(
                    MESSAGES["btn_help"][lang], callback_data="main_menu_help"
                ),
            ],
        ]
    )


def load_menu():
    """Đọc toàn bộ menu từ sheet."""
    return menu_sheet.get_all_records()


def add_to_cart(user_id: int, item: dict, qty: int):
    """Thêm món vào giỏ, cộng dồn nếu trùng id."""
    cart = CARTS.get(user_id, [])
    for row in cart:
        if row["id"] == item["id"]:
            row["qty"] += qty
            break
    else:
        cart.append(item | {"qty": qty})
    CARTS[user_id] = cart


async def send_menu(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Gửi menu theo ngôn ngữ người dùng."""
    lang = get_lang(context, user_id)
    records = load_menu()

    if not records:
        await context.bot.send_message(chat_id, t(context, user_id, "empty_menu"))
        return

    lines = [t(context, user_id, "menu_header"), ""]
    for item in records:
        # Chấp nhận các tên cột linh hoạt
        status = str(item.get("status", "") or item.get("Status", "")).lower()
        if status not in ("", "active", "sold_out"):
            continue

        item_id = str(item.get("id") or item.get("ID") or "").strip()
        name_vi = item.get("name_vi") or item.get("Name_VI") or item.get("NAME_VI")
        name_en = item.get("name_en") or item.get("Name_EN") or item.get("NAME_EN")
        price = item.get("price") or item.get("Price")

        try:
            price = int(price)
        except Exception:
            continue

        name = name_vi if lang == "vi" else (name_en or name_vi or "")

        status_txt = ""
        if status == "sold_out":
            status_txt = " (hết / sold out)"

        lines.append(f"{item_id}. {name} - {price}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user_id, "add_usage"))

    await context.bot.send_message(chat_id, "\n".join(lines))


async def send_cart(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Gửi nội dung giỏ hàng."""
    cart = CARTS.get(user_id, [])
    if not cart:
        await context.bot.send_message(chat_id, t(context, user_id, "cart_empty"))
        return

    lines = [t(context, user_id, "cart_header"), ""]
    total = 0
    for row in cart:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")
    lines.append(t(context, user_id, "cart_next_actions"))

    await context.bot.send_message(chat_id, "\n".join(lines))


# ================== HANDLER LỆNH CƠ BẢN ==================


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

    # Sau khi chọn ngôn ngữ, gửi menu thao tác
    await query.message.reply_text(
        t(context, user.id, "choose_action"),
        reply_markup=main_menu_keyboard(context, user.id),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "help_text"))


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await send_menu(update.effective_chat.id, user.id, context)


async def cart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await send_cart(update.effective_chat.id, user.id, context)


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(t(context, user.id, "add_usage"))
        return

    item_code = args[0]  # ví dụ F01, F02...
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
        raw_id = str(item.get("id") or item.get("ID") or "").strip()
        if raw_id.lower() == item_code.lower():
            target = item
            break

    if not target:
        await update.message.reply_text(t(context, user.id, "item_not_found"))
        return

    name_vi = target.get("name_vi") or target.get("Name_VI") or target.get("NAME_VI")
    name_en = target.get("name_en") or target.get("Name_EN") or target.get("NAME_EN")
    price = target.get("price") or target.get("Price")
    try:
        price = int(price)
    except Exception:
        await update.message.reply_text("Lỗi dữ liệu giá trong MENU.")
        return

    name = name_vi if lang == "vi" else (name_en or name_vi or "")

    image_url = (
        target.get("image_url")
        or target.get("Image_URL")
        or target.get("IMAGE_URL")
        or ""
    )

    add_to_cart(
        user.id,
        {
            "id": str(item_code),
            "name": name,
            "price": price,
            "image_url": image_url,
        },
        qty,
    )

    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
        + "\n"
        + t(context, user.id, "cart_next_actions")
    )


# ================== NÚT MAIN MENU (INLINE) ==================


async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi bấm các nút Menu / Giỏ hàng / Đặt hàng / Hướng dẫn."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = query.message.chat_id
    data = query.data

    if data == "main_menu_menu":
        await send_menu(chat_id, user.id, context)
    elif data == "main_menu_cart":
        await send_cart(chat_id, user.id, context)
    elif data == "main_menu_help":
        await context.bot.send_message(chat_id, t(context, user.id, "help_text"))
    elif data == "main_menu_order":
        # Để đơn giản, hướng dẫn gõ /order
        await context.bot.send_message(chat_id, t(context, user.id, "order_btn_order_hint"))


# ================== /order CONVERSATION ==================


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

    text = (
        f"{t(context, user.id, 'order_summary_title')}\n"
        f"{items_text}\n"
        f"Tổng: {total}đ\n"
        f"SĐT: {phone}\n"
        f"Địa chỉ: {address}\n\n"
        f"Bạn xác nhận đặt đơn này chứ?"
    )

    # Tìm ảnh đầu tiên trong giỏ nếu có
    first_image = None
    for row in cart:
        if row.get("image_url"):
            first_image = row["image_url"]
            break

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="order_yes"),
            InlineKeyboardButton("❌ No", callback_data="order_no"),
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if first_image:
        await update.message.reply_photo(
            photo=first_image,
            caption=text,
            reply_markup=markup,
        )
    else:
        await update.message.reply_text(text, reply_markup=markup)

    return CONFIRM


async def order_confirm_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý nút Yes/No xác nhận đơn."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id

    if query.data == "order_no":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(t(context, user_id, "order_cancelled"))
        return ConversationHandler.END

    # order_yes
    cart = CARTS.get(user_id, [])
    if not cart:
        await query.message.reply_text(t(context, user_id, "cart_empty"))
        return ConversationHandler.END

    total = sum(row["price"] * row["qty"] for row in cart)
    phone = context.user_data.get("order_phone", "")
    address = context.user_data.get("order_address", "")
    lang = get_lang(context, user_id)

    # tạo order_id
    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_text = ", ".join([f"{row['qty']}x {row['name']}" for row in cart])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ghi vào sheet ORDERS
    try:
        orders_sheet.append_row(
            [
                order_id,
                user_id,
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
    except Exception as e:
        print(f"[ORDERS_APPEND_ERROR] {e}")

    # Tắt nút Yes/No trên message cũ
    await query.edit_message_reply_markup(reply_markup=None)

    # Xóa giỏ
    CARTS[user_id] = []

    # Tìm ảnh đầu tiên trong giỏ cho admin (nếu có)
    first_image = None
    for row in cart:
        if row.get("image_url"):
            first_image = row["image_url"]
            break

    # Thông báo sang nhóm Admin nếu có
    if ADMIN_CHAT_ID:
        admin_text = (
            f"🆕 ĐƠN HÀNG MỚI #{order_id}\n"
            f"Khách: {user.full_name} (id: {user_id})\n"
            f"UserName: @{user.username if user.username else 'N/A'}\n"
            f"SĐT: {phone}\n"
            f"Địa chỉ: {address}\n"
            f"Món: {items_text}\n"
            f"Tổng: {total}đ\n"
            f"Thời gian: {now_str}"
        )
        try:
            if first_image:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=first_image,
                    caption=admin_text,
                )
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_text,
                )
        except Exception as e:
            print(f"[ADMIN_NOTIFY_ERROR] {e}")

    # Báo lại cho khách
    await query.message.reply_text(
        t(context, user_id, "order_saved", order_id=order_id)
    )
    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "order_cancelled"))
    return ConversationHandler.END


# ================== MAIN ==================


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Lệnh cơ bản
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("cart", cart_cmd))
    app.add_handler(CommandHandler("add", add_cmd))

    # Nút chọn ngôn ngữ
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))

    # Nút main menu
    app.add_handler(CallbackQueryHandler(main_menu_router, pattern="^main_menu_"))

    # Conversation /order
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            CONFIRM: [
                CallbackQueryHandler(order_confirm_button, pattern="^order_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
