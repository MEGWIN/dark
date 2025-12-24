import os
import json
import asyncio
import requests
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from pydantic import BaseModel

# --- 設定 ---
# Railwayの金庫からキーを取り出す（なければエラー回避のため空文字）
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
UPDATE_INTERVAL = 5 # 監視間隔（秒）

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory="templates")

# --- サーバーのメモリ ---
server_state = {
    "is_active": True,       # システムON/OFF
    "video_id": "",          # YouTubeビデオID
    "chat_id": None,         # チャットID（自動取得）
    "next_page_token": None  # 次の読み込み位置
}

# WebSocket管理
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

# --- YouTube監視タスク (裏側でずっと動くロボット) ---
async def monitor_youtube():
    print("🤖 監視ロボット: 起動しました")
    
    while True:
        # 1. システムがOFF、またはビデオIDがない、またはキーがない時はお休み
        if not server_state["is_active"] or not server_state["video_id"] or not API_KEY:
            await asyncio.sleep(5)
            continue

        # 2. チャットIDがまだない場合、取りに行く
        if not server_state["chat_id"]:
            print(f"🤖 監視ロボット: チャットIDを探しています... ({server_state['video_id']})")
            try:
                url = "https://www.googleapis.com/youtube/v3/videos"
                params = {"part": "liveStreamingDetails", "id": server_state["video_id"], "key": API_KEY}
                # ブロック回避のためスレッドで実行
                resp = await asyncio.to_thread(requests.get, url, params=params)
                data = resp.json()
                items = data.get("items", [])
                if items:
                    server_state["chat_id"] = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                    print(f"✅ チャット特定成功: {server_state['chat_id']}")
                else:
                    print("⚠️ チャットが見つかりません (配信してない？)")
                    await asyncio.sleep(10) # 失敗したら少し長く待つ
                    continue
            except Exception as e:
                print(f"エラー: {e}")
                await asyncio.sleep(10)
                continue

        # 3. コメントを取得してゲームに反映
        try:
            url = "https://www.googleapis.com/youtube/v3/liveChat/messages"
            params = {"liveChatId": server_state["chat_id"], "part": "snippet,authorDetails", "key": API_KEY}
            if server_state["next_page_token"]:
                params["pageToken"] = server_state["next_page_token"]

            resp = await asyncio.to_thread(requests.get, url, params=params)
            data = resp.json()

            if "items" in data:
                for item in data["items"]:
                    msg = item["snippet"].get("displayMessage", "")
                    author = item["authorDetails"]["displayName"]
                    snippet_type = item["snippet"]["type"]

                    # スパチャ判定
                    if snippet_type == "superChatEvent":
                        details = item["snippet"]["superChatDetails"]
                        amt = details["amountDisplayString"]
                        print(f"💰 SP: {author} {amt}")
                        if "10,000" in amt or "10000" in amt: 
                            await manager.broadcast(json.dumps({"type": "heal", "amount": 10000}))
                        else: 
                            await manager.broadcast(json.dumps({"type": "heal", "amount": 1000}))
                    
                    # 通常コメント判定
                    else:
                        if any(w in msg for w in ["終わらせろ", "終了", "つまらん", "帰れ", "オワコン"]):
                            print(f"👿 ANTI: {msg}")
                            await manager.broadcast(json.dumps({"type": "damage", "amount": 500}))
                        elif any(w in msg for w in ["頑張れ", "応援", "まだ", "光"]):
                            print(f"😇 HEAL: {msg}")
                            await manager.broadcast(json.dumps({"type": "heal", "amount": 500}))

                server_state["next_page_token"] = data.get("nextPageToken")
            
            else:
                # データが取れなかった場合（配信終了など）、チャットIDをリセットして再検索へ
                if "error" in data:
                    print("⚠️ APIエラー、再接続します")
                    server_state["chat_id"] = None
                    server_state["next_page_token"] = None

        except Exception as e:
            print(f"監視エラー: {e}")

        # 待機
        await asyncio.sleep(UPDATE_INTERVAL)

# --- サーバー起動時にロボットも起動 ---
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_youtube())


# --- 以下、Webサーバー機能 ---

class VideoIdReq(BaseModel):
    video_id: str

@app.get("/", response_class=HTMLResponse)
async def get_obs(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def get_admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 手動操作用API
@app.post("/api/action")
async def action(request: Request):
    if not server_state["is_active"]: return {"status": "ignored"}
    data = await request.json()
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
    server_state["chat_id"] = None       # IDが変わったらチャットIDもリセット
    server_state["next_page_token"] = None
    print(f"Video ID Updated: {req.video_id}")
    return server_state

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))