from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage, FollowEvent, ImageSendMessage
import os
import json
import datetime
import subprocess

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

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

# PDF保存フォルダを指定（Windows用）
PDF_SAVE_DIR = "C:\\print_bot\\処方箋画像"
os.makedirs(PDF_SAVE_DIR, exist_ok=True)

def generate_receipt_id():
    today = datetime.datetime.now().strftime("%Y%m%d")
    count = daily_counter.get(today, 0) + 1
    daily_counter[today] = count
    return f"{today}{count:04d}"

def create_pdf_with_info(pdf_path, image_path, receipt_id, phone, pickup_time):
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica", 12)
    c.drawString(50, height - 50, f"受付番号: {receipt_id}")
    c.drawString(50, height - 70, f"電話番号: {phone}")
    c.drawString(50, height - 90, f"受け取り日時: {pickup_time}")

    image = ImageReader(image_path)
    max_width = width - 100
    max_height = height - 150

    img_width, img_height = image.getSize()
    scale = min(max_width / img_width, max_height / img_height)
    img_width_scaled = img_width * scale
    img_height_scaled = img_height * scale

    x = (width - img_width_scaled) / 2
    y = height - 150 - img_height_scaled

    c.drawImage(image, x, y, width=img_width_scaled, height=img_height_scaled)
    c.showPage()
    c.save()

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    user_data[user_id] = {}
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="いずみ薬局　テスト店では、LINEにて処方箋の受付を行っています。\n個人情報は印刷および管理のために使用されます。\n同意される方は『同意』と返信してください。\n弊社プライバシーポリシー\nhttp://izumi-group.com/privacy/")
    )

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

    user_data[user_id] = {
        'receipt_id': receipt_id,
        'image_path': image_path,
        'consent': True  # 画像を送った時点で同意済みとみなす（または必要に応じてチェック）
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
        user_data[user_id] = {}

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

    if 'phone' not in user_data[user_id]:
        user_data[user_id]['phone'] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📞 電話番号を確認しました。\n次に受け取り希望日時を入力してください（例：6月14日 15時）。")
        )
        return

    if 'pickup_time' not in user_data[user_id]:
        user_data[user_id]['pickup_time'] = text

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
        drive_service.files().create(
            body=file_metadata, media_body=media, fields='id'
        ).execute()

        pdf_path = os.path.join(PDF_SAVE_DIR, f"{receipt_id}.pdf")
        create_pdf_with_info(
            pdf_path,
            image_path,
            receipt_id,
            user_data[user_id]['phone'],
            user_data[user_id]['pickup_time']
        )

        printer_name = "RICOH SG 3200 RPCS-R調剤"  # ← あなたのプリンタ名に合わせて修正
        try:
            subprocess.run([
                "AcroRd32.exe", "/t", pdf_path, printer_name
            ], check=True)
        except Exception as e:
            print(f"印刷エラー: {e}")

        summary = f"""📄 受付内容：
受付番号：{receipt_id}
電話番号：{user_data[user_id]['phone']}
受け取り日時：{user_data[user_id]['pickup_time']}
"""

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ ありがとうございます！以下の内容で受付しました：\n{summary}")
        )

if __name__ == "__main__":
    app.run(debug=True)
