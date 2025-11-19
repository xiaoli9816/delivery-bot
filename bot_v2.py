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

# ==== TOKEN TELEGRAM & ADMIN GROUP ====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable!")

# ID nhóm Admin & Shipper (âm, ví dụ -1001234567890)
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # có thể None

# ==== KẾT NỐI GOOGLE SHEET ====
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

# ==== GIỮ CART & NGÔN NGỮ TRONG RAM ====
CARTS = {}  # {user_id: [{"id": id, "name": str, "price": int, "qty": int}, ...]}

# ==== ĐA NGÔN NGỮ CƠ BẢN ====
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

(
    PHONE,
    ADDRESS,
    CONFIRM,
    SIMPLE_PRODUCT,
    SIMPLE_QTY,
    SIMPLE_METHOD,
    SIMPLE_INFO,
) = range(7)


def get_default_lang() -> str:
    try:
        records = settings_sheet.get_all_records()
        for row in records:
            if str(row.get("key")).strip() == "language_default":
                return str(row.get("value") or "vi").lower()
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


# ====== HÀM GỬI THÔNG BÁO ĐƠN MỚI CHO NHÓM ADMIN ======
async def notify_admin_new_order(
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
    user,
    items_text: str,
    total: int,
    phone: str,
    address: str,
    lang: str,
    time_str: str,
):
    if not ADMIN_CHAT_ID:
        return
    try:
        msg = (
            f"🔔 ĐƠN MỚI #{order_id}\n"
            f"👤 Khách: {user.full_name} (@{user.username or 'N/A'}, ID: {user.id})\n"
            f"🗣 Ngôn ngữ: {lang.upper()}\n"
            f"🧾 Món: {items_text}\n"
            f"💰 Tổng: {total}đ\n"
            f"📞 SĐT: {phone}\n"
            f"📍 Địa chỉ / Thông tin: {address}\n"
            f"⏰ Thời gian: {time_str}"
        )
        await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=msg)
    except Exception as e:
        print("Cannot send admin notification:", e)


# ==== HANDLERS CƠ BẢN ====
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
        reply_markup=reply_markup,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)

    if lang == "vi":
        text = (
            "🆘 *Hướng dẫn đặt đồ:*\n\n"
            "/start - Chọn ngôn ngữ\n"
            "/help - Xem hướng dẫn\n"
            "/menu - Xem menu hiện tại\n"
            "/add `<id>` `[số_lượng]` - Thêm món vào giỏ (VD: `/add 1 2`)\n"
            "/cart - Xem giỏ hàng\n"
            "/order - Đặt hàng theo giỏ (nhiều món, có giá từ Google Sheet)\n"
            "/simple - Đặt nhanh 1 món bằng hội thoại\n"
            "/cancel - Hủy luồng đặt hàng hiện tại\n\n"
            "💡 Gợi ý: Trong nhóm *Delivery Food & Coffee – Order Now* bạn có thể gửi hình món, "
            "ghi kèm ID món. Khách chỉ cần nhắn riêng bot và dùng /menu + /add + /order "
            "hoặc /simple."
        )
    else:
        text = (
            "🆘 *How to order:*\n\n"
            "/start - Choose language\n"
            "/help - Show help\n"
            "/menu - Show menu\n"
            "/add `<id>` `[qty]` - Add item to cart (ex: `/add 1 2`)\n"
            "/cart - Show your cart\n"
            "/order - Place order from cart\n"
            "/simple - Quick one-item chat order\n"
            "/cancel - Cancel current flow\n"
        )

    await update.message.reply_markdown(text)


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


