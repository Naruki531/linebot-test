from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage, TextSendMessage
)
import os

app = Flask(__name__)

# 環境変数からLINEのAPIキーを取得
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("環境変数が設定されていません")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 簡易ユーザーステート管理（メモリ上）
user_data = {}

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# 画像受信ハンドラー
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id

    image_content = line_bot_api.get_message_content(message_id)
    image_path = f"/tmp/{user_id}_{message_id}.jpg"

    with open(image_path, 'wb') as f:
        for chunk in image_content.iter_content():
            f.write(chunk)

    # 状態を保存
    user_data[user_id] = {
        'image_path': image_path
    }

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="📸 処方箋を受け取りました。次に電話番号を入力してください。")
    )

# テキスト受信ハンドラー
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text

    # 画像を送っていない場合
    if user_id not in user_data:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="まず処方箋の写真を送信してください。")
        )
        return

    # 電話番号の登録
    if 'phone' not in user_data[user_id]:
        user_data[user_id]['phone'] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📞 電話番号を確認しました。次に受け取り希望日時を入力してください（例：6月14日 15時）。")
        )
        return

    # 受け取り日時の登録
    if 'pickup_time' not in user_data[user_id]:
        user_data[user_id]['pickup_time'] = text

        summary = f"""📄 受付内容：
電話番号：{user_data[user_id]['phone']}
受け取り日時：{user_data[user_id]['pickup_time']}
画像ファイル：{user_data[user_id]['image_path']}
"""

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ ありがとうございます！以下の内容で受付しました：\n{summary}")
        )
