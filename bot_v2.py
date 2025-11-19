import os
import json
import logging
from datetime import datetime

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

# -------------------------------------------------
# LOGGING
# -------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# ENV VARIABLES
# -------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

ORDER_NOTIFY_CHAT_ID = os.environ.get("ORDER_NOTIFY_CHAT_ID")  # ID nhóm Admin (optional)

# -------------------------------------------------
# GOOGLE SHEET
# -------------------------------------------------
SHEET_NAME = "77_Delivery_System"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

if "GOOGLE_CREDENTIALS" in os.environ:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    # Dùng file local khi chạy trên máy
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope
    )

client = gspread.authorize(creds)

# MENU & ORDERS phải tồn tại
menu_sheet = client.open(SHEET_NAME).worksheet("MENU")
orders_sheet = client.open(SHEET_NAME).worksheet("ORDERS")

# SETTINGS có thể chưa có
try:
    settings_sheet = client.open(SHEET_NAME).worksheet("SETTINGS")
except gspread.WorksheetNotFound:
    settings_sheet = None


def normalize_menu_row(row: dict) -> dict:
    """Chuẩn hóa 1 dòng menu từ Google Sheet."""
    row_id = (
        row.get("id")
        or row.get("ID")
        or row.get("Id")
        or row.get("mã")
        or ""
    )
    name_vi = row.get("name_vi") or row.get("Name_VI") or row.get("Tên_VN") or ""
    name_en = row.get("name_en") or row.get("Name_EN") or row.get("Name_EN ".strip()) or ""

    price_raw = row.get("price") or row.get("Price") or 0
    try:
        price = int(price_raw)
    except Exception:
        price = 0

    status = row.get("status") or row.get("Status") or ""
    status = str(status).lower().strip()

    return {
        "id": str(row_id).strip(),
        "name_vi": str(name_vi).strip(),
        "name_en": str(name_en).strip(),
        "price": price,
        "status": status or "active",
    }


def load_menu() -> list:
    rows = menu_sheet.get_all_records()
    return [normalize_menu_row(r) for r in rows]


# -------------------------------------------------
# STATE CHO CONVERSATION
# -------------------------------------------------
(
    PHONE,
    ADDRESS,
    CONFIRM,
    SIMPLE_PRODUCT,
    SIMPLE_QTY,
    SIMPLE_METHOD,
    SIMPLE_INFO,
    SIMPLE_CONFIRM,
) = range(8)

# -------------------------------------------------
# IN-MEMORY
# -------------------------------------------------
CARTS = {}  # {user_id: [{"id": str, "name": str, "price": int, "qty": int}, ...]}

# -------------------------------------------------
# MULTI-LANGUAGE MESSAGES
# -------------------------------------------------
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
        "vi": "Xác nhận đơn:\n{items}\nTổng: {total}đ\nSĐT: {phone}\nĐịa chỉ: {address}\n\nGõ 'yes' để xác nhận, 'no' để hủy.",
        "en": "Order summary:\n{items}\nTotal: {total} VND\nPhone: {phone}\nAddress: {address}\n\nType 'yes' to confirm, 'no' to cancel.",
    },
    "order_saved": {
        "vi": "✅ Đơn của bạn đã được ghi nhận! Mã đơn: {order_id}",
        "en": "✅ Your order has been placed! Order ID: {order_id}",
    },
    "order_cancelled": {
        "vi": "❌ Đã hủy đơn.",
        "en": "❌ Order cancelled.",
    },
}


def get_default_lang() -> str:
    try:
        if not settings_sheet:
            return "vi"
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key", "")).strip() == "language_default":
                return str(row.get("value", "vi")).strip() or "vi"
    except Exception as e:
        logger.warning("get_default_lang error: %s", e)
    return "vi"


def get_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    lang = context.user_data.get("lang")
    if not lang:
        lang = get_default_lang()
        context.user_data["lang"] = lang
    return lang


def t(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, key: str, **kwargs
) -> str:
    lang = get_lang(context, user_id)
    text = MESSAGES.get(key, {}).get(lang, "")
    if kwargs:
        text = text.format(**kwargs)
    return text


