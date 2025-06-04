#!/usr/bin/env python3
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import subprocess
import time

# -----------------------------------------------
# ※「frac」とありますが、ここでは一般的な可逆圧縮フォーマットである FLAC（.flac）に変換するものと仮定します。
# -----------------------------------------------

# 変換対象ページのリスト
PAGE_URLS = [
    "https://web.archive.org/web/19970807015220/http://www.mahoroba.or.jp/~nakagami/music/newsound.html",
    "https://web.archive.org/web/19970807015236/http://www.mahoroba.or.jp/~nakagami/music/sndarc.html",
    "https://web.archive.org/web/19970807011832/http://www.mahoroba.or.jp/~nakagami/music/cd.html"
]

# ダウンロード用ディレクトリ（.ra を一旦保存）
RA_DIR = "ra_files"
# 変換後の FLAC を保存するディレクトリ
FLAC_DIR = "flac_files"

# リトライ回数と待機秒数
MAX_RETRIES = 3
RETRY_WAIT_SEC = 5

# ディレクトリがなければ作成
os.makedirs(RA_DIR, exist_ok=True)
os.makedirs(FLAC_DIR, exist_ok=True)

# ページから抽出した .ra の URL を一意に保持するためのセット
ra_urls = set()

for page_url in PAGE_URLS:
    try:
        resp = requests.get(page_url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Warning] Failed to fetch page {page_url}: {e}")
        continue

    soup = BeautifulSoup(resp.text, "html.parser")
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # リンクの末尾が .ra ならば処理対象
        if href.lower().endswith(".ra"):
            # urljoin で完全な URL に変換。ただし Archive のリライトが不正になっている場合でも、
            # requests.get で試せるように元のままの href も併記しておく
            full_url = urljoin(page_url, href)
            ra_urls.add(full_url)

print(f"Found {len(ra_urls)} .ra URLs.")

for url in ra_urls:
    filename = os.path.basename(url)
    if not filename.lower().endswith(".ra"):
        # 万が一パスが .ra で終わらない場合もスキップ
        continue

    local_ra_path = os.path.join(RA_DIR, filename)
    flac_filename = os.path.splitext(filename)[0] + ".flac"
    flac_path = os.path.join(FLAC_DIR, flac_filename)

    # 既に .flac 化済みの場合は最初からスキップ
    if os.path.exists(flac_path):
        print(f"[Exists] {flac_filename}, skip entire process.")
        continue

    # ダウンロード済みの .ra があればリダウンロードせずに進む
    if not os.path.exists(local_ra_path):
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[Downloading] {filename} (attempt {attempt}/{MAX_RETRIES})")
                r = requests.get(url, stream=True, timeout=15)
                if r.status_code == 200:
                    with open(local_ra_path, "wb") as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)
                    print(f"[Downloaded] {filename}")
                    success = True
                    break
                else:
                    print(f"[Skipped] {url} → HTTP {r.status_code}")
                    break
            except requests.exceptions.RequestException as e:
                print(f"[Error] Download {url} (attempt {attempt}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_SEC)
                else:
                    print(f"[Failed] Could not download {filename} after {MAX_RETRIES} attempts, skip.")
        if not success:
            continue
    else:
        print(f"[Exists] {filename}, skip download.")

    # .ra が存在しない or ダウンロードに失敗していないか再チェック
    if not os.path.exists(local_ra_path):
        print(f"[Missing] {filename}, nothing to convert.")
        continue

    # FLAC 変換
    try:
        print(f"[Converting] {filename} → {flac_filename}")
        # FFmpeg の出力を完全に捨てる
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", local_ra_path, "-c:a", "flac", flac_path, "-y"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"[Converted] {filename} → {flac_filename}")
    except subprocess.CalledProcessError:
        print(f"[Error] Conversion failed for {filename}, skip.")
        # 変換失敗時は .ra を残しておく場合は以下をコメントアウト
        if os.path.exists(local_ra_path):
            try:
                os.remove(local_ra_path)
            except Exception:
                pass
        continue

    # 変換成功したら元の .ra を削除
    try:
        os.remove(local_ra_path)
        print(f"[Removed] {filename}")
    except Exception as e:
        print(f"[Warning] Failed to remove {filename}: {e}")
