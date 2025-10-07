from flask import Flask, request, Response, render_template
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
from functools import lru_cache

app = Flask(__name__)

# -------------------------------
# 軽量キャッシュ（最大100件）
# -------------------------------
@lru_cache(maxsize=100)
def fetch_page(url, method="GET", data=None, headers=None):
    try:
        headers = headers or {"User-Agent": "Mozilla/5.0"}
        if method == "POST":
            resp = requests.post(url, data=data, headers=headers, timeout=10)
        else:
            resp = requests.get(url, headers=headers, timeout=10)
        return resp
    except Exception:
        return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/proxy", methods=["GET", "POST"])
def proxy():
    target_url = request.args.get("url") or request.form.get("url")
    if not target_url:
        return "URL not specified.", 400

    method = request.method
    form_data = request.form if method == "POST" else None

    resp = fetch_page(target_url, method, form_data)
    if not resp:
        return f"<pre>Failed to load {target_url}</pre>", 500

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        soup = BeautifulSoup(resp.text, "html.parser")

        # 各種タグのURLを/proxy経由に書き換え
        for tag, attr in [
            ("a", "href"),
            ("img", "src"),
            ("script", "src"),
            ("link", "href"),
            ("form", "action"),
        ]:
            for t in soup.find_all(tag):
                if t.has_attr(attr):
                    abs_url = urljoin(target_url, t[attr])
                    t[attr] = f"/proxy?url={quote(abs_url)}"

        # JavaScript内のfetchやXHRをプロキシ化するスクリプトを注入
        inject_js = """
        <script>
        const originalFetch = window.fetch;
        window.fetch = function(url, options) {
            const proxyUrl = '/proxy?url=' + encodeURIComponent(new URL(url, location.href).href);
            if (options && options.method === 'POST') {
                return originalFetch(proxyUrl, {method:'POST', body: options.body});
            }
            return originalFetch(proxyUrl);
        };
        const origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(m, u, ...r) {
            const proxyUrl = '/proxy?url=' + encodeURIComponent(new URL(u, location.href).href);
            return origOpen.call(this, m, proxyUrl, ...r);
        };
        </script>
        """
        soup.body.append(BeautifulSoup(inject_js, "html.parser"))
        return Response(str(soup), content_type="text/html; charset=utf-8")

    # HTML以外（画像・CSS・JSなど）はそのまま返す
    return Response(resp.content, content_type=content_type)


# -------------------------------
# GunicornでRender対応
# -------------------------------
if __name__ == "__main__":
    # 開発時のみローカル実行
    app.run(host="0.0.0.0", port=5000, debug=True)
