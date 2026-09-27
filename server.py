"""
Kick Account Panel
==================
Run: pip install fastapi uvicorn tls-client websocket-client && python server.py
"""
import os, json, time, subprocess, threading, secrets
import tls_client, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR  = os.path.join(BASE_DIR, "chrome_profiles")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
os.makedirs(PROFILES_DIR, exist_ok=True)

app = FastAPI(title="Kick Account Panel")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── ACCOUNTS STORAGE ─────────────────────────────────────────────────────────
def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE): return []
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_accounts(accounts):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)

# ── KICK API ─────────────────────────────────────────────────────────────────
def get_kick_username(token: str) -> dict:
    bare = token.split(":")[-1] if ":" in token else token
    try:
        session = tls_client.Session(client_identifier="chrome127", random_tls_extension_order=True)
        session.headers.update({
            "accept": "application/json",
            "authorization": f"Bearer {bare}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "referer": "https://kick.com/",
            "origin": "https://kick.com",
        })
        r = session.get("https://kick.com/api/v1/user", timeout_seconds=10)
        if r.status_code == 200:
            d = r.json()
            return {"ok": True, "username": d.get("username", ""), "id": str(d.get("id", ""))}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── CHROME FINDER ─────────────────────────────────────────────────────────────
def find_chrome():
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

