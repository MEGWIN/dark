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

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
UPDATE_INTERVAL = 5 

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
                    msg = item["snippet"].get("displayMessage", "")
                    author = item["authorDetails"]["displayName"] # ★名前を取得
                    snippet_type = item["snippet"]["type"]

                    if snippet_type == "superChatEvent":
                        details = item["snippet"]["superChatDetails"]
                        amt = details["amountDisplayString"]
                        print(f"💰 SP: {author} {amt}")
                        # ★名前に金額も含める
                        display_name = f"{author} ({amt})"
                        if "10,000" in amt or "10000" in amt: 
                            await manager.broadcast(json.dumps({"type": "heal", "amount": 10000, "user": display_name}))
                        else: 
                            await manager.broadcast(json.dumps({"type": "heal", "amount": 1000, "user": display_name}))
                    
                    else:
                        # ★キーワードに「闇」を追加
                        damage_words = ["闇", "ダーク", "終わらせろ", "終了", "つまらん", "帰れ", "オワコン"]
                        heal_words = ["光", "ライト", "希望", "頑張れ", "応援", "まだ"]

                        if any(w in msg for w in damage_words):
                            print(f"👿 ANTI: {msg}")
                            await manager.broadcast(json.dumps({"type": "damage", "amount": 500, "user": author}))
                        
                        elif any(w in msg for w in heal_words):
                            print(f"😇 HEAL: {msg}")
                            await manager.broadcast(json.dumps({"type": "heal", "amount": 500, "user": author}))

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
    # 手動テストの場合は名前を「MEGWIN(TEST)」にする
    data["user"] = "MEGWIN(TEST)"
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
