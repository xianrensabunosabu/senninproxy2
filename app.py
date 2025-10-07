from flask import Flask, request, Response, render_template
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
from functools import lru_cache

app = Flask(__name__)

# -------------------------------
# メモリキャッシュ
# -------------------------------
cache = {}

def fetch_url(url, method="GET", data=None, headers=None):
    if url in cache:
        return cache[url]
    try:
        headers = headers or {"User-Agent": "Mozilla/5.0"}
        if method=="POST":
            resp = requests.post(url, data=data, headers=headers, timeout=10, verify=False)
        else:
            resp = requests.get(url, headers=headers, timeout=10, verify=False)
        cache[url] = resp
        return resp
    except Exception as e:
        print(f"[ERROR] fetch_url failed: {e}")
        return None

# -------------------------------
# ルート
# -------------------------------
@app.route("/", methods=["GET","HEAD"])
def index():
    if request.method=="HEAD":
        return "", 200
    return render_template("index.html")

# -------------------------------
# プロキシ
# -------------------------------
@app.route("/proxy", methods=["GET","POST"])
def proxy():
    target_url = request.args.get("url") or request.form.get("url")
    if not target_url:
        return "<h3>Error: URL not specified</h3>", 400

    method = request.method
    form_data = request.form if method=="POST" else None

    resp = fetch_url(target_url, method, form_data)
    if not resp:
        return f"<pre>Failed to fetch {target_url}</pre>", 500

    content_type = resp.headers.get("Content-Type","")

    # HTMLの場合は書き換え
    if "text/html" in content_type:
        soup = BeautifulSoup(resp.text,"html.parser")
        base_tag = soup.new_tag("base", href=target_url)
        if soup.head:
            soup.head.insert(0, base_tag)
        else:
            soup.insert(0, base_tag)

        # 全リンク/フォーム/スクリプト/画像をサーバー経由
        for tag in soup.find_all(["a","img","script","link","form"]):
            for attr in ["href","src","action"]:
                if tag.has_attr(attr):
                    abs_url = urljoin(target_url, tag[attr])
                    tag[attr] = '/proxy?url=' + quote(abs_url)

        # fetch/XHR書き換え
        inject_js="""
<script>
const originalFetch=window.fetch;
window.fetch=function(url,options){
  const proxyUrl='/proxy?url='+encodeURIComponent(new URL(url,location.href).href);
  if(options&&options.method==='POST'){
    return originalFetch(proxyUrl,{method:'POST',body:options.body});
  }
  return originalFetch(proxyUrl);
};
const origOpen=XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open=function(m,u,...r){
  const proxyUrl='/proxy?url='+encodeURIComponent(new URL(u,location.href).href);
  return origOpen.call(this,m,proxyUrl,...r);
};
</script>
"""
        if soup.body:
            soup.body.append(BeautifulSoup(inject_js,"html.parser"))
        else:
            soup.append(BeautifulSoup(inject_js,"html.parser"))

        return Response(str(soup), content_type="text/html; charset=utf-8")

    # HTML以外（画像/動画/JS/CSS）はバイナリそのまま返す
    response = Response(resp.content, content_type=content_type)
    if resp.headers.get("Content-Length"):
        response.headers["Content-Length"] = resp.headers["Content-Length"]
    return response

# -------------------------------
# ヘルスチェック
# -------------------------------
@app.route("/health")
def health():
    return "ok", 200

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000)