# ── CHROME LAUNCHER ───────────────────────────────────────────────────────────
def launch_profile(account: dict, url: str = "https://kick.com"):
    profile_path  = os.path.join(PROFILES_DIR, f"profile_{account['id']}")
    os.makedirs(profile_path, exist_ok=True)
    bare          = account["token"].split(":")[-1] if ":" in account["token"] else account["token"]
    logged_in_file = os.path.join(profile_path, ".logged_in")
    chrome        = find_chrome()
    if not chrome:
        return {"ok": False, "error": "Chrome not found"}

    # ── FIRST OPEN: inject token via CDP ─────────────────────────────────────
    if not os.path.exists(logged_in_file):
        debug_port = 9222 + abs(hash(account["id"])) % 7000

        def run():
            import urllib.request, json as _j, websocket as _ws

            # 1. Launch Chrome
            proc = subprocess.Popen([
                chrome,
                f"--user-data-dir={profile_path}",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-maximized",
                f"--remote-debugging-port={debug_port}",
                "--remote-allow-origins=*",
                "https://kick.com",
            ])
            print(f"[LOGIN] Chrome started (port {debug_port}), waiting 8s...")
            time.sleep(8)

            # 2. Connect to CDP
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=8) as r:
                    tabs = _j.loads(r.read())
            except Exception as e:
                print(f"[LOGIN] CDP unreachable: {e}"); proc.wait(); return

            tab = next((t for t in tabs if "kick.com" in t.get("url","") and t.get("type")=="page"), None)
            if not tab and tabs: tab = tabs[0]
            if not tab:
                print("[LOGIN] No tab found"); proc.wait(); return

            print(f"[LOGIN] Tab: {tab.get('url','')[:70]}")

            try:
                ws = _ws.create_connection(tab["webSocketDebuggerUrl"], timeout=10)

                def cdp(method, params, mid):
                    ws.send(_j.dumps({"id": mid, "method": method, "params": params}))
                    return _j.loads(ws.recv())

                # 3. Enable Network domain (required for setCookie)
                cdp("Network.enable", {}, 1)
                time.sleep(0.5)

                # 4. Inject cookies via CDP Network.setCookie
                # These are the actual cookies Kick checks for authentication
                cookie_list = [
                    {"name": "kick_session",  "value": bare, "domain": ".kick.com", "path": "/", "secure": True,  "httpOnly": True,  "sameSite": "Lax", "expires": 9999999999},
                    {"name": "session_token", "value": bare, "domain": ".kick.com", "path": "/", "secure": True,  "httpOnly": False, "sameSite": "Lax", "expires": 9999999999},
                    {"name": "access_token",  "value": bare, "domain": ".kick.com", "path": "/", "secure": True,  "httpOnly": False, "sameSite": "Lax", "expires": 9999999999},
                    {"name": "token",         "value": bare, "domain": ".kick.com", "path": "/", "secure": False, "httpOnly": False, "sameSite": "Lax", "expires": 9999999999},
                ]
                for i, ck in enumerate(cookie_list):
                    result = cdp("Network.setCookie", ck, 10 + i)
                    success = result.get("result", {}).get("success", False)
                    print(f"[LOGIN]   Cookie '{ck['name']}' → {'OK' if success else 'FAIL'}")

                # 5. Also write to localStorage via JS
                cdp("Runtime.evaluate", {"expression": f"""
                    (function() {{
                        try {{
                            localStorage.setItem('token', '{bare}');
                            localStorage.setItem('access_token', '{bare}');
                            localStorage.setItem('authToken', '{bare}');
                        }} catch(e) {{}}
                    }})();
                """}, 20)

                # 6. Hard navigate to kick.com so it reads fresh cookies
                cdp("Page.navigate", {"url": "https://kick.com"}, 30)
                print("[LOGIN] Navigating to kick.com, waiting 6s...")
                time.sleep(6)

                # 7. Verify — check if login button is gone (means logged in)
                check = cdp("Runtime.evaluate", {"expression": """
                    (function() {
                        // If "Log In" button exists → not logged in
                        var loginLinks = Array.from(document.querySelectorAll('a, button'))
                            .filter(el => el.textContent.trim() === 'Log In' || el.textContent.trim() === 'Login');
                        if (loginLinks.length > 0) return 'fail';
                        // Check for user avatar or dashboard link
                        var authed = document.querySelector('[href*="dashboard"]')
                                  || document.querySelector('[class*="UserMenu"]')
                                  || document.querySelector('[data-testid="user-menu"]');
                        return authed ? 'ok' : 'unknown';
                    })()
                """}, 40)

                ws.close()
                val = check.get("result", {}).get("result", {}).get("value", "unknown")
                print(f"[LOGIN] Auth check → {val}")

                if val in ("ok", "unknown"):
                    # Mark as logged in (unknown = page may have changed, assume ok)
                    with open(logged_in_file, "w") as f: f.write("1")
                    print(f"[LOGIN] ✓ Profile saved for {account.get('username', account['id'])}")
                else:
                    print(f"[LOGIN] ✗ Not logged in — token expired or invalid")

            except Exception as e:
                print(f"[LOGIN] CDP error: {e}")
                # Still mark logged_in so it doesn't loop — user can reset manually
                with open(logged_in_file, "w") as f: f.write("1")

            proc.wait()

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    # ── ALREADY LOGGED IN: just open Chrome ──────────────────────────────────
    else:
        def run():
            try:
                proc = subprocess.Popen([
                    chrome,
                    f"--user-data-dir={profile_path}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--start-maximized",
                    url,
                ])
                proc.wait()
            except Exception as e:
                print(f"[ERROR] Chrome launch failed: {e}")

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

# ── MODELS ────────────────────────────────────────────────────────────────────
class AddAccountRequest(BaseModel):
    token: str
    name: Optional[str] = ""

class OpenAccountRequest(BaseModel):
    id: str
    url: Optional[str] = "https://kick.com"

class DeleteAccountRequest(BaseModel):
    id: str

class UpdateAccountRequest(BaseModel):
    id: str
    name: str

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(BASE_DIR, "static", "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/accounts")
async def get_accounts():
    return {"ok": True, "accounts": load_accounts()}