def load_menu():
    return menu_sheet.get_all_records()


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)
    records = load_menu()

    if not records:
        await update.message.reply_text(t(context, user.id, "empty_menu"))
        return

    lines = [t(context, user.id, "menu_header"), ""]
    for item in records:
        if str(item.get("status", "")).lower() not in ("active", "sold_out"):
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
    for row in cart:
        if row["id"] == item["id"]:
            row["qty"] += qty
            break
    else:
        cart.append({
            "id": str(item["id"]),   # luôn lưu dạng chuỗi
            "name": item["name"],
            "price": int(item["price"]),
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

    # Lấy ID món dạng chuỗi, ví dụ: "F03" hoặc "f03"
    item_id = args[0].strip().lower()

    # Số lượng (mặc định = 1)
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
        sheet_id = str(item["id"]).strip().lower()   # ID trong sheet
        if sheet_id == item_id:
            target = item
            break

    if not target:
        await update.message.reply_text(
            t(context, user.id, "item_not_found")
        )
        return

    name = target["name_vi"] if lang == "vi" else target["name_en"]
    price = int(target["price"])

    add_to_cart(
        user.id,
        {"id": target["id"], "name": name, "price": price},
        qty
    )

    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
    )


# ========= FLOW /order (theo giỏ hàng, bạn đã dùng ok) =========
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

    CARTS[user.id] = []

    await update.message.reply_text(
        t(context, user.id, "order_saved", order_id=order_id)
    )

    await notify_admin_new_order(
        context,
        order_id,
        user,
        items_text,
        total,
        phone,
        address,
        lang,
        now_str,
    )

    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(t(context, user.id, "order_cancelled"))
    return ConversationHandler.END


# ========= FLOW /simple – ĐẶT NHANH 1 MÓN ==========

async def simple_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bước 1: chào + hỏi tên sản phẩm."""
    user = update.effective_user
    lang = get_lang(context, user.id)

    if lang == "vi":
        text = (
            "Xin chào bạn! 👋\n"
            "Cảm ơn bạn đã liên hệ với quán. Tôi là trợ lý tự động và sẽ giúp bạn đặt hàng nhanh chóng.\n"
            "Bạn muốn mua *món gì* hôm nay? (vd: Cơm gà xối mỡ, Trà sữa trân châu...)"
        )
    else:
        text = (
            "Hello! 👋\n"
            "I'm the shop assistant. Tell me *what item* you want to buy today?"
        )

    await update.message.reply_markdown(text)
    return SIMPLE_PRODUCT


async def simple_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bước 2: ghi tên sản phẩm, hỏi xác nhận + số lượng."""
    user = update.effective_user
    lang = get_lang(context, user.id)
    product = update.message.text.strip()
    context.user_data["simple_product"] = product

    if lang == "vi":
        text = (
            f"Bạn muốn mua *{product}*, đúng không ạ?\n"
            "Bạn cần *số lượng* bao nhiêu?"
        )
    else:
        text = (
            f"You want *{product}*, right?\n"
            "How many do you need?"
        )

    await update.message.reply_markdown(text)
    return SIMPLE_QTY


async def simple_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bước 3: nhận số lượng, hỏi hình thức lấy hàng (pickup/ship)."""
    user = update.effective_user
    lang = get_lang(context, user.id)
    qty_text = update.message.text.strip()

    try:
        qty = int(qty_text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        if lang == "vi":
            await update.message.reply_text(
                "Số lượng không hợp lệ, vui lòng nhập lại (ví dụ: 1, 2, 3...)."
            )
        else:
            await update.message.reply_text(
                "Invalid quantity, please send a number (1, 2, 3, ...)."
            )
        return SIMPLE_QTY

    context.user_data["simple_qty"] = qty

    if lang == "vi":
        text = (
            f"Ok, tôi đã ghi nhận số lượng *{qty}*.\n"
            "Bạn muốn *đến lấy tại quán* hay *ship tận nơi*?"
        )
        buttons = [
            [
                InlineKeyboardButton("🏠 Đến lấy tại quán", callback_data="simple_pickup"),
                InlineKeyboardButton("🚚 Ship tận nơi", callback_data="simple_delivery"),
            ]
        ]
    else:
        text = (
            f"Got it, quantity *{qty}*.\n"
            "Do you want *pickup at store* or *delivery*?"
        )
        buttons = [
            [
                InlineKeyboardButton("🏠 Pickup at store", callback_data="simple_pickup"),
                InlineKeyboardButton("🚚 Delivery", callback_data="simple_delivery"),
            ]
        ]

    await update.message.reply_markdown(text, reply_markup=InlineKeyboardMarkup(buttons))
    return SIMPLE_METHOD


async def simple_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bước 4 + 5: xử lý lựa chọn pickup / ship, hỏi thêm thông tin."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    lang = get_lang(context, user.id)

    if query.data == "simple_pickup":
        context.user_data["simple_method"] = "pickup"

        if lang == "vi":
            text = (
                "Vâng ạ! Bạn dự định *đến quán vào thời gian nào* "
                "để tôi chuẩn bị trước?"
            )
        else:
            text = "Great! When will you come to the store?"

        await query.edit_message_text(text, parse_mode="Markdown")
    else:
        context.user_data["simple_method"] = "delivery"

        if lang == "vi":
            text = (
                "Bạn vui lòng gửi giúp tôi:\n\n"
                "• Tên người nhận\n"
                "• Số điện thoại\n"
                "• Địa chỉ giao hàng"
            )
        else:
            text = (
                "Please send:\n\n"
                "• Receiver name\n"
                "• Phone number\n"
                "• Delivery address"
            )

        await query.edit_message_text(text)

    return SIMPLE_INFO


async def simple_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bước 6: nhận thông tin, tổng kết đơn, lưu sheet + báo nhóm Admin."""
    user = update.effective_user
    lang = get_lang(context, user.id)

    info_text = update.message.text.strip()
    context.user_data["simple_info"] = info_text

    product = context.user_data.get("simple_product", "N/A")
    qty = context.user_data.get("simple_qty", 1)
    method = context.user_data.get("simple_method", "pickup")

    method_vi = "lấy tại quán" if method == "pickup" else "ship tận nơi"
    method_en = "pickup at store" if method == "pickup" else "delivery"

    # Lưu vào Google Sheet (không tính giá, total = 0, phone/address gộp vào info)
    current_records = orders_sheet.get_all_records()
    order_id = 10001 + len(current_records)
    items_text = f"{qty}x {product} ({method_vi if lang == 'vi' else method_en})"
    total = 0  # bạn có thể sửa sau nếu muốn có giá
    phone = ""  # trong info_text sẽ chứa đầy đủ
    address = info_text
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    # Gửi tổng kết cho khách
    if lang == "vi":
        text = (
            "Hoàn tất rồi! 🎉\n"
            "Tôi đã ghi nhận đơn:\n"
            f"• Sản phẩm: *{product}*\n"
            f"• Số lượng: *{qty}*\n"
            f"• Hình thức: *{method_vi}*\n"
            f"• Thông tin giao / thời gian: {info_text}\n\n"
            f"Mã đơn của bạn: *{order_id}*"
        )
    else:
        text = (
            "All done! 🎉\n"
            "Here is your order:\n"
            f"• Item: *{product}*\n"
            f"• Quantity: *{qty}*\n"
            f"• Method: *{method_en}*\n"
            f"• Info: {info_text}\n\n"
            f"Your order ID: *{order_id}*"
        )

    await update.message.reply_markdown(text)

    # Báo nhóm Admin & Shipper
    await notify_admin_new_order(
        context,
        order_id,
        user,
        items_text,
        total,
        phone,
        address,
        lang,
        now_str,
    )

    return ConversationHandler.END


async def simple_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(context, user.id)
    if lang == "vi":
        text = "❌ Đã hủy luồng đặt nhanh."
    else:
        text = "❌ Quick order cancelled."
    await update.message.reply_text(text)
    return ConversationHandler.END


# ============ MAIN ============
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Chọn ngôn ngữ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lang_button, pattern="^lang_"))

    # Hướng dẫn
    app.add_handler(CommandHandler("help", help_cmd))

    # Các lệnh đặt đồ
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("cart", cart))        # xem giỏ hàng
    # alias tiếng Việt không dấu (OPTIONAL)
    app.add_handler(CommandHandler("giohang", cart))

    # luồng /order
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
    )
    app.add_handler(conv_handler)

    app.run_polling(drop_pending_updates=True)


