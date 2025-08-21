from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage, FollowEvent
import os
import datetime
import subprocess
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("必要な環境変数が設定されていません")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ユーザーデータ保持用
user_data = {}
daily_counter = {}

# PDF保存先
PDF_SAVE_DIR = r"C:\print_bot\処方箋画像"
os.makedirs(PDF_SAVE_DIR, exist_ok=True)

# SumatraPDFパスとプリンタ名
SUMATRA_PATH = r"C:\Users\gwincl3\AppData\Local\SumatraPDF\SumatraPDF.exe"
PRINTER_NAME = "RICOH SG 3200 RPCS-R調剤"

def generate_receipt_id():
    today = datetime.datetime.now().strftime("%Y%m%d")
    count = daily_counter.get(today, 0) + 1
    daily_counter[today] = count
    return f"{today}{count:04d}"

def create_pdf_single_page(pdf_path, image_path, receipt_id, phone, pickup_time):
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    # ヘッダー情報
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 50, f"受付番号: {receipt_id}")
    c.drawString(50, height - 70, f"電話番号: {phone}")
    c.drawString(50, height - 90, f"受け取り日時: {pickup_time}")

    # 画像描画
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
        TextSendMessage(text="いずみ薬局 テスト店です。処方箋受付のために個人情報を使用します。\n同意される方は「同意」と返信してください。")
    )

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    message_id = event.message.id

    # 同意確認
    if not user_data.get(user_id, {}).get('consent'):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="ご利用には同意が必要です。「同意」と送信してください。")
        )
        return

    receipt_id = user_data[user_id].get("receipt_id") or generate_receipt_id()
    user_data[user_id]["receipt_id"] = receipt_id

    # 画像を一時保存
    image_content = line_bot_api.get_message_content(message_id)
    image_idx = len(user_data[user_id].get("images", [])) + 1
    image_path = f"{PDF_SAVE_DIR}\\{receipt_id}_{image_idx}.jpg"
    with open(image_path, 'wb') as f:
        for chunk in image_content.iter_content():
            f.write(chunk)

    user_data[user_id].setdefault("images", []).append(image_path)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"📸 画像を受け取りました。必要に応じて続けて送信してください。")
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id not in user_data:
        user_data[user_id] = {}

    # 同意処理
    if 'consent' not in user_data[user_id]:
        if text.lower() in ['同意', 'はい', 'ok', '了解']:
            user_data[user_id]['consent'] = True
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="✅ ご同意ありがとうございます。処方箋の受付を開始できます。")
            )
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
            TextSendMessage(text="📞 電話番号を確認しました。次に受け取り希望日時を入力してください。")
        )
        return

    # 受け取り日時入力
    if 'pickup_time' not in user_data[user_id]:
        user_data[user_id]['pickup_time'] = text

        receipt_id = user_data[user_id]['receipt_id']
        phone = user_data[user_id]['phone']
        pickup_time = user_data[user_id]['pickup_time']
        images = user_data[user_id].get("images", [])

        # 画像ごとにPDF作成・印刷
        for idx, img_path in enumerate(images):
            pdf_path = f"{PDF_SAVE_DIR}\\{receipt_id}_{idx + 1}.pdf"
            create_pdf_single_page(pdf_path, img_path, receipt_id, phone, pickup_time)

            # SumatraPDFで印刷
            try:
                subprocess.run([SUMATRA_PATH, "-print-to", PRINTER_NAME, pdf_path], check=True)
            except Exception as e:
                print(f"印刷エラー: {e}")

        summary = f"受付番号：{receipt_id}\n画像枚数：{len(images)}枚\n電話番号：{phone}\n受け取り日時：{pickup_time}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ 受付完了しました：\n{summary}")
        )

        # ユーザーデータ削除
        del user_data[user_id]

if __name__ == "__main__":
    app.run(debug=True)
