from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, PostbackEvent, PostbackAction,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent, ButtonComponent
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

def add_record(user_id, source_id, category, amount):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (user_id, source_id, category, amount) VALUES (?, ?, ?, ?)",
        (user_id, source_id, category, amount),
    )
    conn.commit()
    conn.close()

def clear_records(source_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE source_id = ?", (source_id,))
    conn.commit()
    conn.close()

def calculate_and_format_settlement(source_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("SELECT user_id, SUM(amount) FROM records WHERE source_id = ? GROUP BY user_id", (source_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return TextSendMessage(text="目前沒有記帳資料。")

    total_all = sum(row[1] for row in rows)
    user_count = len(rows)
    average = total_all / user_count

    settlement = {user_id: amount_sum - average for user_id, amount_sum in rows}
    transactions = min_cash_flow(settlement)

    lines = [f"總支出：${total_all} / 人均：${average:.2f}"]
    if transactions:
        for debtor, creditor, amount in transactions:
            lines.append(f"使用者 {debtor} 付給 使用者 {creditor} ${amount:.2f}")
    else:
        lines.append("✅ 所有人均已付清，不需轉帳。")

    return TextSendMessage(text="\n".join(lines))

def min_cash_flow(settlement):
    transactions = []
    people = list(settlement.keys())
    amounts = [settlement[p] for p in people]

    def get_max_credit_index():
        return max(range(len(amounts)), key=lambda i: amounts[i])

    def get_max_debit_index():
        return min(range(len(amounts)), key=lambda i: amounts[i])

    def settle():
        max_credit = get_max_credit_index()
        max_debit = get_max_debit_index()

        if abs(amounts[max_credit]) < 1e-5 and abs(amounts[max_debit]) < 1e-5:
            return

        min_amount = min(amounts[max_credit], -amounts[max_debit])
        amounts[max_credit] -= min_amount
        amounts[max_debit] += min_amount

        transactions.append((people[max_debit], people[max_credit], min_amount))
        settle()

    settle()
    return transactions

def send_menu(reply_token):
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="記帳系統選單", weight="bold", size="lg"),
                ButtonComponent(
                    style="primary",
                    height="sm",
                    action=PostbackAction(label="清除所有紀錄", data="action=clear")
                ),
                ButtonComponent(
                    style="primary",
                    height="sm",
                    action=PostbackAction(label="一鍵分帳", data="action=settlement")
                ),
                ButtonComponent(
                    style="primary",
                    height="sm",
                    action=PostbackAction(label="記帳 (LIFF 表單)", data="action=add_record"),
                ),
            ],
        )
    )
    flex_message = FlexSendMessage(alt_text="記帳系統選單", contents=bubble)
    line_bot_api.reply_message(reply_token, flex_message)

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
    user_msg = event.message.text.strip()
    # 收到任何訊息就送出選單
    send_menu(event.reply_token)

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    source_id = event.source.group_id if event.source.type == "group" else event.source.user_id

    if data == "action=clear":
        clear_records(source_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✅ 已清除所有紀錄"))
    elif data == "action=settlement":
        reply = calculate_and_format_settlement(source_id)
        line_bot_api.reply_message(event.reply_token, reply)
    elif data == "action=add_record":
        # 這邊示範用文字提示，通常要用 LIFF 開啟表單
        # 你可以把這裡改成 URIAction 打開 LIFF 網頁
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請點此打開記帳表單: https://你的liff網址"))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="無效指令"))

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
