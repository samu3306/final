from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, PostbackAction, FlexSendMessage,
    BubbleContainer, BoxComponent, TextComponent, ButtonComponent
)
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if CHANNEL_ACCESS_TOKEN is None or CHANNEL_SECRET is None:
    raise Exception("請先設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 簡單的「用戶暫存」：key=user_id，value=待輸入的 category
user_pending_category = {}

def init_db():
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            category TEXT,
            amount INTEGER
        )
    """)
    conn.commit()
    conn.close()

def add_record(user_id, category, amount):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (user_id, category, amount) VALUES (?, ?, ?)",
        (user_id, category, amount),
    )
    conn.commit()
    conn.close()

def build_category_flex():
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇記帳分類", weight="bold", size="lg", margin="md"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
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
    return FlexSendMessage(alt_text="請選擇記帳分類", contents=bubble)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # 檢查此用戶是否等待輸入金額（是否有暫存的 category）
    if user_id in user_pending_category:
        category = user_pending_category.pop(user_id)
        # 確認輸入是數字
        if text.isdigit():
            amount = int(text)
            add_record(user_id, category, amount)
            reply = TextSendMessage(text=f"記帳成功：{category} ${amount}")
        else:
            # 沒輸入正確數字，重新要求輸入
            user_pending_category[user_id] = category
            reply = TextSendMessage(text="請輸入正確的金額（數字）")
        line_bot_api.reply_message(event.reply_token, reply)
        return

    # 使用者輸入指令觸發記帳流程
    if text == "記帳":
        # 回傳選擇分類的 Flex Message
        flex_message = build_category_flex()
        line_bot_api.reply_message(event.reply_token, flex_message)
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入「記帳」開始記帳流程")
        )

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data  # 格式例如：action=select_category&category=午餐

    # 解析 postback data
    params = {}
    for item in data.split('&'):
        k, v = item.split('=')
        params[k] = v

    if params.get("action") == "select_category":
        category = params.get("category")
        if category:
            # 將用戶暫存，下一則訊息為金額
            user_pending_category[user_id] = category
            reply = TextSendMessage(text=f"你選擇了「{category}」，請輸入金額（例如：120）")
            line_bot_api.reply_message(event.reply_token, reply)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="分類錯誤，請重新記帳"))

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