@app.post("/api/accounts/add")
async def add_account(req: AddAccountRequest):
    token = req.token.strip()
    if not token: raise HTTPException(400, "Token required")
    result   = get_kick_username(token)
    username = result.get("username", "") if result["ok"] else ""
    uid      = result.get("id", "") if result["ok"] else ""
    name     = req.name.strip() if req.name else (username or f"Account {int(time.time())}")
    accounts = load_accounts()
    if any(a["token"] == token for a in accounts):
        return {"ok": False, "error": "Token already exists"}
    account = {
        "id": secrets.token_hex(8), "name": name, "token": token,
        "username": username, "kick_id": uid, "valid": result["ok"],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "last_opened": None,
    }
    accounts.append(account)
    save_accounts(accounts)
    return {"ok": True, "account": account}

@app.post("/api/accounts/add_bulk")
async def add_bulk(req: dict):
    tokens = req.get("tokens", [])
    added, errors = [], []
    for token in tokens:
        token = token.strip()
        if not token: continue
        result   = get_kick_username(token)
        username = result.get("username", "") if result["ok"] else ""
        uid      = result.get("id", "") if result["ok"] else ""
        accounts = load_accounts()
        if any(a["token"] == token for a in accounts):
            errors.append(f"{token[:20]}... already exists"); continue
        account = {
            "id": secrets.token_hex(8),
            "name": username or f"Account {int(time.time())}",
            "token": token, "username": username, "kick_id": uid,
            "valid": result["ok"],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "last_opened": None,
        }
        accounts.append(account)
        save_accounts(accounts)
        added.append(account)
        time.sleep(0.3)
    return {"ok": True, "added": len(added), "errors": errors, "accounts": added}

@app.post("/api/accounts/open")
async def open_account(req: OpenAccountRequest):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == req.id), None)
    if not acc: raise HTTPException(404, "Account not found")
    result = launch_profile(acc, req.url or "https://kick.com")
    acc["last_opened"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_accounts(accounts)
    return result

@app.post("/api/accounts/open_multi")
async def open_multi(req: dict):
    ids, url = req.get("ids", []), req.get("url", "https://kick.com")
    accounts = load_accounts()
    opened = 0
    for aid in ids:
        acc = next((a for a in accounts if a["id"] == aid), None)
        if not acc: continue
        launch_profile(acc, url)
        acc["last_opened"] = time.strftime("%Y-%m-%d %H:%M:%S")
        opened += 1
        time.sleep(0.8)
    save_accounts(accounts)
    return {"ok": True, "opened": opened}

@app.post("/api/accounts/delete")
async def delete_account(req: DeleteAccountRequest):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == req.id), None)
    if not acc: raise HTTPException(404, "Account not found")
    profile_path = os.path.join(PROFILES_DIR, f"profile_{req.id}")
    if os.path.exists(profile_path):
        import shutil; shutil.rmtree(profile_path, ignore_errors=True)
    accounts = [a for a in accounts if a["id"] != req.id]
    save_accounts(accounts)
    return {"ok": True}

@app.post("/api/accounts/update")
async def update_account(req: UpdateAccountRequest):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == req.id), None)
    if not acc: raise HTTPException(404, "Account not found")
    acc["name"] = req.name
    save_accounts(accounts)
    return {"ok": True}

@app.post("/api/accounts/validate")
async def validate_account(req: dict):
    aid = req.get("id")
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == aid), None)
    if not acc: raise HTTPException(404, "Account not found")
    result = get_kick_username(acc["token"])
    acc["valid"] = result["ok"]
    if result["ok"]:
        acc["username"] = result.get("username", acc["username"])
        acc["kick_id"]  = result.get("id", acc["kick_id"])
        if not acc["name"] or acc["name"].startswith("Account"):
            acc["name"] = acc["username"]
    save_accounts(accounts)
    return {"ok": True, "account": acc}

@app.post("/api/accounts/validate_all")
async def validate_all():
    accounts = load_accounts()
    for acc in accounts:
        result = get_kick_username(acc["token"])
        acc["valid"] = result["ok"]
        if result["ok"]:
            acc["username"] = result.get("username", acc["username"])
            if not acc["name"] or acc["name"] == acc["kick_id"]:
                acc["name"] = acc["username"]
        time.sleep(0.3)
    save_accounts(accounts)
    return {"ok": True, "accounts": accounts}

