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

# ==== TOKEN TELEGRAM ====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# ==== KẾT NỐI GOOGLE SHEET ====
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
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

# ==== NHÓM ADMIN (GỬI THÔNG BÁO ĐƠN) ====
ORDER_NOTIFY_CHAT_ID = os.environ.get("ORDER_NOTIFY_CHAT_ID")  # vd: -1001234567890

# ==== GIỎ HÀNG TRÊN RAM ====
CARTS = {}  # {user_id: [ {id, name, price, qty}, ... ]}

# ==== ĐA NGÔN NGỮ ====
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
    "main_menu_title": {
        "vi": "Bạn muốn làm gì tiếp theo?",
        "en": "What would you like to do next?",
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
        "vi": (
            "Xác nhận đơn:\n{items}\nTổng: {total}đ\nSĐT: {phone}\nĐịa chỉ: {address}"
            "\n\nGõ 'yes' để xác nhận, 'no' để hủy."
        ),
        "en": (
            "Order summary:\n{items}\nTotal: {total} VND\nPhone: {phone}\nAddress: {address}"
            "\n\nType 'yes' to confirm, 'no' to cancel."
        ),
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
            "🆘 *Hướng dẫn đặt đồ:*\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add <id> [số_lượng] - Thêm món vào giỏ (VD: /add F01 2)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n"
        ),
        "en": (
            "🆘 *How to order:*\n\n"
            "/start - Choose language\n"
            "/help - Show this help\n"
            "/menu - Show current menu\n"
            "/add <id> [qty] - Add item to cart (e.g.: /add F01 2)\n"
            "/cart - View your cart\n"
            "/order - Place order from cart\n"
            "/cancel - Cancel current order\n"
        ),
    },
    "after_add_hint": {
        "vi": "Bạn có thể xem giỏ bằng /cart hoặc đặt hàng bằng /order.",
        "en": "You can view your cart with /cart or place order with /order.",
    },
}

PHONE, ADDRESS, CONFIRM = range(3)


def get_default_lang() -> str:
    """Đọc SETTINGS để lấy ngôn ngữ mặc định."""
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key", "")).lower() == "language_default":
                return row.get("value", "vi")
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


# --------- MAIN MENU (INLINE KEYBOARD) ----------


