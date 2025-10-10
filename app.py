import os, time, logging
from urllib.parse import urljoin, quote, urlparse
from functools import wraps

import requests
from flask import Flask, request, Response, render_template
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---- .env 読み込み（ローカル用） ----
load_dotenv()

# ---- 設定 ----
ADMIN_USER = os.environ.get("PB_USER", "admin")
ADMIN_PASS = os.environ.get("PB_PASS", "password")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
CACHE_MAX = int(os.environ.get("CACHE_MAX", "200"))

# 教育用の安全なドメインのみ許可
WHITELIST = {
    "example.com",
    "www.example.com",
}

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ---- キャッシュ ----
_cache = {}

def cache_get(url):
    entry = _cache.get(url)
    if not entry:
        return None
    if time.time() - entry["time"] > CACHE_TTL:
        _cache.pop(url, None)
        return None
    return entry["resp"]

def cache_set(url, resp):
    if len(_cache) >= CACHE_MAX:
        oldest = min(_cache.items(), key=lambda kv: kv[1]["time"])[0]
        _cache.pop(oldest, None)
    _cache[url] = {"time": time.time(), "resp": resp}

# ---- 認証 ----
def check_auth(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response("認証が必要です", 401, {"WWW-Authenticate": 'Basic realm="Login Required"'})
        return f(*args, **kwargs)
    return decorated

# ---- ホワイトリスト ----
def is_whitelisted(target_url):
    try:
        host = urlparse(target_url).hostname
        return host in WHITELIST
    except Exception:
        return False

# ---- サイト取得 ----
def safe_fetch(url, method="GET", data=None):
    headers = {"User-Agent": "EducationalProxy/1.0"}
    if method == "POST":
        return requests.post(url, data=data, headers=headers, timeout=15, verify=True)
    return requests.get(url, headers=headers, timeout=15, verify=True)

# ---- HTML 書き換え ----
def rewrite_html(target_url, text):
    soup = BeautifulSoup(text, "html.parser")
    base_tag = soup.new_tag("base", href=target_url)
    if soup.head:
        soup.head.insert(0, base_tag)
    else:
        soup.insert(0, base_tag)

    for tag in soup.find_all(["a", "img", "script", "link", "form"]):
        for attr in ("href", "src", "action"):
            if tag.has_attr(attr):
                val = tag[attr]
                if not val or val.strip().lower().startswith(("javascript:", "data:")):
                    continue
                try:
                    abs_url = urljoin(target_url, val)
                    tag[attr] = "/proxy?url=" + quote(abs_url, safe="")
                except Exception:
                    continue

    inject = """
<script>
(function(){
  const origFetch=window.fetch;
  window.fetch=function(url,options){
    try{
      const abs=new URL(url,location.href).href;
      const p='/proxy?url='+encodeURIComponent(abs);
      if(options && options.method && options.method.toUpperCase()==='POST')
        return origFetch(p,{method:'POST',body:options.body});
      return origFetch(p);
    }catch(e){return origFetch(url,options);}
  };
  const origOpen=XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open=function(m,u,...r){
    try{
      const abs=new URL(u,location.href).href;
      const p='/proxy?url='+encodeURIComponent(abs);
      return origOpen.call(this,m,p,...r);
    }catch(e){return origOpen.call(this,m,u,...r);}
  };
})();
</script>
"""
    if soup.body:
        soup.body.append(BeautifulSoup(inject, "html.parser"))
    else:
        soup.append(BeautifulSoup(inject, "html.parser"))
    return str(soup)

# ---- ルート ----
@app.route("/", methods=["GET", "HEAD"])
def index():
    if request.method == "HEAD":
        return "", 200
    return render_template("index.html")

# ---- プロキシ ----
@app.route("/proxy", methods=["GET", "POST"])
@requires_auth
def proxy():
    target_url = request.args.get("url") or request.form.get("url")
    if not target_url:
        return render_template("error.html", message="URLが指定されていません。"), 400
    if not is_whitelisted(target_url):
        return render_template("error.html", message="このドメインは許可されていません。"), 403

    cached = cache_get(target_url)
    if cached:
        resp = cached
    else:
        try:
            if request.method == "POST":
                resp = safe_fetch(target_url, "POST", request.form)
            else:
                resp = safe_fetch(target_url)
            if resp.status_code == 200:
                cache_set(target_url, resp)
        except requests.RequestException as e:
            return render_template("error.html", message=f"サイト取得に失敗しました: {e}"), 502

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        try:
            html = rewrite_html(target_url, resp.text)
            return Response(html, content_type="text/html; charset=utf-8")
        except Exception as e:
            return render_template("error.html", message=f"HTML処理エラー: {e}"), 500

    response = Response(resp.content, content_type=content_type)
    if resp.headers.get("Content-Length"):
        response.headers["Content-Length"] = resp.headers["Content-Length"]
    return response

# ---- エラーハンドラ ----
@app.errorhandler(404)
def notfound(e):
    return render_template("error.html", message="ページが見つかりません。"), 404

@app.errorhandler(500)
def internal(e):
    return render_template("error.html", message="サーバー内部エラーが発生しました。"), 500

@app.route("/health")
def health():
    return "ok", 200

# ---- メイン ----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))  # Renderが割り当てるポートを使う
    app.run(host="0.0.0.0", port=port, debug=False)
