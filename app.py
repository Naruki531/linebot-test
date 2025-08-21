from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage,
    TextSendMessage, FollowEvent, ImageSendMessage
)
import os
import json
import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# ====== 環境変数 ======
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
FOLDER_ID = "1XqsqIobVzwYjByX6g_QcNSb4NNI9YfcV"  # 共有ドライブ内のフォルダID

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not GOOGLE_CREDENTIALS:
    raise ValueError("必要な環境変数が設定されていません")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== Google Drive API ======
credentials_info = json.loads(GOOGLE_CREDENTIALS)
credentials = service_account.Credentials.from_service_account_info(
    credentials_info, scopes=['https://www.googleapis.com/auth/drive.file']
)
drive_service = build('drive', 'v3', credentials=credentials)

# ====== ユーザーステート管理 ======
user_data = {}
daily_counter = {}

def generate_receipt_id():
    today = datetime.datetime.now().strftime("%Y%m%d")
    count = daily_counter.get(today, 0) + 1
    daily_counter[today] = count
    return f"{today}{count:04d}"

# ====== Webhookエンドポイント ======
@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# ====== 友だち追加時 ======
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    user_data[user_id] = {}
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="いずみ薬局 テスト店では、LINEにて処方箋の受付を行っています。\n"
                 "個人情報は印刷および管理のために使用されます。\n"
                 "同意される方は『同意』と返信してください。\n"
                 "弊社プライバシーポリシー\nhttp://izumi-group.com/privacy/"
        )
    )

# ====== 画像受信時 ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id

    receipt_id = user_data.get(user_id, {}).get("receipt_id") or generate_receipt_id()
    image_content = line_bot_api.get_message_content(message_id)
    image_list = user_data.get(user_id, {}).get("images", [])
    image_path = f"/tmp/{receipt_id}_{len(image_list) + 1}.jpg"

    with open(image_path, 'wb') as f:
        for chunk in image_content.iter_content():
            f.write(chunk)

    if user_id not in user_data:
        user_data[user_id] = {}

    user_data[user_id]["receipt_id"] = receipt_id
    user_data[user_id].setdefault("images", []).append(image_path)
    user_data[user_id]["consent"] = True  # 同意済みにしておく

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="📸 処方箋画像を受け取りました。\n"
                             "複数ある場合は続けて送信してください。\n"
                             "すべて送信したら、電話番号を入力してください。")
    )

# ====== テキスト受信時 ======
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id not in user_data:
        user_data[user_id] = {}

    # 同意確認
    if 'consent' not in user_data[user_id]:
        if text.lower() in ['同意', 'はい', 'ok', '了解']:
            user_data[user_id]['consent'] = True
            image_msg = ImageSendMessage(
                original_content_url="https://drive.google.com/uc?id=1gXkCnQHz9S7Dwiu0g-3VlvBGvACTiiwa",
                preview_image_url="https://drive.google.com/uc?id=1gXkCnQHz9S7Dwiu0g-3VlvBGvACTiiwa"
            )
            line_bot_api.reply_message(event.reply_token, [
                TextSendMessage(text="✅ ご同意ありがとうございます。\n処方箋の受付方法は以下の画像をご覧ください："),
                image_msg
            ])
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ご利用には同意が必要です。「同意」と送信してください。")
            )
        return

    # 電話番号入力
    if 'phone' not in user_data[user_id]:
        user_data[user_id]['phone'] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📞 電話番号を確認しました。\n次に受け取り希望日時を入力してください（例：6月14日 15時）。")
        )
        return

    # 受け取り日時入力
    if 'pickup_time' not in user_data[user_id]:
        user_data[user_id]['pickup_time'] = text

        receipt_id = user_data[user_id]['receipt_id']
        phone = user_data[user_id]['phone']
        pickup_time = user_data[user_id]['pickup_time']
        images = user_data[user_id].get("images", [])

        # Google Drive に保存（Shared Drive対応）
        for idx, image_path in enumerate(images):
            file_metadata = {
                'name': f'{receipt_id}_{idx + 1}.jpg',
                'parents': [FOLDER_ID],  # 共有ドライブ内フォルダID
                'properties': {
                    'reception_id': receipt_id,
                    'phone': phone,
                    'pickup_time': pickup_time
                }
            }
            media = MediaFileUpload(image_path, mimetype='image/jpeg')
            drive_service.files().create(
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True  # これを追加
            ).execute()

        # LINE返信
        summary = f"""📄 受付内容：
受付番号：{receipt_id}
画像枚数：{len(images)}枚
電話番号：{phone}
受け取り日時：{pickup_time}
"""
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ ありがとうございます！以下の内容で受付しました：\n{summary}")
        )

        # 終了後にユーザーデータ削除
        del user_data[user_id]

if __name__ == "__main__":
    app.run(debug=True)
