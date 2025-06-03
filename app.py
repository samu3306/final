@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if isinstance(event.source, (SourceGroup, SourceRoom)):
        group_id = event.source.group_id or event.source.room_id
    else:
        group_id = event.source.user_id  # 個人聊天室用 user_id 當 group_id

    user_id = event.source.user_id
    text = event.message.text.strip()
    try:
        if user_id in user_pending_category:
            category = user_pending_category.pop(user_id)
            if text.isdigit():
                amount = int(text)
                if amount <= 0:
                    user_pending_category[user_id] = category
                    reply = TextSendMessage(text="金額需大於0，請重新輸入正確數字金額")
                    line_bot_api.reply_message(event.reply_token, reply)
                    return
                profile = line_bot_api.get_profile(user_id)
                user_name = profile.display_name
                add_record(group_id, user_id, user_name, category, amount)
                reply = TextSendMessage(text=f"記帳成功：{category} ${amount} ({user_name})")
                flex_main = build_main_flex()
                line_bot_api.reply_message(event.reply_token, [reply, flex_main])
            else:
                user_pending_category[user_id] = category
                reply = TextSendMessage(text="請輸入正確數字金額")
                line_bot_api.reply_message(event.reply_token, reply)
            return
        flex_main = build_main_flex()
        line_bot_api.reply_message(event.reply_token, flex_main)
    except Exception as e:
        print(f"handle_message error: {e}")

@handler.add(PostbackEvent)
def handle_postback(event):
    if isinstance(event.source, (SourceGroup, SourceRoom)):
        group_id = event.source.group_id or event.source.room_id
    else:
        group_id = event.source.user_id

    user_id = event.source.user_id
    data = event.postback.data
    try:
        params = {}
        for item in data.split('&'):
            if '=' in item:
                k, v = item.split('=', 1)
                params[k] = v
        action = params.get("action")

        if action == "start_record":
            flex_category = build_category_flex()
            line_bot_api.reply_message(event.reply_token, flex_category)

        elif action == "select_category":
            category = params.get("category")
            if category:
                user_pending_category[user_id] = category
                reply = TextSendMessage(text=f"你選擇了「{category}」，請輸入金額（數字）")
                line_bot_api.reply_message(event.reply_token, reply)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="分類錯誤，請重新操作"))

        elif action == "delete_last":
            success = delete_last_record(group_id, user_id)
            if success:
                reply = TextSendMessage(text="刪除最新記錄成功。")
            else:
                reply = TextSendMessage(text="沒有可刪除的記錄。")
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])

        elif action == "clear_all":
            clear_all_records(group_id, user_id)
            reply = TextSendMessage(text="已清除所有記錄。")
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])

        elif action == "query_records":
            records = get_recent_records(group_id, user_id)
            if records:
                lines = [f"{cat} - ${amt}" for cat, amt in records]
                text = "最近紀錄：\n" + "\n".join(lines)
            else:
                text = "沒有記錄"
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=text), flex_main])

        elif action == "settlement":
            settlement_text = calculate_settlement(group_id)
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=settlement_text), flex_main])

        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不明指令"))

    except Exception as e:
        print(f"handle_postback error: {e}")
