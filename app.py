from flask import Flask, request, render_template, jsonify, Response
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urlparse, urljoin

app = Flask(__name__)

# --- ログを減らして静かに運用 ---
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- サーバーキャッシュ（簡易） ---
cache = {}

# --- ルート（UI） ---
@app.route("/", methods=["GET", "HEAD"])
def index():
    if request.method == "HEAD":
        return "", 200  # Renderのヘルスチェック対応
    return render_template("index.html")

# --- プロキシ経由でWebページ取得 ---
@app.route("/proxy", methods=["GET", "POST"])
def proxy():
    target_url = request.args.get("url") or request.form.get("url")
    if not target_url:
        return "Error: No URL provided", 400

    # キャッシュ確認
    if target_url in cache:
        html = cache[target_url]
        return Response(html, mimetype="text/html")

    try:
        headers = {"User-Agent": request.headers.get("User-Agent", "ProxyBrowser/1.0")}
        if request.method == "POST":
            resp = requests.post(target_url, data=request.form, headers=headers, timeout=10)
        else:
            resp = requests.get(target_url, headers=headers, timeout=10)

        # HTML以外はそのまま返す（画像など）
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return Response(resp.content, mimetype=content_type)

        # HTML書き換え
        soup = BeautifulSoup(resp.text, "html.parser")
        base_tag = soup.new_tag("base", href=target_url)
        if soup.head:
            soup.head.insert(0, base_tag)
        else:
            head = soup.new_tag("head")
            head.insert(0, base_tag)
            soup.insert(0, head)

        # 相対リンクを絶対URLに
        for tag in soup.find_all(["a", "img", "script", "link", "form"]):
            for attr in ["href", "src", "action"]:
                if tag.has_attr(attr):
                    tag[attr] = urljoin(target_url, tag[attr])

        html = str(soup)
        cache[target_url] = html
        return Response(html, mimetype="text/html")

    except Exception as e:
        return f"<h3>Proxy Error:</h3><pre>{e}</pre>", 500


# --- ヘルスチェック用エンドポイント ---
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
