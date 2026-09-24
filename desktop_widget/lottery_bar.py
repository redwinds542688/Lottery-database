# -*- coding: utf-8 -*-
"""
最新開獎資訊列（桌面常駐橫幅，顯示在工作列正上方）
- 底色固定透明（Windows 色鍵去背）
- 四種彩券平均分布在整個螢幕寬度
- 統一配色：彩券名稱淺藍色、日期淺灰色、號碼淺白色、特別號淺紅色（不顯示
  「特別號」三個字，只顯示數字本身，靠顏色跟間距區分）
- 固定顯示在螢幕下方，不可拖曳移動（2026-08-28 修正：原本可以用滑鼠左鍵
  按住拖曳整條資訊列，使用者要求改成固定位置，避免不小心手滑點到就被
  拖走，移除了原本的拖曳綁定）。

2026-09-02 曾經改用 Pillow + Win32 layered window（UpdateLayeredWindow）做
逐像素真透明，想解決白色網頁背景下文字鑲邊/模糊的問題，但在實機測試時
變得不穩定（同樣的啟動方式時好時壞、透過工作排程器啟動完全沒有畫面），
排查太耗時，已經整個撤掉，改回這版的視窗建立方式（overrideredirect +
-transparentcolor 色鍵去背 + tkinter mainloop），這部分已經確認穩定
可靠，之後不要再改。

2026-09-02 用比較低風險的方式處理白色背景鑲邊問題：文字本身改成用
Pillow 事先畫成小圖片（tk.Label 用 image= 顯示，不再用 text=/font=
直接讓 tkinter 畫文字），畫的時候把反鋸齒邊緣「二值化」——每個像素
只會是「完全是色鍵透明色」或「完全是文字顏色」兩種之一，不會再有
兩者之間的過渡色（過渡色就是造成鑲邊/模糊觀感的原因，因為它跟色鍵
不完全一樣、不會被判定成透明，就變成一圈突兀的深色邊）。這個改動
只動「文字怎麼畫出來」這一小塊，視窗建立/mainloop/點擊更新的邏輯
完全沒有變，風險比上面那次 Win32 layered window 的整個重寫小很多。
代價：文字邊緣會比原本 ClearType 反鋸齒硬一點（沒那麼平滑），字型
大小/清晰度如果不理想，可以調整下面的 FONT_SIZE。

2026-09-02 操作方式簡化：拿掉了原本的右鍵選單（「立即更新」／「結束」）。
改成滑鼠左鍵點一下小工具本身（任何文字上都可以），就立刻重新抓取一次
data.json 並刷新畫面，不用等 5 分鐘自動週期。副作用：小工具本身沒有
「結束」這個操作了——要關閉程式請透過工作管理員（Ctrl+Shift+Esc）找
執行 lottery_bar.py 的 python / pythonw 程序，手動結束工作。

用法：
    python lottery_bar.py
    （或 py lottery_bar.py）
需求：
    pip install requests pillow
資料來源（2026-09-24 修正）：
    GitHub repo 已改成 Private，公開網址 raw.githubusercontent.com 讀不到了(404)，
    所以改從 Cloudflare Worker（lottery-data-gate）讀，跟手機上的抓539／主程式同一個來源，
    不需要設定任何 Token。Worker 的程式金鑰(WORKER_KEY)如果之後換了，這裡也要跟著換。
    這次只改了 fetch_data() 與上面幾個設定常數，文字繪製、點擊更新、位置等其他部分完全沒動。
操作：
    - 滑鼠左鍵點一下小工具本身，就會立刻重新整理，不用等 5 分鐘自動週期
    - 位置固定在螢幕下方（工作列正上方），不會被滑鼠拖動
    - 沒有選單、沒有「結束」選項；要關閉程式請透過工作管理員結束
      python / pythonw 程序
已知小限制：
    文字改成 Pillow 二值化繪製後，白色背景鑲邊/模糊的問題應該已經解決；
    但字型邊緣會比原本 ClearType 反鋸齒略硬一點，如果覺得字看起來太
    「鋸齒」，可以試著調大 FONT_SIZE 讓文字整體大一點會比較不明顯。
"""
import base64
import json
import os
import re
import time
import tkinter as tk
from datetime import date
import requests
from PIL import Image, ImageDraw, ImageFont, ImageTk
# ---------------------------------------------------------------------------
# 設定：這幾個值可以依你自己的螢幕/喜好調整
# ---------------------------------------------------------------------------
GITHUB_REPO = "redwinds542688-gif/Lottery-database"
GITHUB_BRANCH = "main"
GITHUB_DATA_PATH = "data.json"
RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_DATA_PATH}"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_PATH}"
# 2026-09-24：repo 改 Private 後的主要資料來源——Cloudflare Worker（跟手機程式同一個）
WORKER_URL = "https://lottery-data-gate.redwinds542688.workers.dev/"
WORKER_KEY = "XDpe6u87-81Lmx5o6z8hNZWuFvcJGus2"   # 跟手機程式裡的 CRAWLER_CLIENT_KEY 相同；Worker 換金鑰時這裡也要換
APP_ID = "widget"
APP_VERSION = "v1.1"
REFRESH_INTERVAL_MS = 5 * 60 * 1000  # 自動重新整理間隔（毫秒），預設 5 分鐘
BAR_HEIGHT = 34            # 資訊列高度（像素）
TASKBAR_HEIGHT = 40        # 工作列高度估計值，如果資訊列跟工作列對不齊，調整這個數字
FONT_SIZE = 18             # 文字大小（像素）。2026-09-02 從 20 調小到 18：
                           # Pillow 畫出來的文字實際寬度比原本 tkinter 內建
                           # 字型微寬，20px 時內容最長的「大樂透」那一欄
                           # （週幾+6個號碼）會超出四等分後的欄寬，被螢幕
                           # 邊緣切掉，調小騰出空間。如果覺得字太小，可以
                           # 試著調大，但如果又被切到，記得同時調小或拿掉
                           # 下面 _add_text_label 呼叫時字串前面的空白。
