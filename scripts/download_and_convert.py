#!/usr/bin/env python3
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import subprocess

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
        print(f"Failed to fetch {page_url}: {e}")
        continue

    soup = BeautifulSoup(resp.text, "html.parser")
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # リンクの末尾が .ra ならば処理対象
        if href.lower().endswith(".ra"):
            full_url = urljoin(page_url, href)
            ra_urls.add(full_url)

print(f"Found {len(ra_urls)} .ra URLs.")

for url in ra_urls:
    filename = os.path.basename(url)
    local_ra_path = os.path.join(RA_DIR, filename)

    # すでにダウンロード済みかチェック
    if not os.path.exists(local_ra_path):
        try:
            r = requests.get(url, stream=True, timeout=15)
            if r.status_code == 200:
                with open(local_ra_path, "wb") as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                print(f"[Downloaded] {filename}")
            else:
                print(f"[Skipped] {url} → HTTP {r.status_code}")
                continue
        except Exception as e:
            print(f"[Error] Download {url}: {e}")
            continue
    else:
        print(f"[Exists] {filename}, skip download.")

    # FLAC 変換
    flac_filename = os.path.splitext(filename)[0] + ".flac"
    flac_path = os.path.join(FLAC_DIR, flac_filename)

    if not os.path.exists(flac_path):
        try:
            # ffmpeg が runner にインストールされている想定
            subprocess.run(
                ["ffmpeg", "-i", local_ra_path, "-c:a", "flac", flac_path, "-loglevel", "error", "-y"],
                check=True
            )
            print(f"[Converted] {filename} → {flac_filename}")
        except subprocess.CalledProcessError as e:
            print(f"[Error] Conversion {filename}: {e}")
            continue
    else:
        print(f"[Exists] {flac_filename}, skip conversion.")

    # .ra ファイルは不要になったら削除
    try:
        os.remove(local_ra_path)
        print(f"[Removed] {filename}")
    except Exception as e:
        print(f"[Warning] Failed to remove {filename}: {e}")