# -------------------------------------------------
# HANDLERS: START + LANGUAGE
# -------------------------------------------------
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

    if update.message:
        await update.message.reply_text(
            t(context, user.id, "welcome"), reply_markup=reply_markup
        )
    elif update.callback_query:
        # /start từ nút khác
        await update.callback_query.message.reply_text(
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


# -------------------------------------------------
# /HELP
# -------------------------------------------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)

    if lang == "vi":
        text = (
            "🆘 *Hướng dẫn đặt đồ:*\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add <id> [số_lượng] - Thêm món vào giỏ (VD: /add F01 2)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ (nhiều món, giá từ Google Sheet)\n"
            "/simple - Đặt nhanh 1 món bằng hội thoại\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n\n"
            "💡 Gợi ý: Ở nhóm *Delivery Food & Coffee – Order Now* bạn có thể "
            "gửi hình món, ghi kèm ID món. Khách chỉ cần nhắn riêng bot và dùng "
            "/menu + /add + /order hoặc /simple."
        )
    else:
        text = (
            "🆘 *How to order:*\n\n"
            "/start - Choose language\n"
            "/help - Show this help\n"
            "/menu - Show menu\n"
            "/add <id> [qty] - Add item to cart (e.g. /add F01 2)\n"
            "/cart - View cart\n"
            "/order - Checkout cart (multi-item)\n"
            "/simple - Quick order one item via dialog\n"
            "/cancel - Cancel current flow\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


# -------------------------------------------------
# /MENU
# -------------------------------------------------
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)
    records = load_menu()

    if not records:
        await update.message.reply_text(t(context, user.id, "empty_menu"))
        return

    lines = [t(context, user.id, "menu_header"), ""]
    for item in records:
        if item["status"] not in ("active", "sold_out"):
            continue
        name = item["name_vi"] if lang == "vi" else item["name_en"] or item["name_vi"]
        status_txt = " (hết / sold out)" if item["status"] == "sold_out" else ""
        lines.append(f"{item['id']}. {name} - {item['price']}đ{status_txt}")

    lines.append("")
    lines.append(t(context, user.id, "add_usage"))
    await update.message.reply_text("\n".join(lines))


# -------------------------------------------------
# CART
# -------------------------------------------------
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

    item_id = args[0].strip()  # F01, F02,...
    qty = 1
    if len(args) >= 2:
        try:
            qty = int(args[1])
        except Exception:
            qty = 1

    lang = get_lang(context, user.id)
    records = load_menu()
    target = None
    for item in records:
        if item["id"].upper() == item_id.upper():
            target = item
            break

    if not target:
        await update.message.reply_text(t(context, user.id, "item_not_found"))
        return

    name = target["name_vi"] if lang == "vi" else target["name_en"] or target["name_vi"]
    add_to_cart(
        user.id,
        {"id": target["id"], "name": name, "price": target["price"]},
        qty,
    )

    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
    )


async def cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cart_data = CARTS.get(user.id, [])

    if not cart_data:
        await update.message.reply_text(t(context, user.id, "cart_empty"))
        return

    lines = [t(context, user.id, "cart_header"), ""]
    total = 0
    for row in cart_data:
        line_total = row["price"] * row["qty"]
        total += line_total
        lines.append(f"{row['qty']} x {row['name']} = {line_total}đ")

    lines.append("")
    lines.append(f"👉 Total: {total}đ")
    await update.message.reply_text("\n".join(lines))


# -------------------------------------------------
# /ORDER (dùng giỏ hàng)
# -------------------------------------------------
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cart_data = CARTS.get(user.id, [])
    if not cart_data:
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

    cart_data = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart_data)
    lines = []
    for row in cart_data:
        lines.append(f"{row['qty']} x {row['name']} = {row['price'] * row['qty']}đ")

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

    cart_data = CARTS.get(user.id, [])
    total = sum(row["price"] * row["qty"] for row in cart_data)
    phone = context.user_data["order_phone"]
    address = context.user_data["order_address"]
    lang = get_lang(context, user.id)

    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)

    items_text = ", ".join(
        [f"{row['qty']}x {row['name']}" for row in cart_data]
    )
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Ghi vào sheet
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

    await update.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )

    # Gửi thông báo sang nhóm Admin nếu có
    if ORDER_NOTIFY_CHAT_ID:
        msg = (
            f"🆕 Đơn hàng mới (cart): #{order_id}\n"
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
            logger.warning("Notify admin error: %s", e)

    return ConversationHandler.END


# -------------------------------------------------
# /SIMPLE – ĐẶT NHANH 1 MÓN (HỘI THOẠI)
# -------------------------------------------------
async def simple_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Xin chào bạn! 👋\n"
        "Cảm ơn bạn đã liên hệ với quán. Tôi là trợ lý tự động và sẽ giúp bạn đặt hàng nhanh chóng.\n"
        "Bạn muốn mua món gì hôm nay?"
    )
    await update.message.reply_text(text)
    return SIMPLE_PRODUCT