# 微軟正黑體字型檔實際路徑（Windows 內建），優先用粗體版本；
# 如果你的系統找不到這個路徑，會退回用 Pillow 內建的陽春字型
# （只有英數字，中文會顯示不出來，屆時要調整下面這個清單）。
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msjhbd.ttc",   # 微軟正黑體 粗體
    r"C:\Windows\Fonts\msjh.ttc",     # 微軟正黑體 一般
    r"C:\Windows\Fonts\mingliu.ttc",  # 備援：細明體
]
# 透明色鍵：這個顏色會被視窗判定成「透明」而完全看不見，所以底色、
# 所有 Frame/Label 的 bg 都要用同一個顏色。選深黑色是因為：
#   1. 底下四種文字顏色（淺藍、淺灰、淺白、淺紅）都不會用到接近黑色，
#      不會誤觸文字也跟著隱形。
#   2. 抗鋸齒邊緣萬一沒完全被判定成透明，殘留的深色鑲邊會比亮色（例如
#      桃紅色）鑲邊不明顯很多，肉眼比較不容易注意到。
TRANSPARENT_COLOR = "#010101"
# 統一配色（不分彩券，所有彩券共用同一套顏色）
GAME_NAME_COLOR = "#8ec9f2"   # 彩券名稱：淺藍色
DATE_COLOR = "#c9c9c9"        # 日期：淺灰色
WEEKDAY_COLOR = "#f2e28a"     # 週幾：淺黃色
NUMBER_COLOR = "#f2f2f2"      # 號碼：淺白色
SPECIAL_COLOR = "#f28b8b"     # 特別號：淺紅色（不顯示「特別號」文字，只顯示數字）
# JSON 裡的完整彩券名稱 -> 資訊列上要顯示的簡稱
GAME_DISPLAY = [
    ("今彩539",     "539"),
    ("香港六合彩",   "六合彩"),
    ("加州天天樂",   "天天樂"),
    ("大樂透",       "大樂透"),
]
WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]
_MONTH_NAME_TO_NUM = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
# ---------------------------------------------------------------------------
# 日期格式解析（跟雲端爬蟲程式用同一套規則，確保週幾算出來一致）
# ---------------------------------------------------------------------------
def normalize_draw_date(raw):
    """把各種格式的開獎日期字串統一轉成 date 物件，抓不到就回傳 None。"""
    if not raw:
        return None
    s = str(raw).strip()
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(?<!\d)(\d{2,3})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        try:
            return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        month = _MONTH_NAME_TO_NUM.get(m.group(1)[:3].upper())
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", s)
    if m:
        month = _MONTH_NAME_TO_NUM.get(m.group(2)[:3].upper())
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None
def format_date_zh(d):
    """把 date 物件轉成 'MM-DD' 格式（不含週幾）。"""
    if d is None:
        return "--/--"
    return f"{d.month:02d}-{d.day:02d}"
def format_weekday_zh(d):
    """把 date 物件轉成 '(週X)' 格式。"""
    if d is None:
        return ""
    return f"(週{WEEKDAY_ZH[d.weekday()]})"
