#!/usr/bin/env python3
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import subprocess
import time
import argparse

# -----------------------------------------------
# ※「frac」とありますが、本例では可逆圧縮フォーマットとして一般的な FLAC（.flac）に変換します。
# -----------------------------------------------

# 変換対象ページのリスト（Web Archive のスナップショット URL）
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


def parse_archive_base(page_url):
    """
    Archive URL からタイムスタンプとオリジナルのベースディレクトリを抽出する。
    例:
      page_url = "https://web.archive.org/web/19970807011832/http://www.mahoroba.or.jp/~nakagami/music/cd.html"
      → ts = "19970807011832"
      → orig_base = "http://www.mahoroba.or.jp/~nakagami/music/"
    """
    parsed = urlparse(page_url)
    parts = parsed.path.split("/", 4)
    # parts = ['', 'web', '19970807011832', 'http:', 'www.mahoroba.or.jp/~nakagami/music/cd.html']
    if len(parts) < 5:
        return None, None
    ts = parts[2]  # "19970807011832"
    orig_full = parts[3] + "//" + parts[4]  # "http://" + "www.mahoroba.or.jp/~nakagami/music/cd.html"
    parsed_orig = urlparse(orig_full)
    orig_domain = f"{parsed_orig.scheme}://{parsed_orig.netloc}"
    orig_dir = os.path.dirname(parsed_orig.path) + "/"  # "/~nakagami/music/"
    orig_base = orig_domain + orig_dir
    return ts, orig_base


def download_and_convert(url, skipped_list):
    """
    引数:
      url:  ダウンロードを試みる Archive URL （https://web.archive.org/web/タイムスタンプ/http://.../.ra 形式）
      skipped_list: 失敗した URL を追加するリスト（呼び出し元で用意する）
    戻り値:
      True ＝ 成功して .flac まで作成済み
      False = ダウンロード or 変換に失敗してスキップ
    """

    filename = os.path.basename(url)
    if not filename.lower().endswith(".ra"):
        return False

    local_ra_path = os.path.join(RA_DIR, filename)
    flac_filename = os.path.splitext(filename)[0] + ".flac"
    flac_path = os.path.join(FLAC_DIR, flac_filename)

    # 既に .flac 化済みならスキップ
    if os.path.exists(flac_path):
        print(f"[Exists] {flac_filename}, skip entire process.")
        return True

    # ダウンロード済みの .ra が無いならダウンロード
    if not os.path.exists(local_ra_path):
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[Downloading] {filename} (attempt {attempt}/{MAX_RETRIES})")
                resp = requests.get(url, stream=True, timeout=15)
                if resp.status_code == 200:
                    with open(local_ra_path, "wb") as f:
                        for chunk in resp.iter_content(1024):
                            f.write(chunk)
                    print(f"[Downloaded] {filename}")
                    success = True
                    break
                else:
                    print(f"[Skipped] {url} → HTTP {resp.status_code}")
                    skipped_list.append(url)
                    break
            except requests.exceptions.RequestException as e:
                print(f"[Error] Download {url} (attempt {attempt}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT_SEC)
                else:
                    print(f"[Failed] Could not download {filename} after {MAX_RETRIES} attempts, skip.")
                    skipped_list.append(url)
        if not success:
            return False
    else:
        print(f"[Exists] {filename}, skip download.")

    # .ra が存在しない場合は何もしない
    if not os.path.exists(local_ra_path):
        print(f"[Missing] {filename}, nothing to convert.")
        return False

    # FLAC 変換（ログを抑制）
    try:
        print(f"[Converting] {filename} → {flac_filename}")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", local_ra_path, "-c:a", "flac", flac_path, "-y"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"[Converted] {filename} → {flac_filename}")
    except subprocess.CalledProcessError:
        print(f"[Error] Conversion failed for {filename}, skip.")
        # 変換失敗でも .ra を削除して次に進みたい場合は以下
        if os.path.exists(local_ra_path):
            try:
                os.remove(local_ra_path)
            except Exception:
                pass
        skipped_list.append(url)
        return False

    # 変換成功 → .ra を削除
    try:
        os.remove(local_ra_path)
        print(f"[Removed] {filename}")
    except Exception as e:
        print(f"[Warning] Failed to remove {filename}: {e}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Download .ra files and convert to FLAC.")
    parser.add_argument(
        '--manual-urls',
        type=str,
        default='',
        help='Comma-separated manual URLs to retry (override automatic skips).'
    )
    args = parser.parse_args()
    manual_input = args.manual_urls.strip()

    # 1) 自動フェーズ：Archive ページをパースして .ra の Archive URL をすべて集める
    ra_urls = set()
    for page_url in PAGE_URLS:
        try:
            resp = requests.get(page_url, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            print(f"[Warning] Failed to fetch page {page_url}: {e}")
            continue

        ts, orig_base = parse_archive_base(page_url)
        if ts is None or orig_base is None:
            print(f"[Warning] Could not parse archive base from {page_url}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not href.lower().endswith(".ra"):
                continue

            # 元の絶対 URL を作成
            if href.startswith("http://") or href.startswith("https://"):
                orig_url = href
            else:
                orig_url = urljoin(orig_base, href)

            # Archive URL に組み立て
            archive_url = f"https://web.archive.org/web/{ts}/{orig_url}"
            ra_urls.add(archive_url)

    print(f"Found {len(ra_urls)} .ra URLs (archive-wrapped).")

    # 2) ダウンロード＆変換フェーズ
    skipped_urls = []
    for url in sorted(ra_urls):
        download_and_convert(url, skipped_urls)

    # 3) 手動入力フェーズ：workflow_dispatch からの --manual-urls がある場合に実行
    if manual_input:
        manual_urls = [u.strip() for u in manual_input.split(",") if u.strip()]
        print(f"\n手動入力で指定された URL を {len(manual_urls)} 件、ダウンロード→変換を試みます。\n")
        skipped_manual = []
        for url in manual_urls:
            if not url.lower().endswith(".ra"):
                print(f"[Warning] 手動入力 URL が “.ra” で終わっていません: {url} → スキップします。")
                continue
            success = download_and_convert(url, skipped_manual)
            if not success:
                print(f"[Failed] 手動入力でも取得できませんでした: {url}")
        if skipped_manual:
            print("\n---- 手動入力フェーズでも失敗した URL ----")
            for u in skipped_manual:
                print(f"- {u}")
            print("------------------------------------------")
    elif skipped_urls:
        # manual_input が空で、かつ自動フェーズでスキップがあればログ表示のみ
        print("\n==== 以下の URL は自動フェーズでスキップされましたが、手動入力は提供されませんでした ====")
        for idx, u in enumerate(skipped_urls, start=1):
            print(f"{idx}. {u}")
        print("このままスキップします。手動入力が必要な場合は --manual-urls オプションで指定してください。")

    print("\nすべての処理が完了しました。")


if __name__ == "__main__":
    main()
