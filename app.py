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

def get_source_id(event):
    if event.source.type == "user":
        return event.source.user_id
    elif event.source.type == "group":
        return event.source.group_id
    elif event.source.type == "room":
        return event.source.room_id
    return None

def init_db():
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT,
                user_id TEXT,
                user_name TEXT,
                category TEXT,
                amount INTEGER
            )
        """)
        conn.commit()

def add_record(source_id, user_id, user_name, category, amount):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO records (source_id, user_id, user_name, category, amount) VALUES (?, ?, ?, ?, ?)",
            (source_id, user_id, user_name, category, amount),
        )
        conn.commit()

def delete_last_record(source_id, user_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM records WHERE source_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (source_id, user_id)
        )
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM records WHERE id=?", (row[0],))
            conn.commit()
            return True
        return False

def clear_all_records(source_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM records WHERE source_id=?", (source_id,))
        conn.commit()

def get_recent_records(source_id, user_id, limit=10):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT category, amount FROM records WHERE source_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (source_id, user_id, limit)
        )
        return c.fetchall()

def get_all_records(source_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_name, SUM(amount) FROM records WHERE source_id=? GROUP BY user_id",
            (source_id,)
        )
        return c.fetchall()

def get_all_user_records(source_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_name, user_id, category, amount FROM records WHERE source_id=? ORDER BY user_id, id",
            (source_id,)
        )
        rows = c.fetchall()

    records_by_user = {}
    for user_name, user_id, category, amount in rows:
        if user_id not in records_by_user:
            records_by_user[user_id] = {
                "name": user_name,
                "records": []
            }
        records_by_user[user_id]["records"].append((category, amount))
    return records_by_user

def calculate_settlement(source_id):
    all_records = get_all_records(source_id)
    if not all_records:
        return "沒有記帳資料，無法計算分帳"

    total = sum([amt for _, amt in all_records])
    n = len(all_records)
    avg = total / n

    balances = [(user_name, amt - avg) for user_name, amt in all_records]

    payers = [(uname, -bal) for uname, bal in balances if bal < -0.01]
    receivers = [(uname, bal) for uname, bal in balances if bal > 0.01]

    transfers = []
    i, j = 0, 0
    while i < len(payers) and j < len(receivers):
        payer_name, pay_amount = payers[i]
        receiver_name, recv_amount = receivers[j]

        transfer_amount = min(pay_amount, recv_amount)
        transfers.append(f"{payer_name} → {receiver_name}：${transfer_amount:.0f}")

        pay_amount -= transfer_amount
        recv_amount -= transfer_amount

        if abs(pay_amount) < 0.01:
            i += 1
        else:
            payers[i] = (payer_name, pay_amount)

        if abs(recv_amount) < 0.01:
            j += 1
        else:
            receivers[j] = (receiver_name, recv_amount)

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
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="記帳", data="action=start_record")),
                        #ButtonComponent(style="primary", margin="md", action=PostbackAction(label="刪除最新記錄", data="action=delete_last")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="刪除指定記錄", data="action=delete_select")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="清除所有記錄", data="action=clear_all")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="查詢紀錄", data="action=query_records")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="一鍵分帳", data="action=settlement")),
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
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="午餐", data="action=select_category&category=午餐")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="交通", data="action=select_category&category=交通")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="娛樂", data="action=select_category&category=娛樂")),
                        ButtonComponent(style="primary", margin="md", action=PostbackAction(label="其他", data="action=select_category&category=其他")),
                    ],
                ),
            ]
        )
    )
    return FlexSendMessage(alt_text="請選擇記帳分類", contents=bubble)

def get_recent_records_with_id(source_id, user_id, limit=10):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, category, amount FROM records WHERE source_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (source_id, user_id, limit)
        )
        return c.fetchall()

def build_delete_select_flex(source_id, user_id):
    records = get_recent_records_with_id(source_id, user_id)
    if not records:
        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=[
                    TextComponent(text="沒有可刪除的記錄", weight="bold", size="md", margin="md"),
                    ButtonComponent(style="primary", margin="md", action=PostbackAction(label="回主選單", data="action=main_menu"))
                ]
            )
        )
        return FlexSendMessage(alt_text="刪除指定紀錄", contents=bubble)

    buttons = []
    for rec_id, category, amount in records:
        label = f"{category} ${amount}"
        buttons.append(
            ButtonComponent(
                style="secondary",
                margin="sm",
                height="sm",
                action=PostbackAction(
                    label=label,
                    data=f"action=delete_record&record_id={rec_id}"
                )
            )
        )

    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇要刪除的紀錄", weight="bold", size="lg", margin="md"),
                BoxComponent(layout="vertical", margin="md", contents=buttons),
                ButtonComponent(style="primary", margin="md", action=PostbackAction(label="取消", data="action=main_menu"))
            ]
        )
    )
    return FlexSendMessage(alt_text="刪除指定紀錄", contents=bubble)

def delete_record_by_id(record_id):
    with sqlite3.connect("accounts.db") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM records WHERE id=?", (record_id,))
        conn.commit()

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    source_id = get_source_id(event)
    user_id = event.source.user_id
    text = event.message.text.strip()
    try:
        if source_id in user_pending_category:
            category = user_pending_category.pop(source_id)
            if text.isdigit():
                amount = int(text)
                if amount <= 0:
                    user_pending_category[source_id] = category
                    reply = TextSendMessage(text="金額需大於0，請重新輸入正確數字金額")
                    line_bot_api.reply_message(event.reply_token, reply)
                    return
                user_name = event.source.user_id  # 可以改為抓名稱或暱稱
                add_record(source_id, user_id, user_name, category, amount)
                reply = TextSendMessage(text=f"已記帳：{category} ${amount}")
                line_bot_api.reply_message(event.reply_token, [reply, build_main_flex()])
            else:
                user_pending_category[source_id] = category
                reply = TextSendMessage(text="請輸入數字金額")
                line_bot_api.reply_message(event.reply_token, reply)
        else:
            line_bot_api.reply_message(event.reply_token, build_main_flex())
    except Exception as e:
        print("handle_message error:", e)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="發生錯誤，請稍後再試"))

@handler.add(PostbackEvent)
def handle_postback(event):
    source_id = get_source_id(event)
    user_id = event.source.user_id
    data = event.postback.data
    params = {}
    if "&" in data:
        pairs = data.split("&")
        for p in pairs:
            k,v = p.split("=")
            params[k] = v
    else:
        params[data] = ""

    action = params.get("action")

    try:
        if action == "start_record":
            # 顯示分類選單
            line_bot_api.reply_message(event.reply_token, build_category_flex())

        elif action == "select_category":
            category = params.get("category")
            if category:
                user_pending_category[source_id] = category
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"請輸入{category}的金額"))

        elif action == "delete_last":
            if delete_last_record(source_id, user_id):
                reply = TextSendMessage(text="已刪除最新一筆記錄")
            else:
                reply = TextSendMessage(text="找不到要刪除的記錄")
            line_bot_api.reply_message(event.reply_token, [reply, build_main_flex()])

        elif action == "delete_select":
            flex_delete_select = build_delete_select_flex(source_id, user_id)
            line_bot_api.reply_message(event.reply_token, flex_delete_select)

        elif action == "delete_record":
            record_id = params.get("record_id")
            if record_id and record_id.isdigit():
                delete_record_by_id(int(record_id))
                reply = TextSendMessage(text="指定記錄已刪除。")
            else:
                reply = TextSendMessage(text="刪除失敗，無效的記錄ID。")
            line_bot_api.reply_message(event.reply_token, [reply, build_main_flex()])

        elif action == "clear_all":
            clear_all_records(source_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="已清除所有記錄"), build_main_flex()])

        elif action == "query_records":
            records_by_user = get_all_user_records(source_id)
            if not records_by_user:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="沒有任何記錄"))
            else:
                msg = ""
                for user_data in records_by_user.values():
                    msg += f"{user_data['name']}：\n"
                    for cat, amt in user_data["records"]:
                        msg += f"  {cat} ${amt}\n"
                    msg += "\n"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

        elif action == "settlement":
            settlement_text = calculate_settlement(source_id)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=settlement_text))

        elif action == "main_menu":
            line_bot_api.reply_message(event.reply_token, build_main_flex())

        else:
            line_bot_api.reply_message(event.reply_token, build_main_flex())

    except Exception as e:
        print("handle_postback error:", e)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="發生錯誤，請稍後再試"))

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
    app.run(port=8000)