def format_numbers(numbers_str):
    """把 '13 19 23 35 38' 這種空白分隔字串轉成 '13-19-23-35-38'，每個補成 2 位數。"""
    parts = [p for p in str(numbers_str).split() if p.strip()]
    return "-".join(f"{int(p):02d}" for p in parts)
# ---------------------------------------------------------------------------
# 文字繪製（用 Pillow 畫成小圖片，二值化去除反鋸齒過渡色，解決色鍵去背
# 在白色背景下的鑲邊/模糊問題；細節見檔案開頭的 2026-09-02 changelog）
# ---------------------------------------------------------------------------
def _load_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, FONT_SIZE)
            except Exception:
                continue
    return ImageFont.load_default()
_FONT = _load_font()
_ASCENT, _DESCENT = _FONT.getmetrics()
_TEXT_IMG_HEIGHT = _ASCENT + _DESCENT + 4  # 上下各留一點邊，避免筆畫被裁到
_TEXT_IMG_PAD = 2
def render_text_image(text, color_hex):
    """把一段文字畫成一張 Pillow RGB 圖片，回傳可以直接放進 tk.Label(image=...)
    的 PhotoImage。每個像素只會是「色鍵透明色」或「文字顏色」兩者之一，
    反鋸齒造成的過渡色會被二值化拿掉（見下面的 point() 那行），這樣色鍵
    去背才能正確判斷透明，不會殘留鑲邊。"""
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width = max(int(dummy_draw.textlength(text, font=_FONT)) + _TEXT_IMG_PAD * 2, 1)
    height = _TEXT_IMG_HEIGHT
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((_TEXT_IMG_PAD, _TEXT_IMG_PAD), text, font=_FONT, fill=255)
    # 二值化：反鋸齒造成的過渡灰階像素，一律歸類成「有文字」或「沒文字」，
    # 不再保留中間值，這樣畫出來的圖片才不會有介於色鍵色跟文字色之間的
    # 過渡像素（那種過渡像素才是造成白色背景下鑲邊/模糊的元兇）。
    mask = mask.point(lambda p: 255 if p >= 128 else 0)
    img = Image.new("RGB", (width, height), TRANSPARENT_COLOR)
    solid = Image.new("RGB", (width, height), color_hex)
    img.paste(solid, (0, 0), mask)
    return ImageTk.PhotoImage(img)
