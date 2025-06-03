from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage,
    BubbleContainer, BoxComponent, TextComponent, ButtonComponent, URIAction
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

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

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

def get_user_name(user_id):
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except:
        return "匿名使用者"

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

    contents = [
        TextComponent(text="一鍵分帳結果", weight="bold", size="lg", color="#3366CC"),
        TextComponent(text=f"總支出：${total_all} / 人均：${average:.2f}", size="sm", margin="md"),
    ]

    if transactions:
        for debtor, creditor, amount in transactions:
            debtor_name = get_user_name(debtor)
            creditor_name = get_user_name(creditor)
            contents.append(TextComponent(text=f"{debtor_name} → {creditor_name}：${amount:.2f}", size="sm", margin="sm"))
    else:
        contents.append(TextComponent(text="✅ 所有人均已付清，不需轉帳。", size="sm", margin="md", color="#00AA00"))

    contents.append(
        ButtonComponent(
            style="primary",
            action=URIAction(label="查看更多記錄", uri="line://app/your_app_id")  # 可換成你的 URI
        )
    )

    bubble = BubbleContainer(
        body=BoxComponent(layout="vertical", contents=contents)
    )
    return FlexSendMessage(alt_text="一鍵分帳結果", contents=bubble)

def query_recent_records(user_id, source_id, limit=5):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        "SELECT category, amount FROM records WHERE user_id=? AND source_id=? ORDER BY id DESC LIMIT ?",
        (user_id, source_id, limit)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return TextSendMessage(text="你目前沒有記帳紀錄。")

    contents = [
        TextComponent(text="最近記帳紀錄", weight="bold", size="lg", color="#3366CC")
    ]
    for category, amount in rows:
        contents.append(TextComponent(text=f"{category}：${amount}", size="sm", margin="sm"))

    bubble = BubbleContainer(body=BoxComponent(layout="vertical", contents=contents))
    return FlexSendMessage(alt_text="最近記帳紀錄", contents=bubble)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    source_id = event.source.group_id if event.source.type == "group" else event.source.user_id

    if len(user_message.split()) == 2 and user_message.split()[1].isdigit():
        category, amount = user_message.split()
        add_record(user_id, source_id, category, int(amount))
        reply = TextSendMessage(text=f"已記帳：{category} ${amount}")
    elif user_message == "一鍵分帳":
        reply = calculate_and_format_settlement(source_id)
    elif user_message == "查紀錄":
        reply = query_recent_records(user_id, source_id)
    else:
        reply = TextSendMessage(text="請用格式：項目 金額（例如：午餐 120），或輸入「一鍵分帳」、「查紀錄」")

    line_bot_api.reply_message(event.reply_token, reply)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
