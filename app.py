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

def delete_last_record(user_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        "SELECT id FROM records WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,)
    )
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM records WHERE id=?", (row[0],))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def clear_all_records(user_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def build_main_flex():
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇操作", weight="bold", size="lg", margin="md"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
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
                    ],
                ),
            ]
        )
    )
    return FlexSendMessage(alt_text="主選單", contents=bubble)

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

    # 若用戶在輸入金額
    if user_id in user_pending_category:
        category = user_pending_category.pop(user_id)
        if text.isdigit():
            amount = int(text)
            add_record(user_id, category, amount)
            reply = TextSendMessage(text=f"記帳成功：{category} ${amount}")
            # 記帳成功後，回主選單
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])
        else:
            user_pending_category[user_id] = category
            reply = TextSendMessage(text="請輸入正確數字金額")
            line_bot_api.reply_message(event.reply_token, reply)
        return

    # 一般訊息，回主選單
    flex_main = build_main_flex()
    line_bot_api.reply_message(event.reply_token, flex_main)

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data

    params = {}
    for item in data.split('&'):
        if '=' in item:
            k, v = item.split('=', 1)
            params[k] = v

    action = params.get("action")

    if action == "start_record":
        # 啟動記帳，顯示分類選擇
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
        success = delete_last_record(user_id)
        if success:
            reply = TextSendMessage(text="刪除最新記錄成功。")
        else:
            reply = TextSendMessage(text="沒有可刪除的記錄。")
        # 刪除後回主選單
        flex_main = build_main_flex()
        line_bot_api.reply_message(event.reply_token, [reply, flex_main])

    elif action == "clear_all":
        clear_all_records(user_id)
        reply = TextSendMessage(text="已清除所有記錄。")
        flex_main = build_main_flex()
        line_bot_api.reply_message(event.reply_token, [reply, flex_main])

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不明指令"))

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
