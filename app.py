import os
import time
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage
from reportlab.pdfgen import canvas
from PIL import Image
import subprocess

# 環境変数または直接記述
CHANNEL_ACCESS_TOKEN = 'LINE_CHANNEL_ACCESS_TOKEN'
CHANNEL_SECRET = 'LINE_CHANNEL_SECRET'

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 保存先フォルダとPDF出力先
SAVE_FOLDER = r'C:\print_bot\処方箋画像'
PDF_PATH = os.path.join(SAVE_FOLDER, 'output.pdf')
SUMATRA_PATH = r'C:\Users\gwincl3\AppData\Local\SumatraPDF\SumatraPDF.exe'
PRINTER_NAME = 'RICOH SG 3200 RPCS-R調剤'

# フォルダ作成
os.makedirs(SAVE_FOLDER, exist_ok=True)

app = Flask(__name__)

# ユーザーごとの状態保持
user_data = {}

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text == '印刷':
        if user_id not in user_data or not user_data[user_id]['images']:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text='画像が登録されていません。先に画像を送ってください。')
            )
            return

        images = user_data[user_id]['images']
        pdf_path = PDF_PATH

        # PDF作成
        create_pdf(images, pdf_path)

        # SumatraPDFで印刷
        try:
            cmd = [
                SUMATRA_PATH,
                "-print-to", PRINTER_NAME,
                pdf_path
            ]
            subprocess.run(cmd, check=True)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text='印刷しました。')
            )
        except Exception as e:
            print(f"印刷エラー: {e}")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text='印刷中にエラーが発生しました。')
            )

        # 状態リセット
        del user_data[user_id]

    elif text == 'キャンセル':
        if user_id in user_data:
            del user_data[user_id]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='キャンセルしました。')
        )

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='画像を送信後「印刷」と入力してください。キャンセルする場合は「キャンセル」と入力してください。')
        )

@handler.add(MessageEvent, message=TextMessage)
def handle_image(event):
    if event.message.type != 'image':
        return

    user_id = event.source.user_id
    message_id = event.message.id

    # 保存先ファイル名
    timestamp = int(time.time())
    file_path = os.path.join(SAVE_FOLDER, f'{user_id}_{timestamp}.jpg')

    # LINE画像取得
    content = line_bot_api.get_message_content(message_id)
    with open(file_path, 'wb') as f:
        for chunk in content.iter_content():
            f.write(chunk)

    # ユーザーデータに追加
    if user_id not in user_data:
        user_data[user_id] = {'images': []}
    user_data[user_id]['images'].append(file_path)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text='画像を受け取りました。印刷するには「印刷」と入力してください。')
    )

def create_pdf(image_paths, pdf_path):
    c = canvas.Canvas(pdf_path)

    for img_path in image_paths:
        img = Image.open(img_path)
        img_width, img_height = img.size

        # A4 サイズ
        a4_width = 595
        a4_height = 842

        scale = min(a4_width / img_width, a4_height / img_height)
        new_width = img_width * scale
        new_height = img_height * scale
        x = (a4_width - new_width) / 2
        y = (a4_height - new_height) / 2

        c.drawImage(img_path, x, y, width=new_width, height=new_height)
        c.showPage()

    c.save()

if __name__ == "__main__":
    app.run(debug=True)
