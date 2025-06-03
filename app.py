from linebot.models import (
    PostbackAction, QuickReply, QuickReplyButton,
)

# 儲存用戶狀態：user_pending_category 用來標記用戶待輸入金額的分類
user_pending_category = {}

def build_main_flex():
    from linebot.models import BubbleContainer, BoxComponent, TextComponent, ButtonComponent, FlexSendMessage
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇操作", weight="bold", size="lg", margin="md"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
                    spacing="sm",
                    contents=[
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="記帳", data="action=start_record")
                        ),
                        ButtonComponent(
                            style="secondary",
                            action=PostbackAction(label="刪除最新記錄", data="action=delete_last")
                        ),
                        ButtonComponent(
                            style="danger",
                            action=PostbackAction(label="清除所有記錄", data="action=clear_all")
                        ),
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="查詢紀錄", data="action=query_records")
                        ),
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="一鍵分帳", data="action=settlement")
                        ),
                    ],
                ),
            ]
        )
    )
    return FlexSendMessage(alt_text="主選單", contents=bubble)

def build_category_flex():
    from linebot.models import BubbleContainer, BoxComponent, TextComponent, ButtonComponent, FlexSendMessage
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇記帳分類", weight="bold", size="lg", margin="md"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
                    spacing="sm",
                    contents=[
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="午餐", data="action=select_category&category=午餐")
                        ),
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="交通", data="action=select_category&category=交通")
                        ),
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="娛樂", data="action=select_category&category=娛樂")
                        ),
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="其他", data="action=select_category&category=其他")
                        ),
                    ],
                ),
            ]
        )
    )
    return FlexSendMessage(alt_text="請選擇分類", contents=bubble)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data
    params = dict(item.split('=') for item in data.split('&') if '=' in item)
    action = params.get("action")

    if action == "start_record":
        # 回傳分類選擇按鈕
        line_bot_api.reply_message(event.reply_token, build_category_flex())

    elif action == "select_category":
        category = params.get("category")
        if category:
            # 標記用戶選擇了哪個分類，接下來要輸入金額
            user_pending_category[user_id] = category
            # 用 Quick Reply 讓用戶選擇數字（這裡示範幾個常用金額）
            quick_reply_buttons = [
                QuickReplyButton(action=PostbackAction(label=str(x), data=f"action=enter_amount&amount={x}"))
                for x in [50, 100, 150, 200, 300]
            ]
            quick_reply = QuickReply(items=quick_reply_buttons)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"你選擇了「{category}」，請點選金額：", quick_reply=quick_reply)
            )
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="分類錯誤"))

    elif action == "enter_amount":
        amount_str = params.get("amount")
        if user_id in user_pending_category and amount_str and amount_str.isdigit():
            category = user_pending_category.pop(user_id)
            amount = int(amount_str)
            add_record(user_id, category, amount)
            reply = TextSendMessage(text=f"記帳成功：{category} ${amount}")
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請先選擇分類"))

    elif action == "delete_last":
        success = delete_last_record(user_id)
        reply_text = "刪除成功" if success else "沒有可刪除的記錄"
        line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=reply_text), build_main_flex()])

    elif action == "clear_all":
        clear_all_records(user_id)
        line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="已清除所有記錄"), build_main_flex()])

    elif action == "query_records":
        records = get_recent_records(user_id)
        if records:
            lines = [f"{cat} - ${amt}" for cat, amt in records]
            reply = TextSendMessage(text="最近紀錄：\n" + "\n".join(lines))
        else:
            reply = TextSendMessage(text="沒有紀錄")
        line_bot_api.reply_message(event.reply_token, [reply, build_main_flex()])

    elif action == "settlement":
        flex = build_settlement_flex()
        line_bot_api.reply_message(event.reply_token, flex)

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不明指令"))

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 文字訊息不處理，直接回主選單
    line_bot_api.reply_message(event.reply_token, build_main_flex())

# 以下省略你原本的資料庫操作函式 (init_db, add_record, delete_last_record, clear_all_records, get_recent_records)
# 以及 build_settlement_flex(), min_cash_flow() 函式，請用你已有的

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
