# -*- coding: utf-8 -*-
"""桌面開獎資訊列 檢查小程式：逐項檢查為什麼資訊列沒出現，結果印在視窗上，截圖傳回即可。"""
import os
import sys
import traceback

BAR_FILE = r"C:\LotteryBar\lottery_bar.py"
WORKER_URL = "https://lottery-data-gate.redwinds542688.workers.dev/"
WORKER_KEY = "XDpe6u87-81Lmx5o6z8hNZWuFvcJGus2"
RAW_URL = "https://raw.githubusercontent.com/redwinds542688-gif/Lottery-database/main/data.json"
GAMES = ["今彩539", "香港六合彩", "加州天天樂", "大樂透"]


def line(title, ok, detail=""):
    mark = "OK  " if ok else "失敗"
    print(f"[{mark}] {title}" + (f"：{detail}" if detail else ""))


def main():
    print("=" * 60)
    print("桌面開獎資訊列 檢查")
    print("=" * 60)
    line("Python 版本", True, sys.version.split()[0] + "  (" + sys.executable + ")")

    # 1. 程式檔案
    if not os.path.exists(BAR_FILE):
        line("程式檔案存在", False, BAR_FILE + " 找不到")
    else:
        with open(BAR_FILE, "rb") as f:
            raw = f.read()
        line("程式檔案存在", True, f"{len(raw)} bytes")
        try:
            text = raw.decode("utf-8")
            line("檔案編碼是 UTF-8", True)
        except UnicodeDecodeError:
            text = raw.decode("cp950", errors="replace")
            line("檔案編碼是 UTF-8", False, "存檔時請選「UTF-8」編碼再存一次")
        first = text.lstrip("\ufeff").splitlines()[0] if text.strip() else ""
        if first.strip().startswith("```"):
            line("第一行正確", False, "第一行是 ``` ，把最上面和最下面的 ``` 那兩行刪掉")
        else:
            line("第一行正確", True, first[:40])
        if "WORKER_URL" in text:
            line("是新版(讀 Worker)", True)
        else:
            line("是新版(讀 Worker)", False, "還是舊版，新內容沒有存進去")
        try:
            compile(text.lstrip("\ufeff"), BAR_FILE, "exec")
            line("程式語法", True)
        except SyntaxError as e:
            line("程式語法", False, f"第 {e.lineno} 行：{e.msg}")

    # 2. requests 套件
    try:
        import requests
        line("requests 套件", True, requests.__version__)
    except Exception as e:
        line("requests 套件", False, "沒有安裝，請執行：pip install requests")
        return

    # 2b. Pillow 套件(資訊列用它畫文字)
    try:
        import PIL
        line("Pillow 套件", True, getattr(PIL, "__version__", ""))
    except Exception:
        line("Pillow 套件", False, "沒有安裝，請執行：pip install pillow")

    # 3. Worker
    try:
        r = requests.get(WORKER_URL, params={"key": WORKER_KEY, "app": "widget-diag"}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            found = [g for g in GAMES if g in data]
            line("連到 Cloudflare Worker", True, f"HTTP 200，讀到 {len(found)} 種彩券")
            for g in GAMES:
                recs = data.get(g) or []
                if recs:
                    e = recs[0]
                    print(f"       {g}：{e.get('draw_date')}  {e.get('numbers')}  {e.get('special_number') or ''}")
        else:
            line("連到 Cloudflare Worker", False, f"HTTP {r.status_code}  {r.text[:120]}")
    except Exception as e:
        line("連到 Cloudflare Worker", False, f"{type(e).__name__}: {e}")

    # 4. 舊的公開網址(參考用，repo 私有後應該是 404)
    try:
        r = requests.get(RAW_URL, timeout=20)
        line("舊公開網址(參考)", r.status_code == 200, f"HTTP {r.status_code}（私有後 404 是正常的）")
    except Exception as e:
        line("舊公開網址(參考)", False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
    print("=" * 60)
    input("檢查完畢，截圖這個視窗傳給我，然後按 Enter 關閉…")
