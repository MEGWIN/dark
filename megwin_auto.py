import requests
import time
import json
import sys

# ================= 設定エリア =================
API_KEY = "ここにAPIキーを入れる"
RAILWAY_BASE_URL = "https://あなたのURL.up.railway.app" # 最後にスラッシュは不要
UPDATE_INTERVAL = 5
# ============================================

CHAT_API_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"
VIDEO_API_URL = "https://www.googleapis.com/youtube/v3/videos"
ACTION_URL = f"{RAILWAY_BASE_URL}/api/action"
STATUS_URL = f"{RAILWAY_BASE_URL}/api/status"

current_video_id = None
current_chat_id = None
next_page_token = None

def get_server_status():
    """サーバーから現在の設定（ON/OFF, ビデオID）を取得"""
    try:
        resp = requests.get(STATUS_URL, timeout=5)
        return resp.json()
    except:
        print("⚠️ サーバー接続エラー: Railwayは動いていますか？")
        return None

def get_live_chat_id(video_id):
    """ビデオIDからチャットIDを取得"""
    params = {"part": "liveStreamingDetails", "id": video_id, "key": API_KEY}
    try:
        resp = requests.get(VIDEO_API_URL, params=params)
        data = resp.json()
        items = data.get("items", [])
        if not items: return None
        return items[0]["liveStreamingDetails"].get("activeLiveChatId")
    except Exception as e:
        print(f"ChatID取得エラー: {e}")
        return None

def send_command(type_str, amount):
    try:
        payload = {"type": type_str, "amount": amount}
        requests.post(ACTION_URL, json=payload)
    except:
        pass

def main():
    global current_video_id, current_chat_id, next_page_token
    print(f"=== MEGWIN 全自動監視システム ===")
    print(f"サーバー: {RAILWAY_BASE_URL}")
    print("起動しました。管理ページからの指示を待っています...")

    while True:
        # 1. サーバーの状態を確認
        status = get_server_status()
        
        if not status:
            time.sleep(10)
            continue

        is_active = status.get("is_active", False)
        target_video_id = status.get("video_id", "")

        # --- ケースA: システムOFF ---
        if not is_active:
            print(f"\r[待機中] システムはOFFです... ", end="")
            time.sleep(5)
            continue

        # --- ケースB: ビデオIDが設定されていない ---
        if not target_video_id:
            print(f"\r[待機中] ビデオIDが管理画面で設定されていません... ", end="")
            time.sleep(5)
            continue

        # --- ケースC: 新しいビデオIDが設定された！ ---
        if target_video_id != current_video_id:
            print(f"\n🆕 新しいビデオIDを検出: {target_video_id}")
            print("チャットIDを取得中...")
            new_chat_id = get_live_chat_id(target_