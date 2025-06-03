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

if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    raise Exception("請先設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

user_pending_category = {}
user_pending_name = set()  # 用來追蹤哪些 user 正在輸入名字

def init_db():
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        # 新增 user_names 表，用來存 user_id 對應的名稱
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_names (
                user_id TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        # 更新 records 表，加入 user_name 欄位
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

def set_user_name(user_id, name):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("REPLACE INTO user_names (user_id, name) VALUES (?, ?)", (user_id, name))
        conn.commit()

def get_user_name(user_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM user_names WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        return row[0] if row else None

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
            "SELECT category, amount FROM records WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return c.fetchall()

def get_all_records():
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, SUM(amount) FROM records GROUP BY user_id")
        return c.fetchall()

def calculate_settlement():
    all_records = get_all_records()
    if not all_records:
        return "沒有記帳資料，無法計算分帳"

    total = sum([amt for _, amt in all_records])
    n = len(all_records)
    avg = total / n

    balances = [(user_id, amt - avg) for user_id, amt in all_records]

    payers = [(uid, -bal) for uid, bal in balances if bal < -0.01]
    receivers = [(uid, bal) for uid, bal in balances if bal > 0.01]

    transfers = []
    i, j = 0, 0
    while i < len(payers) and j < len(receivers):
        payer_id, pay_amount = payers[i]
        receiver_id, recv_amount = receivers[j]

        transfer_amount = min(pay_amount, recv_amount)
        transfers.append(f"用戶 {payer_id} → 用戶 {receiver_id}：${transfer_amount:.0f}")

        pay_amount -= transfer_amount
        recv_amount -= transfer_amount

        if abs(pay_amount) < 0.01:
            i += 1
        else:
            payers[i] = (payer_id, pay_amount)

        if abs(recv_amount) < 0.01:
            j += 1
        else:
            receivers[j] = (receiver_id, recv_amount)

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
                        ButtonComponent(
                            style="primary",
                            action=PostbackAction(label="記帳", data="action=start_record")
                        ),
                        ButtonComponent(
                            style="secondary",
                            action=PostbackAction(label="刪除最新記錄", data="action=delete_last")
                        ),
                        ButtonComponent(
                            style="secondary",
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
    try:
        name = get_user_name(user_id)
        # 尚未設定名稱，請輸入名稱階段
        if not name:
            if user_id not in user_pending_name:
                user_pending_name.add(user_id)
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="歡迎使用，請先輸入您的名稱（例如：小明）：")
                )
                return
            else:
                # user_pending_name 裡，使用者剛剛輸入的視為名稱，儲存
                set_user_name(user_id, text)
                user_pending_name.remove(user_id)
                reply = TextSendMessage(text=f"名稱已儲存為：{text}\n現在可以開始記帳了！")
                flex_main = build_main_flex()
                line_bot_api.reply_message(event.reply_token, [reply, flex_main])
                return
        
        # 使用者已設定名稱，正常記帳流程
        if user_id in user_pending_category:
            category = user_pending_category.pop(user_id)
            if text.isdigit():
                amount = int(text)
                if amount <= 0:
                    user_pending_category[user_id] = category
                    reply = TextSendMessage(text="金額需大於0，請重新輸入正確數字金額")
                    line_bot_api.reply_message(event.reply_token, reply)
                    return
                add_record(user_id, name, category, amount)
                reply = TextSendMessage(text=f"記帳成功：{category} ${amount}")
                flex_main = build_main_flex()
                line_bot_api.reply_message(event.reply_token, [reply, flex_main])
            else:
                user_pending_category[user_id] = category
                reply = TextSendMessage(text="請輸入正確數字金額")
                line_bot_api.reply_message(event.reply_token, reply)
            return

        # 非記帳階段，顯示主選單
        flex_main = build_main_flex()
        line_bot_api.reply_message(event.reply_token, flex_main)

    except Exception as e:
        print(f"handle_message error: {e}")

@handler.add(PostbackEvent)
def handle_postback(event):
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
            # 先檢查是否有設定名稱
            name = get_user_name(user_id)
            if not name:
                user_pending_name.add(user_id)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請先輸入您的名稱（例如：小明），謝謝！"))
                return

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
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])

        elif action == "clear_all":
            clear_all_records(user_id)
            reply = TextSendMessage(text="已清除所有記錄。")
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])

        elif action == "query_records":
            records = get_recent_records(user_id)
            if records:
                lines = [f"{cat} - ${amt}" for cat, amt in records]
                text = "最近紀錄：\n" + "\n".join(lines)
            else:
                text = "沒有記錄"
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=text), flex_main])

        elif action == "settlement":
            settlement_text = calculate_settlement()
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=settlement_text), flex_main])

        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不明指令"))

    except Exception as e:
        print(f"handle_postback error: {e}")

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
