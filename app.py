from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent, ButtonComponent,
    PostbackEvent, PostbackAction
)
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 初始化資料庫
def init_db():
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            source_id TEXT,
            category TEXT,
            amount INTEGER
        )
    """)
    conn.commit()
    conn.close()

# 新增記帳
def add_record(user_id, source_id, category, amount):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("INSERT INTO records (user_id, source_id, category, amount) VALUES (?, ?, ?, ?)",
              (user_id, source_id, category, amount))
    conn.commit()
    conn.close()

# 刪除單筆記錄
def delete_record(record_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE id=?", (record_id,))
    conn.commit()
    conn.close()

# 清除所有記錄
def clear_records(source_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE source_id=?", (source_id,))
    conn.commit()
    conn.close()

# 查詢最近紀錄（最多五筆）
def get_recent_records(source_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("SELECT id, category, amount FROM records WHERE source_id=? ORDER BY id DESC LIMIT 5", (source_id,))
    records = c.fetchall()
    conn.close()
    return records

# 建立 Flex 訊息功能表
def create_flex_menu():
    contents = [
        TextComponent(text="請選擇操作", weight="bold", size="lg", margin="md"),
        BoxComponent(
            layout="vertical",
            margin="md",
            spacing="sm",
            contents=[
                ButtonComponent(
                    style="primary",
                    action=PostbackAction(label="午餐 $120", data="action=add&category=午餐&amount=120")
                ),
                ButtonComponent(
                    style="primary",
                    action=PostbackAction(label="飲料 $60", data="action=add&category=飲料&amount=60")
                ),
                ButtonComponent(
                    style="primary",
                    action=PostbackAction(label="晚餐 $150", data="action=add&category=晚餐&amount=150")
                ),
                ButtonComponent(
                    style="secondary",
                    action=PostbackAction(label="🧹 清除全部紀錄", data="action=clear")
                )
            ]
        )
    ]

    bubble = BubbleContainer(body=BoxComponent(layout="vertical", contents=contents))
    return FlexSendMessage(alt_text="功能選單", contents=bubble)

# 建立刪除項目按鈕 Flex
def create_delete_flex(source_id):
    records = get_recent_records(source_id)
    if not records:
        return TextSendMessage(text="目前沒有記錄可刪除。")

    contents = [TextComponent(text="選擇要刪除的項目", weight="bold", size="lg", margin="md")]
    for record_id, category, amount in records:
        contents.append(
            ButtonComponent(
                style="danger",
                action=PostbackAction(label=f"刪除：{category} ${amount}", data=f"action=delete&id={record_id}")
            )
        )

    bubble = BubbleContainer(body=BoxComponent(layout="vertical", contents=contents))
    return FlexSendMessage(alt_text="刪除項目", contents=bubble)

# 接收文字訊息：顯示操作選單
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    msg = event.message.text.strip()
    source_id = event.source.group_id if event.source.type == "group" else event.source.user_id

    if msg == "功能選單":
        reply = create_flex_menu()
    elif msg == "刪除紀錄":
        reply = create_delete_flex(source_id)
    else:
        reply = TextSendMessage(text="請點選「功能選單」或「刪除紀錄」來操作。")

    line_bot_api.reply_message(event.reply_token, reply)

# 處理 Postback：新增、刪除、清除
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    source_id = event.source.group_id if event.source.type == "group" else event.source.user_id
    data = event.postback.data

    params = dict(pair.split('=') for pair in data.split('&'))

    action = params.get("action")
    if action == "add":
        category = params.get("category")
        amount = int(params.get("amount", 0))
        add_record(user_id, source_id, category, amount)
        reply = TextSendMessage(text=f"已記帳：{category} ${amount}")
    elif action == "delete":
        record_id = int(params.get("id"))
        delete_record(record_id)
        reply = TextSendMessage(text="已刪除該筆紀錄。")
    elif action == "clear":
        clear_records(source_id)
        reply = TextSendMessage(text="已清除所有紀錄。")
    else:
        reply = TextSendMessage(text="未知操作。")

    line_bot_api.reply_message(event.reply_token, reply)

# LINE webhook
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# 啟動
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
