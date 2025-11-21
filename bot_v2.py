async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            t(context, user.id, "add_usage")
        )
        return

    # ID món có thể là '1' hoặc 'F03', giữ nguyên dạng chuỗi
    item_id = args[0].strip()

    # Số lượng
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
        if str(item["id"]).lower() == item_id.lower():
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
        qty,
    )

    await update.message.reply_text(
        t(context, user.id, "added_to_cart", qty=qty, name=name)
    )
