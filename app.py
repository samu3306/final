from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
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
    user_message = event.message.text
    user_id = event.source.user_id
    source_type = event.source.type

    if source_type == "group":
        source_id = event.source.group_id
    elif source_type == "room":
        source_id = event.source.room_id
    else:
        source_id = user_id  # 單人對話時，以 user_id 當作來源 ID

    parts = user_message.split()
    if len(parts) == 2 and parts[1].isdigit():
        category, amount = parts
        add_record(source_id, source_type, user_id, category, int(amount))
        reply = f"已記帳：{category} ${amount}"
    elif user_message == "一鍵分帳":
        reply = calculate_and_format_settlement(source_id)
    else:
        reply = "請用格式：項目 金額（例如：午餐 120）或輸入「一鍵分帳」"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def init_db():
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            source_type TEXT,
            user_id TEXT,
            category TEXT,
            amount INTEGER
        )
        """
    )
    conn.commit()
    conn.close()

def add_record(source_id, source_type, user_id, category, amount):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (source_id, source_type, user_id, category, amount) VALUES (?, ?, ?, ?, ?)",
        (source_id, source_type, user_id, category, amount),
    )
    conn.commit()
    conn.close()

def calculate_and_format_settlement(source_id):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("SELECT user_id, SUM(amount) FROM records WHERE source_id = ? GROUP BY user_id", (source_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return "目前沒有記帳資料。"

    total_all = sum(row[1] for row in rows)
    user_count = len(rows)
    average = total_all / user_count

    settlement = {}
    for user_id, amount_sum in rows:
        settlement[user_id] = amount_sum - average

    transactions = min_cash_flow(settlement)

    reply_lines = [f"總消費：${total_all}，平均每人應付：${average:.2f}\n"]

    if not transactions:
        reply_lines.append("所有人均已付清，不需轉帳。")
    else:
        for debtor, creditor, amount in transactions:
            reply_lines.append(
                f"使用者 {debtor} 付給 使用者 {creditor} ${amount:.2f}"
            )

    return "\n".join(reply_lines)

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

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
