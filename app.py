from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
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

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    raise Exception("請先設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

user_pending_info = {}  # user_id -> {'user_name': str, 'category': str, 'user_id_selected': str}

def init_db():
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_name TEXT,
                category TEXT,
                amount INTEGER
            )
        """)
        conn.commit()

def add_record(user_id, user_name, category, amount):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO records (user_id, user_name, category, amount) VALUES (?, ?, ?, ?)",
            (user_id, user_name, category, amount),
        )
        conn.commit()

def delete_last_record(user_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM records WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM records WHERE id=?", (row[0],))
            conn.commit()
            return True
        return False

def clear_all_records(user_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM records WHERE user_id=?", (user_id,))
        conn.commit()

def get_recent_records(user_id, limit=10):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_name, category, amount FROM records WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return c.fetchall()

def get_all_records():
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, user_name, SUM(amount) FROM records GROUP BY user_id, user_name")
        return c.fetchall()

def calculate_settlement():
    all_records = get_all_records()
    if not all_records:
        return "沒有記帳資料，無法計算分帳"

    total = sum([amt for _, _, amt in all_records])
    n = len(all_records)
    avg = total / n

    balances = [(user_id, user_name, amt - avg) for user_id, user_name, amt in all_records]
    payers = [(user_id, user_name, -bal) for user_id, user_name, bal in balances if bal < -0.01]
    receivers = [(user_id, user_name, bal) for user_id, user_name, bal in balances if bal > 0.01]

    transfers = []
    i, j = 0, 0
    while i < len(payers) and j < len(receivers):
        payer_id, payer_name, pay_amount = payers[i]
        receiver_id, receiver_name, recv_amount = receivers[j]

        transfer_amount = min(pay_amount, recv_amount)
        transfers.append(f"{payer_name} → {receiver_name}：${transfer_amount:.0f}")

        pay_amount -= transfer_amount
        recv_amount -= transfer_amount

        if abs(pay_amount) < 0.01:
            i += 1
        else:
            payers[i] = (payer_id, payer_name, pay_amount)

        if abs(recv_amount) < 0.01:
            j += 1
        else:
            receivers[j] = (receiver_id, receiver_name, recv_amount)

    if not transfers:
        return "所有人已經均分，無需轉帳"

    return "\n".join(transfers)

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
                        ButtonComponent(style="primary", action=PostbackAction(label="記帳", data="action=start_record")),
                        ButtonComponent(style="secondary", action=PostbackAction(label="刪除最新記錄", data="action=delete_last")),
                        ButtonComponent(style="secondary", action=PostbackAction(label="清除所有記錄", data="action=clear_all")),
                        ButtonComponent(style="primary", action=PostbackAction(label="查詢紀錄", data="action=query_records")),
                        ButtonComponent(style="primary", action=PostbackAction(label="一鍵分帳", data="action=settlement")),
                    ],
                ),
            ]
        )
    )
    return FlexSendMessage(alt_text="主選單", contents=bubble)

def build_user_flex_dynamic(users):
    buttons = []
    for user in users:
        buttons.append(
            ButtonComponent(
                style="primary",
                action=PostbackAction(label=user["display_name"], data=f"action=select_user&user_id={user['user_id']}&user_name={user['display_name']}")
            )
        )
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇記帳人", weight="bold", size="lg", margin="md"),
                BoxComponent(layout="vertical", margin="md", contents=buttons)
            ]
        )
    )
    return FlexSendMessage(alt_text="請選擇記帳人", contents=bubble)

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
                        ButtonComponent(style="primary", action=PostbackAction(label="午餐", data="action=select_category&category=午餐")),
                        ButtonComponent(style="primary", action=PostbackAction(label="交通", data="action=select_category&category=交通")),
                        ButtonComponent(style="primary", action=PostbackAction(label="娛樂", data="action=select_category&category=娛樂")),
                        ButtonComponent(style="primary", action=PostbackAction(label="其他", data="action=select_category&category=其他")),
                    ],
                ),
            ]
        )
    )
    return FlexSendMessage(alt_text="請選擇記帳分類", contents=bubble)

def get_group_members(group_id):
    members = []
    next_token = None
    try:
        while True:
            if next_token:
                member_ids_response = line_bot_api.get_group_member_ids(group_id, start=next_token)
            else:
                member_ids_response = line_bot_api.get_group_member_ids(group_id)

            member_ids = member_ids_response.member_ids
            for user_id in member_ids:
                profile = line_bot_api.get_group_member_profile(group_id, user_id)
                members.append({"user_id": user_id, "display_name": profile.display_name})

            if member_ids_response.next:
                next_token = member_ids_response.next
            else:
                break
    except LineBotApiError as e:
        print(f"get_group_members error: {e}")
    return members

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if event.source.type != "group":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請在群組中使用此功能"))
        return

    user_id = event.source.user_id
    text = event.message.text.strip()
    try:
        if user_id in user_pending_info:
            info = user_pending_info[user_id]
            if text.isdigit():
                amount = int(text)
                if amount <= 0:
                    reply = TextSendMessage(text="金額需大於0，請重新輸入正確數字金額")
                    line_bot_api.reply_message(event.reply_token, reply)
                    return
                add_record(info['user_id_selected'], info['user_name'], info['category'], amount)
                reply = TextSendMessage(text=f"記帳成功：{info['user_name']} - {info['category']} ${amount}")
                flex_main = build_main_flex()
                line_bot_api.reply_message(event.reply_token, [reply, flex_main])
                del user_pending_info[user_id]
            else:
                reply = TextSendMessage(text="請輸入正確數字金額")
                line_bot_api.reply_message(event.reply_token, reply)
            return
        flex_main = build_main_flex()
        line_bot_api.reply_message(event.reply_token, flex_main)
    except Exception as e:
        print(f"handle_message error: {e}")

@handler.add(PostbackEvent)
def handle_postback(event):
    if event.source.type != "group":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請在群組中使用此功能"))
        return

    user_id = event.source.user_id
    data = event.postback.data

    try:
        params = {k: v for item in data.split('&') if '=' in item for k, v in [item.split('=', 1)]}
        action = params.get("action")

        if action == "start_record":
            group_id = event.source.group_id
            members = get_group_members(group_id)
            if members:
                flex_user = build_user_flex_dynamic(members)
                line_bot_api.reply_message(event.reply_token, flex_user)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="無法取得群組成員資訊"))

        elif action == "select_user":
            user_name = params.get("user_name")
            sel_user_id = params.get("user_id")
            if user_name and sel_user_id:
                user_pending_info[user_id] = {
                    "user_name": user_name,
                    "user_id_selected": sel_user_id
                }
                flex_category = build_category_flex()
                line_bot_api.reply_message(event.reply_token, flex_category)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="使用者選擇錯誤，請重新開始"))

        elif action == "select_category":
            category = params.get("category")
            if category and user_id in user_pending_info:
                user_pending_info[user_id]["category"] = category
                reply = TextSendMessage(text=f"你選擇了「{category}」，請輸入金額（數字）")
                line_bot_api.reply_message(event.reply_token, reply)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請先選擇使用者"))

        elif action == "delete_last":
            success = delete_last_record(user_id)
            text = "已刪除最新一筆記錄" if success else "沒有可刪除的記錄"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))

        elif action == "clear_all":
            clear_all_records(user_id)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已清除所有記錄"))

        elif action == "query_records":
            records = get_recent_records(user_id)
            if records:
                text = "最近記錄：\n" + "\n".join([f"{r[0]} - {r[1]} ${r[2]}" for r in records])
            else:
                text = "沒有記帳紀錄"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))

        elif action == "settlement":
            text = calculate_settlement()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))

        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不支援的操作"))

    except Exception as e:
        print(f"handle_postback error: {e}")

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
