from flask import Flask, request, abort, render_template, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
import os
import sqlite3
from dotenv import load_dotenv
from datetime import datetime
import matplotlib.pyplot as plt
import io

load_dotenv()
app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
YOUR_PUBLIC_URL = os.getenv("YOUR_PUBLIC_URL", "https://your-domain.ngrok.io")  # 用於圖片發送

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

def init_db():
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        display_name TEXT,
        source_id TEXT,
        category TEXT,
        amount INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    source_id = get_source_id(event)
    profile = line_bot_api.get_profile(user_id)
    display_name = profile.display_name

    parts = user_message.split()

    if user_message in ["使用說明", "幫助", "help"]:
        reply = (
            "📘 使用說明：\n"
            "1. 記帳：午餐 120\n"
            "2. 一鍵分帳\n"
            "3. 查紀錄\n"
            "4. 修改 ID 新金額\n"
            "5. 刪除 ID\n"
            "6. 清除全部\n"
            "7. 統計圖表"
        )

    elif len(parts) == 2 and parts[1].isdigit():
        category, amount = parts
        add_record(user_id, display_name, source_id, category, int(amount))
        reply = f"✅ 已記帳：{category} ${amount}"

    elif user_message == "一鍵分帳":
        reply = calculate_and_format_settlement(source_id)

    elif user_message == "查紀錄":
        reply = get_history(user_id)

    elif parts[0] == "修改" and len(parts) == 3:
        reply = update_record(parts[1], parts[2], user_id)

    elif parts[0] == "刪除" and len(parts) == 2:
        reply = delete_record(parts[1], user_id)

    elif user_message == "清除全部":
        reply = clear_all_records(source_id)

    elif user_message == "統計圖表":
        image_path = generate_pie_chart(user_id)
        if image_path:
            image_url = f"{YOUR_PUBLIC_URL}/{image_path}"
            line_bot_api.reply_message(
                event.reply_token,
                ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
            )
            return
        else:
            reply = "沒有可供統計的資料"

    else:
        reply = "⚠️ 請輸入格式：項目 金額（例如：午餐 120）或輸入「使用說明」查看可用指令"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_source_id(event):
    return getattr(event.source, "group_id", None) or getattr(event.source, "room_id", None) or event.source.user_id