def build_main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "vi":
        btn_menu = "📋 Menu"
        btn_cart = "🛒 Giỏ hàng"
        btn_order = "📦 Đặt hàng"
        btn_help = "❓ Hướng dẫn"
    else:
        btn_menu = "📋 Menu"
        btn_cart = "🛒 Cart"
        btn_order = "📦 Order"
        btn_help = "❓ Help"

    keyboard = [
        [
            InlineKeyboardButton(btn_menu, callback_data="mm_menu"),
            InlineKeyboardButton(btn_cart, callback_data="mm_cart"),
        ],
        [
            InlineKeyboardButton(btn_order, callback_data="mm_order"),
            InlineKeyboardButton(btn_help, callback_data="mm_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_main_menu(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context, user_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=t(context, user_id, "main_menu_title"),
        reply_markup=build_main_menu_keyboard(lang),
    )


# ------------ HANDLERS CƠ BẢN --------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu: cho chọn ngôn ngữ."""
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
        reply_markup=reply_markup,
    )


async def lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi bấm chọn ngôn ngữ."""
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "lang_vi":
        context.user_data["lang"] = "vi"
        await query.edit_message_text(t(context, user.id, "lang_set_vi"))
    elif query.data == "lang_en":
        context.user_data["lang"] = "en"
        await query.edit_message_text(t(context, user.id, "lang_set_en"))

    # Sau khi chọn ngôn ngữ xong -> hiện menu chính
    await send_main_menu(query.message.chat_id, user.id, context)


def load_menu():
    """Đọc toàn bộ menu từ sheet."""
    return menu_sheet.get_all_records()


async def show_menu(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context, user_id)
    records = load_menu()

    if not records:
        await context.bot.send_message(
            chat_id=chat_id,
            text=t(context, user_id, "empty_menu"),
        )
        return

    lines = [t(context, user_id, "menu_header"), ""]
    for item in records:
        # các key phụ thuộc header trong sheet của bạn (id, name_vi, ...)
        status = str(item.get("status", "active")).lower()
        if status not in ("active", "sold_out"):
            continue

        try:
            item_id = item["id"]
        except KeyError:
            # nếu header viết hoa, thử ID
            item_id = item.get("ID", "")

        name = item.get("name_vi") if lang == "vi" else item.get("name_en")
        price = item.get("price")
        status_txt = " (hết / sold out)" if status == "sold_out" else ""
        lines.append(f"{item_id}. {name} - {price}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user_id, "add_usage"))

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /menu."""
    user = update.effective_user
    await show_menu(update.effective_chat.id, user.id, context)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_markdown(
        t(context, user.id, "help")
    )


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


def find_image_url(item: dict) -> str | None:
    """Tìm cột chứa link ảnh (ImageUrl / image / img...)."""
    for key in item.keys():
        if key.lower() in ("imageurl", "image_url", "image", "img", "photo"):
            url = str(item.get(key)).strip()
            if url:
                return url
    return None


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add <id> [qty]"""
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(t(context, user.id, "add_usage"))
        return

    item_code = args[0]  # VD: F01, F02...
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
        # so sánh theo text ID (F01, F02...)
        _id = str(item.get("id") or item.get("ID", "")).strip()
        if _id.lower() == item_code.lower():
            target = item
            break

    if not target:
        await update.message.reply_text(t(context, user.id, "item_not_found"))
        return

    name = target.get("name_vi") if lang == "vi" else target.get("name_en")
    price = int(target.get("price", 0))

    add_to_cart(user.id, {"id": item_code, "name": name, "price": price}, qty)

    # Thông báo đã thêm
    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
    )

    # Gửi ảnh món nếu có
    img_url = find_image_url(target)
    if img_url:
        try:
            await update.message.reply_photo(
                photo=img_url,
                caption=f"{name} - {price}đ",
            )
        except Exception:
            # nếu link lỗi thì bỏ qua, không crash bot
            pass

    # Gợi ý bước tiếp theo + nút
    await update.message.reply_text(
        t(context, user.id, "after_add_hint"),
        reply_markup=build_main_menu_keyboard(lang),
    )


async def show_cart_text(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    cart = CARTS.get(user_id, [])
    if not cart:
        return ""

    lines = [t(context, user_id, "cart_header"), ""]
    total = 0
    for row in cart:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")
    return "\n".join(lines)


async def cart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    txt = await show_cart_text(user.id, context)
    if not txt:
        await update.message.reply_text(t(context, user.id, "cart_empty"))
    else:
        await update.message.reply_text(txt)


# ==== /order Conversation ====


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point cho /order hoặc nút mm_order."""
    user = update.effective_user

    # Xác định nơi để reply (command hay callback)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        send = query.message.reply_text
    else:
        chat_id = update.effective_chat.id
        send = update.message.reply_text

    cart = CARTS.get(user.id, [])
    if not cart:
        await send(t(context, user.id, "cart_empty"))
        return ConversationHandler.END

    await send(t(context, user.id, "order_start"))
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
    lines = [
        f"{row['qty']} x {row['name']} = {row['price'] * row['qty']}đ"
        for row in cart
    ]
    items_text = "\n".join(lines)
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]

    await update.message.reply_text(
        t(
            context,
            user.id,
            "order_summary",
            items=items_text,
            total=total,
            phone=phone,
            address=address,
        )
    )
    return CONFIRM


async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()
    if text not in ["yes", "y", "có", "ok", "đồng ý"]:
        await update.message.reply_text(t(context, user.id, "order_cancelled"))
        return ConversationHandler.END

    cart = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart)
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]
    lang = get_lang(context, user.id)

    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_text = ", ".join(
        [f"{row['qty']}x {row['name']}" for row in cart]
    )
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

    # Xóa giỏ
    CARTS[user.id] = []

    # Thông báo cho khách
    await update.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )

    # Gửi thông báo sang nhóm Admin (nếu cấu hình)
    if ORDER_NOTIFY_CHAT_ID:
        msg = (
            f"🆕 Đơn hàng mới: #{order_id}\n"
            f"Khách: {user.full_name} (@{user.username})\n"
            f"SĐT: {phone}\n"
            f"Địa chỉ: {address}\n"
            f"Món: {items_text}\n"
            f"Tổng: {total}đ\n"
            f"Ngôn ngữ: {lang}\n"
            f"Thời gian: {now_str}"
        )
        try:
            await context.bot.send_message(
                chat_id=int(ORDER_NOTIFY_CHAT_ID), text=msg
            )
        except Exception as e:
            print("Notify admin error:", e)

    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "order_cancelled"))
    return ConversationHandler.END


# --------- XỬ LÝ NÚT MAIN MENU (INLINE) ----------


async def main_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = query.message.chat_id

    if query.data == "mm_menu":
        await show_menu(chat_id, user.id, context)

    elif query.data == "mm_cart":
        txt = await show_cart_text(user.id, context)
        if not txt:
            await query.message.reply_text(t(context, user.id, "cart_empty"))
        else:
            await query.message.reply_text(txt)

    elif query.data == "mm_help":
        await query.message.reply_markdown(
            t(context, user.id, "help")
        )

    elif query.data == "mm_order":
        # Bắt đầu flow /order từ callback
        return await order_start(update, context)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart_cmd))

    # Ngôn ngữ & main menu (inline)
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(main_menu_buttons, pattern="^mm_"))

    # Conversation /order
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("order", order_start),
            CallbackQueryHandler(order_start, pattern="^mm_order$"),
        ],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)
            ],
            CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)
            ],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
