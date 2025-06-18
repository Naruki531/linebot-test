from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import os
import json
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# 環境変数の読み込み
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
FOLDER_ID = "1XqsqIobVzwYjByX6g_QcNSb4NNI9YfcV"  # Google Drive フォルダID

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not GOOGLE_CREDENTIALS:
    raise ValueError("必要な環境変数が設定されていません")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Drive API セットアップ
credentials_info = json.loads(GOOGLE_CREDENTIALS)
credentials = service_account.Credentials.from_service_account_info(
    credentials_info, scopes=['https://www.googleapis.com/auth/drive.file']
)
drive_service = build('drive', 'v3', credentials=credentials)

# ユーザーステート管理と受付番号カウンタ
user_data = {}
daily_counter = {}

def generate_receipt_id():
    today = datetime.datetime.now().strftime("%Y%m%d")
    count = daily_counter.get(today, 0) + 1
    daily_counter[today] = count
    return f"{today}{count:04d}"

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id

    receipt_id = generate_receipt_id()
    image_content = line_bot_api.get_message_content(message_id)
    image_path = f"/tmp/{receipt_id}.jpg"
    with open(image_path, 'wb') as f:
        for chunk in image_content.iter_content():
            f.write(chunk)

    # 一時的にデータを保存（後でアップロード）
    user_data[user_id] = {
        'receipt_id': receipt_id,
        'image_path': image_path
    }

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"📸 処方箋を受け取りました。\n受付番号：{receipt_id}\n次に電話番号を入力してください。")
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id not in user_data:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="まず処方箋の写真を送信してください。")
        )
        return

    if 'phone' not in user_data[user_id]:
        user_data[user_id]['phone'] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📞 電話番号を確認しました。\n次に受け取り希望日時を入力してください（例：6月14日 15時）。")
        )
        return

    if 'pickup_time' not in user_data[user_id]:
        user_data[user_id]['pickup_time'] = text

        # 受付完了したので、Google Drive にアップロード
        receipt_id = user_data[user_id]['receipt_id']
        image_path = user_data[user_id]['image_path']

        file_metadata = {
            'name': f'{receipt_id}.jpg',
            'parents': [FOLDER_ID],
            'properties': {
                'reception_id': receipt_id,
                'phone': user_data[user_id]['phone'],
                'pickup_time': user_data[user_id]['pickup_time']
            }
        }
        media = MediaFileUpload(image_path, mimetype='image/jpeg')
        uploaded_file = drive_service.files().create(
            body=file_metadata, media_body=media, fields='id'
        ).execute()

        summary = f"""📄 受付内容：
受付番号：{receipt_id}
電話番号：{user_data[user_id]['phone']}
受け取り日時：{user_data[user_id]['pickup_time']}
"""

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ ありがとうございます！以下の内容で受付しました：\n{summary}")
        )

