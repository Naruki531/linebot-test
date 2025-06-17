from flask import Flask, request, abort

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200

@app.route("/callback", methods=["POST"])
def callback():
    # LINEからのリクエストか確認（セキュリティのため）
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    # ここに署名検証やイベント処理を書く（後で実装）
    print("Received body:", body)

    return "OK", 200