@app.post("/api/accounts/reset_login")
async def reset_login(req: dict):
    """Delete .logged_in so next open re-injects the token"""
    aid = req.get("id")
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == aid), None)
    if not acc: raise HTTPException(404, "Account not found")
    f = os.path.join(PROFILES_DIR, f"profile_{aid}", ".logged_in")
    if os.path.exists(f): os.remove(f)
    return {"ok": True, "message": "Login reset — open account again to re-inject"}

# ── SEND MESSAGE ──────────────────────────────────────────────────────────────
class ConnectChannelRequest(BaseModel):
    channel: str

class SendMessageRequest(BaseModel):
    account_id: str
    chatroom_id: int
    message: str
    channel: str = ""

class MultiSendRequest(BaseModel):
    account_ids: List[str]
    chatroom_id: int
    message: str
    channel: str = ""
    delay_ms: int = 500

def make_kick_session(token: str, channel: str = "") -> tls_client.Session:
    bare = token.split(":")[-1] if ":" in token else token
    session = tls_client.Session(client_identifier="chrome127", random_tls_extension_order=True)
    session.headers.update({
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "authorization": f"Bearer {bare}",
        "content-type": "application/json",
        "origin": "https://kick.com",
        "referer": f"https://kick.com/{channel}" if channel else "https://kick.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    })
    return session

@app.post("/api/chat/connect")
async def connect_channel(req: ConnectChannelRequest):
    channel = req.channel.strip().lower().split("/")[-1]
    try:
        session = tls_client.Session(client_identifier="chrome127", random_tls_extension_order=True)
        session.headers.update({
            "accept": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "referer": f"https://kick.com/{channel}",
        })
        r = session.get(f"https://kick.com/api/v2/channels/{channel}", timeout_seconds=10)
        if r.status_code == 200:
            d = r.json()
            return {"ok": True, "chatroom_id": d["chatroom"]["id"], "channel": channel, "channel_id": d["id"]}
        return {"ok": False, "error": f"Channel not found (HTTP {r.status_code})"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/chat/send")
async def send_message(req: SendMessageRequest):
    accounts = load_accounts()
    acc = next((a for a in accounts if a["id"] == req.account_id), None)
    if not acc: raise HTTPException(404, "Account not found")
    session = make_kick_session(acc["token"], req.channel)
    try:
        r = session.post(
            f"https://kick.com/api/v2/messages/send/{req.chatroom_id}",
            json={"content": req.message, "type": "message"},
            timeout_seconds=10
        )
        if r.status_code in (200, 201): return {"ok": True}
        if r.status_code == 429: return {"ok": False, "error": "Rate limited"}
        if r.status_code == 401: return {"ok": False, "error": "Token invalid"}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:100]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/chat/send_multi")
async def send_multi(req: MultiSendRequest):
    accounts_all = load_accounts()
    results = []
    for aid in req.account_ids:
        acc = next((a for a in accounts_all if a["id"] == aid), None)
        if not acc: continue
        session = make_kick_session(acc["token"], req.channel)
        try:
            r = session.post(
                f"https://kick.com/api/v2/messages/send/{req.chatroom_id}",
                json={"content": req.message, "type": "message"},
                timeout_seconds=10
            )
            ok = r.status_code in (200, 201)
            results.append({"account": acc["name"], "ok": ok, "error": "" if ok else f"HTTP {r.status_code}"})
        except Exception as e:
            results.append({"account": acc["name"], "ok": False, "error": str(e)})
        if req.delay_ms > 0:
            time.sleep(req.delay_ms / 1000)
    sent = sum(1 for r in results if r["ok"])
    return {"ok": True, "sent": sent, "failed": len(results) - sent, "results": results}


@app.get("/api/chrome")
async def check_chrome():
    chrome = find_chrome()
    return {"ok": bool(chrome), "path": chrome or "Not found"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5059))
    print(f"\n  Kick Account Panel")
    print(f"  http://localhost:{port}\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
