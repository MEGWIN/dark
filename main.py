import os
import json
import asyncio
import requests
import csv
import datetime
import re # ★これが超重要！金額計算に使います
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from pydantic import BaseModel

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
UPDATE_INTERVAL = 5 
LOG_FILE = "stream_log.csv"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory="templates")

server_state = {
    "is_active": True,
    "video_id": "",
    "chat_id": None,
    "next_page_token": None
}

# --- ログ機能 ---
def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Time", "User", "Type", "Amount", "Money", "Message"])

def save_log(user, action_type, amount, money="", message=""):
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([now, user, action_type, amount, money, message])
    except Exception as e:
        print(f"ログ保存エラー: {e}")

init_log()

# ★金額計算ロジック（エラー対策済み）
def parse_money(money_str):
    try:
        # 数字以外を全部消す（例: "¥320" -> "320"）
        if not money_str: return 100
        nums = re.sub(r'[^\d]', '', str(money_str))
        if not nums: return 100 
        return int(nums)
    except Exception as e:
        print(f"⚠️ 金額計算エラー: {e}")
        return 100 # エラー時はとりあえず100円扱い

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: str):
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except:
                self.active_connections.remove(connection)

manager = ConnectionManager()

async def monitor_youtube():
    print("🤖 監視ロボット: 起動しました")
    while True:
        if not server_state["is_active"] or not server_state["video_id"] or not API_KEY:
            await asyncio.sleep(5)
            continue

        if not server_state["chat_id"]:
            try:
                url = "https://www.googleapis.com/youtube/v3/videos"
                params = {"part": "liveStreamingDetails", "id": server_state["video_id"], "key": API_KEY}
                resp = await asyncio.to_thread(requests.get, url, params=params)
                data = resp.json()
                items = data.get("items", [])
                if items:
                    server_state["chat_id"] = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                    print(f"✅ チャット特定成功: {server_state['chat_id']}")
                else:
                    await asyncio.sleep(10)
                    continue
            except Exception as e:
                print(f"エラー: {e}")
                await asyncio.sleep(10)
                continue

        try:
            url = "https://www.googleapis.com/youtube/v3/liveChat/messages"
            params = {"liveChatId": server_state["chat_id"], "part": "snippet,authorDetails", "key": API_KEY}
            if server_state["next_page_token"]:
                params["pageToken"] = server_state["next_page_token"]

            resp = await asyncio.to_thread(requests.get, url, params=params)
            data = resp.json()

            if "items" in data:
                for item in data["items"]:
                    try:
                        msg = item["snippet"].get("displayMessage", "")
                        author = item["authorDetails"]["displayName"]
                        icon_url = item["authorDetails"]["profileImageUrl"]
                        snippet_type = item["snippet"]["type"]

                        # ★スパチャ処理（ここを強化しました）
                        if snippet_type == "superChatEvent":
                            details = item["snippet"]["superChatDetails"]
                            amt_str = details["amountDisplayString"]
                            comment_text = details.get("userComment", "")
                            print(f"💰 SP検知: {author} {amt_str}")
                            
                            # 金額計算
                            money_val = parse_money(amt_str)
                            
                            # 効果量：金額 × 50 (OBS側で0.2倍されるので、実質10倍)
                            effect_amount = money_val * 50

                            payload = {
                                "type": "heal", 
                                "amount": effect_amount, 
                                "user": author,
                                "icon": icon_url,
                                "money": amt_str
                            }
                            
                            save_log(author, "SuperChat", payload["amount"], amt_str, comment_text)
                            await manager.broadcast(json.dumps(payload))
                            print(f"🚀 スパチャ反映完了: {effect_amount}ポイント") # 確認用ログ
                        
                        else:
                            # 通常コメント
                            damage_words = ["闇", "ダーク", "終わらせろ", "終了", "つまらん", "帰れ", "オワコン"]
                            heal_words = ["光", "ライト", "希望", "頑張れ", "応援", "まだ"]

                            if any(w in msg for w in damage_words):
                                print(f"👿 ANTI: {msg}")
                                save_log(author, "Damage", 500, "", msg)
                                await manager.broadcast(json.dumps({
                                    "type": "damage", "amount": 500, "user": author, "icon": icon_url
                                }))
                            
                            elif any(w in msg for w in heal_words):
                                print(f"😇 HEAL: {msg}")
                                save_log(author, "Heal", 500, "", msg)
                                await manager.broadcast(json.dumps({
                                    "type": "heal", "amount": 500, "user": author, "icon": icon_url
                                }))
                    
                    except Exception as e:
                        print(f"⚠️ 処理エラー(1件スキップ): {e}")
                        continue

                server_state["next_page_token"] = data.get("nextPageToken")
            else:
                if "error" in data:
                    server_state["chat_id"] = None
                    server_state["next_page_token"] = None

        except Exception as e:
            print(f"監視エラー: {e}")

        await asyncio.sleep(UPDATE_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_youtube())

class VideoIdReq(BaseModel):
    video_id: str

@app.get("/", response_class=HTMLResponse)
async def get_obs(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def get_admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/api/download_log")
async def download_log():
    if os.path.exists(LOG_FILE):
        return FileResponse(LOG_FILE, media_type='text/csv', filename=f"log_{datetime.datetime.now().strftime('%Y%m%d')}.csv")
    return {"error": "Log file not found"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/api/action")
async def action(request: Request):
    if not server_state["is_active"]: return {"status": "ignored"}
    data = await request.json()
    data["user"] = "MEGWIN(TEST)"
    data["icon"] = "https://cdn-icons-png.flaticon.com/512/1077/1077114.png"
    
    money_val = data.get("money", "")
    if not money_val and data["type"] == "heal" and data["amount"] >= 1000:
         money_val = "¥10,000"
         data["money"] = money_val
    
    save_log("MEGWIN(TEST)", data["type"], data["amount"], money_val, "TEST ACTION")
    await manager.broadcast(json.dumps(data))
    return {"status": "ok"}

@app.get("/api/status")
async def get_status():
    return server_state

@app.post("/api/toggle")
async def toggle_status():
    server_state["is_active"] = not server_state["is_active"]
    await manager.broadcast(json.dumps({"type": "status_change", "is_active": server_state["is_active"]}))
    return server_state

@app.post("/api/config_video")
async def set_video_id(req: VideoIdReq):
    server_state["video_id"] = req.video_id
    server_state["chat_id"] = None
    server_state["next_page_token"] = None
    return server_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