# ---------------------------------------------------------------------------
# 讀取雲端資料
# ---------------------------------------------------------------------------
def fetch_data():
    """讀取雲端 data.json。
    1. 先走 Cloudflare Worker（repo 已是 Private，這是現在的主要來源，不需要 Token）。
    2. Worker 失敗時，再試舊的公開網址（repo 萬一改回 Public 還能用）。
    3. 最後才試 GitHub API + 環境變數 GITHUB_TOKEN（有設定才會用）。
    全部失敗就丟出例外，由 refresh() 靜默略過、保留畫面上的舊資料。"""
    try:
        resp = requests.get(
            WORKER_URL,
            params={"key": WORKER_KEY, "app": APP_ID, "v": APP_VERSION, "_ts": int(time.time() * 1000)},
            headers={"Cache-Control": "no-cache"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and any(k in data for k, _ in GAME_DISPLAY):
                return data
    except (requests.RequestException, ValueError):
        pass
    try:
        resp = requests.get(RAW_URL, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except (requests.RequestException, ValueError):
        pass
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("讀取失敗：Worker 與公開網址都讀不到，且未設定 GITHUB_TOKEN")
    headers = {"Authorization": f"token {token}"}
    resp = requests.get(API_URL, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    raw = base64.b64decode(payload["content"])
    return json.loads(raw.decode("utf-8"))
# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class LotteryBar:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)              # 不顯示標題列/邊框
        self.root.attributes("-topmost", True)         # 永遠置頂
        self.root.configure(bg=TRANSPARENT_COLOR)
        # Windows 專屬：把 TRANSPARENT_COLOR 這個顏色判定成完全透明
        self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        y = screen_h - TASKBAR_HEIGHT - BAR_HEIGHT
        self.root.geometry(f"{screen_w}x{BAR_HEIGHT}+0+{y}")
        # 用 grid 把螢幕寬度平均切成 4 欄，每種彩券各佔一欄，欄內置中
        for col in range(len(GAME_DISPLAY)):
            self.root.columnconfigure(col, weight=1, uniform="game_col")
        self.root.rowconfigure(0, weight=1)
        self.column_frames = []
        for col in range(len(GAME_DISPLAY)):
            frame = tk.Frame(self.root, bg=TRANSPARENT_COLOR)
            frame.grid(row=0, column=col, sticky="nsew")
            self.column_frames.append(frame)
        # 固定顯示在螢幕下方，不提供拖曳移動功能
        # 點一下小工具本身就立刻重新整理（沒有選單、沒有「結束」選項，
        # 要關閉程式請透過工作管理員）
        self._refresh_job = None
        self._photo_refs = []  # 保留畫好的文字圖片參照，避免被垃圾回收（見 _add_text_label 說明）
        self._bind_click(self.root)
        for frame in self.column_frames:
            self._bind_click(frame)
        self.refresh()
    def _bind_click(self, widget):
        """幫這個 widget 綁上「點一下就立刻更新」。因為畫面上滑鼠實際點到的
        通常是 Frame/Label 這些子元件，所以每個會顯示在畫面上的元件都要
        各自綁定，點擊事件才不會被子元件接住、傳不到最上層。"""
        widget.bind("<Button-1>", self._on_click)
    def _on_click(self, event):
        self.manual_refresh()
    def manual_refresh(self):
        """點一下小工具：取消排定中的下一次自動重新整理，馬上重新抓取
        一次，並從這次重新開始算下一個 5 分鐘週期。"""
        if self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None
        self.refresh()
    def _clear_columns(self):
        for frame in self.column_frames:
            for widget in frame.winfo_children():
                widget.destroy()
        # 舊的文字圖片參照也要一起清掉，不然每次 refresh() 都會累積、
        # 記憶體用量隨時間一直增加（圖片很小，但長時間跑下來還是會有感）。
        self._photo_refs = []
    def _add_text_label(self, parent, text, color_hex):
        """建立一個用 Pillow 畫好的文字圖片當內容的 Label，並綁上點擊更新。
        圖片物件要存在 self._photo_refs 裡保留參照，不然 tkinter 顯示圖片
        時如果沒有 Python 端的參照撐著，圖片會被垃圾回收、畫面變空白
        （這是 tkinter PhotoImage 常見的坑，不是這次才有的新問題）。"""
        photo = render_text_image(text, color_hex)
        self._photo_refs.append(photo)
        lbl = tk.Label(parent, image=photo, bg=TRANSPARENT_COLOR, bd=0, highlightthickness=0)
        lbl.pack(side=tk.LEFT)
        self._bind_click(lbl)
        return lbl
    def _render_game(self, frame, label, records):
        # 用一個內層 Frame 承裝這個彩券的所有文字區塊，讓 pack() 的預設
        # 置中行為把整組內容在欄位裡水平置中。
        # 這裡新建的 inner Frame 跟每一個 Label 都要各自綁上「點一下就更新」，
        # 因為每次 refresh() 都會先整個清空重建（見 _clear_columns），
        # 舊的綁定會跟著舊 widget 一起被銷毀，所以要在這裡重新綁一次。
        inner = tk.Frame(frame, bg=TRANSPARENT_COLOR)
        inner.pack(expand=True)
        self._bind_click(inner)
        if not records:
            self._add_text_label(inner, f"{label} 無資料", GAME_NAME_COLOR)
            return
        entry = records[0]
        d = normalize_draw_date(entry.get("draw_date"))
        date_str = format_date_zh(d)
        weekday_str = format_weekday_zh(d)
        numbers_str = format_numbers(entry.get("numbers", ""))
        special = entry.get("special_number", "")
        # 2026-09-02：字與字之間的空白從兩個字元收緊成一個，跟調小
        # FONT_SIZE 一起騰出空間，避免內容最長的「大樂透」欄位被切到。
        self._add_text_label(inner, label, GAME_NAME_COLOR)
        self._add_text_label(inner, f" {date_str}", DATE_COLOR)
        if weekday_str:
            self._add_text_label(inner, weekday_str, WEEKDAY_COLOR)
        self._add_text_label(inner, f" {numbers_str}", NUMBER_COLOR)
        if special:
            self._add_text_label(inner, f"  {int(special):02d}", SPECIAL_COLOR)
    def refresh(self):
        try:
            data = fetch_data()
            self._clear_columns()
            for frame, (game_key, label) in zip(self.column_frames, GAME_DISPLAY):
                self._render_game(frame, label, data.get(game_key, []))
        except Exception:
            pass  # 讀取失敗就先維持畫面上原本的內容，等下一輪自動重試
        self._refresh_job = self.root.after(REFRESH_INTERVAL_MS, self.refresh)
    def run(self):
        self.root.mainloop()
if __name__ == "__main__":
    LotteryBar().run()