async def simple_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product = update.message.text.strip()
    context.user_data["simple_product"] = product

    text = (
        f"Bạn muốn mua *{product}*, đúng không ạ?\n"
        "Bạn cần số lượng bao nhiêu?"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return SIMPLE_QTY


async def simple_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty_text = update.message.text.strip()
    try:
        qty = int(qty_text)
        if qty <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text(
            "Số lượng không hợp lệ, vui lòng nhập lại (ví dụ: 1, 2, 3...)."
        )
        return SIMPLE_QTY

    context.user_data["simple_qty"] = qty

    keyboard = [
        [
            InlineKeyboardButton(
                "Đến lấy tại quán", callback_data="simple_pickup"
            ),
            InlineKeyboardButton(
                "Ship tận nơi", callback_data="simple_ship"
            ),
        ]
    ]
    await update.message.reply_text(
        "Ok, tôi đã ghi nhận số lượng "
        f"{qty}.\nBạn muốn đến lấy tại quán hay ship tận nơi?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SIMPLE_METHOD


async def simple_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "simple_pickup":
        context.user_data["simple_method"] = "pickup"
        await query.edit_message_text(
            "Vâng ạ! Bạn dự định đến quán vào thời gian nào để tôi chuẩn bị trước?"
        )
    else:
        context.user_data["simple_method"] = "ship"
        await query.edit_message_text(
            "Bạn vui lòng gửi giúp tôi:\n\n"
            "• Tên người nhận\n"
            "• Số điện thoại\n"
            "• Địa chỉ giao hàng"
        )
    return SIMPLE_INFO


async def simple_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = update.message.text.strip()
    context.user_data["simple_info"] = info

    product = context.user_data["simple_product"]
    qty = context.user_data["simple_qty"]
    method = context.user_data["simple_method"]

    method_text = "Lấy tại quán" if method == "pickup" else "Ship tận nơi"

    summary = (
        "Hoàn tất rồi! 🎉\n"
        "Tôi đã ghi nhận đơn:\n"
        f"• Sản phẩm: {product}\n"
        f"• Số lượng: {qty}\n"
        f"• Hình thức: {method_text}\n"
    )
    if method == "ship":
        summary += f"• Thông tin giao hàng:\n{info}\n"
    else:
        summary += f"• Thời gian đến quán: {info}\n"

    summary += "\nBạn gõ 'yes' để xác nhận, 'no' để hủy."

    await update.message.reply_text(summary)
    return SIMPLE_CONFIRM


async def simple_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().lower()
    if text not in ["yes", "y", "có", "ok", "đồng ý"]:
        await update.message.reply_text("❌ Đã hủy đơn.")
        return ConversationHandler.END

    product = context.user_data["simple_product"]
    qty = context.user_data["simple_qty"]
    method = context.user_data["simple_method"]
    info = context.user_data["simple_info"]
    lang = get_lang(context, user.id)

    current_records = orders_sheet.get_all_records()
    order_id = 20001 + len(current_records)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    items_text = f"{qty}x {product} (simple)"
    address = info if method == "ship" else f"Đến quán: {info}"
    total = ""  # không có giá từ menu, có thể để trống

    orders_sheet.append_row(
        [
            order_id,
            user.id,
            user.username or "",
            "",  # phone (không bắt buộc trong simple)
            items_text,
            total,
            address,
            lang,
            now_str,
            f"simple-{method}",
        ]
    )

    await update.message.reply_text(
        f"✅ Đơn của bạn đã được ghi nhận! Mã đơn: {order_id}"
    )

    if ORDER_NOTIFY_CHAT_ID:
        method_text = "Lấy tại quán" if method == "pickup" else "Ship tận nơi"
        msg = (
            f"🆕 Đơn hàng mới (simple): #{order_id}\n"
            f"Khách: {user.full_name} (@{user.username})\n"
            f"Sản phẩm: {product}\n"
            f"Số lượng: {qty}\n"
            f"Hình thức: {method_text}\n"
            f"Thông tin: {info}\n"
            f"Thời gian: {now_str}"
        )
        try:
            await context.bot.send_message(
                chat_id=int(ORDER_NOTIFY_CHAT_ID), text=msg
            )
        except Exception as e:
            logger.warning("Notify admin error (simple): %s", e)

    return ConversationHandler.END


# -------------------------------------------------
# /CANCEL
# -------------------------------------------------
async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "order_cancelled"))
    return ConversationHandler.END


# -------------------------------------------------
# MAIN
# -------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # start + language
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))

    # help
    app.add_handler(CommandHandler("help", help_cmd))

    # menu + cart
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart))
    app.add_handler(CommandHandler("giohang", cart))  # alias tiếng Việt không dấu

    # order theo giỏ
    order_conv = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(order_conv)

    # simple one-item flow
    simple_conv = ConversationHandler(
        entry_points=[CommandHandler("simple", simple_start)],
        states={
            SIMPLE_PRODUCT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, simple_product
                )
            ],
            SIMPLE_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, simple_qty)
            ],
            SIMPLE_METHOD: [
                CallbackQueryHandler(simple_method, pattern="^simple_")
            ],
            SIMPLE_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, simple_info)
            ],
            SIMPLE_CONFIRM: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, simple_confirm
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(simple_conv)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
