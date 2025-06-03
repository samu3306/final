from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, PostbackEvent,
    PostbackAction, QuickReply, QuickReplyButton,
    BubbleContainer, BoxComponent, TextComponent, ButtonComponent, FlexSendMessage,
)
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()  # 讀取 .env 檔

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if CHANNEL_ACCESS_TOKEN is None or CHANNEL_SECRET is None:
    raise Exception("請先設定環境變數 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 用戶待輸入金額分類狀態
user_pending_category = {}

# --- Flex Message 建立函式 ---

def build_main_flex():
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="請選擇操作", weight="bold", size="lg", margin="md"),
                BoxComponent(
                    layout="vertical",
                    margin="md",
                    spacing="sm",
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
                    spacing="sm",
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
    return FlexSendMessage(alt_text="請選擇分類", contents=bubble)

def build_settlement_flex():
    settlement_text = calculate_and_format_settlement()

    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="一鍵分帳結果", weight="bold", size="lg", margin="md"),
                TextComponent(text=settlement_text, wrap=True, margin="md"),
            ]
        )
    )
    return FlexSendMessage(alt_text="一鍵分帳結果", contents=bubble)

# --- 資料庫操作函式 ---

def init_db():
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            category TEXT,
            amount INTEGER
        )
        """
    )
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
    c.execute("SELECT id FROM records WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
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

def get_recent_records(user_id, limit=5):
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("SELECT category, amount FROM records WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# --- 一鍵分帳計算邏輯 ---

def calculate_and_format_settlement():
    conn = sqlite3.connect("accounts.db")
    c = conn.cursor()
    c.execute("SELECT user_id, SUM(amount) FROM records GROUP BY user_id")
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
        max_index = 0
        for i in range(1, len(amounts)):
            if amounts[i] > amounts[max_index]:
                max_index = i
        return max_index

    def get_max_debit_index():
        min_index = 0
        for i in range(1, len(amounts)):
            if amounts[i] < amounts[min_index]:
                min_index = i
        return min_index

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

# --- LINE Webhook 路由和事件處理 ---

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data
    params = dict(item.split('=') for item in data.split('&') if '=' in item)
    action = params.get("action")

    if action == "start_record":
        line_bot_api.reply_message(event.reply_token, build_category_flex())

    elif action == "select_category":
        category = params.get("category")
        if category:
            user_pending_category[user_id] = category
            # 用 Quick Reply 讓用戶選擇金額
            quick_reply_buttons = [
                QuickReplyButton(action=PostbackAction(label=str(x), data=f"action=enter_amount&amount={x}"))
                for x in [50, 100, 150, 200, 300]
            ]
            quick_reply = QuickReply(items=quick_reply_buttons)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"你選擇了「{category}」，請點選金額：", quick_reply=quick_reply)
            )
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="分類錯誤"))

    elif action == "enter_amount":
        amount_str = params.get("amount")
        if user_id in user_pending_category and amount_str and amount_str.isdigit():
            category = user_pending_category.pop(user_id)
            amount = int(amount_str)
            add_record(user_id, category, amount)
            reply = TextSendMessage(text=f"記帳成功：{category} ${amount}")
            flex_main = build_main_flex()
            line_bot_api.reply_message(event.reply_token, [reply, flex_main])
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請先選擇分類"))

    elif action == "delete_last":
        success = delete_last_record(user_id)
        reply_text = "刪除成功" if success else "沒有可刪除的記錄"
        line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=reply_text), build_main_flex()])

    elif action == "clear_all":
        clear_all_records(user_id)
        line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="已清除所有記錄"), build_main_flex()])

    elif action == "query_records":
        records = get_recent_records(user_id)
        if records:
            lines = [f"{cat} - ${amt}" for cat, amt in records]
            reply = TextSendMessage(text="最近紀錄：\n" + "\n".join(lines))
        else:
            reply = TextSendMessage(text="沒有紀錄")
        line_bot_api.reply_message(event.reply_token, [reply, build_main_flex()])

    elif action == "settlement":
        flex = build_settlement_flex()
        line_bot_api.reply_message(event.reply_token, flex)

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="不明指令"))

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 任何文字訊息都回主選單
    line_bot_api.reply_message(event.reply_token, build_main_flex())

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
