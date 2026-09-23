# -*- coding: utf-8 -*-
"""coran-social（週2回の多チャネル投稿）が使う CORAN Frame 画像の在庫を作る。

    ~/.local/bin/uv run --python 3.12 --with pillow --with numpy python tools/build_social_frames.py
    （--limit 3 で試し刷り。--force で既存を作り直す）

出力:
    images/social/<カテゴリ>/<素材名>.jpg   … 4:5・見出し焼き込み済みの CORAN Frame
    images/social/manifest.json             … coran-social が読む目録（公開 raw URL の組み立て元）

なぜこの形か（2026-09-23 パープル・Phase 2 案①）:
    絵の実装（brandkit.py のレイアウト・フォント・階調）はこの repo にしかない。coran-social は
    TypeScript なので、向こうに Frame 生成を移植すると同じ「CORAN の画」が2実装に分かれて黙ってズレる。
    そこで画はここで作って commit し、向こうは URL を読むだけにする。
    ・PR で実物の画を人が見てからでないと投稿に使われない（承認ゲートが1枚増える）
    ・IG は公開 URL から画像を取りに来る。この repo が公開である限り raw.githubusercontent.com で取れる
      （★非公開にすると coran-social の IG 投稿が丸ごと失敗する）

守ること:
    ・価格・割引・クーポンを焼き込まない。見出しは brandimage.CATEGORY のテンプレ（事実の主張を書かない）。
    ・Dream Hotel 時代の写真は manifest.json に無いので、ここにも入らない（tools/build_manifest.py が唯一の正）。
    ・API は呼ばない（Claude での見出し生成はしない＝毎回同じ絵が再現する）。
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# config.py は import 時に本物の値を要求する。ここは描画しかしないのでダミーでよい
# （本物のトークンをローカルに置かない＝CLAUDE.md の決まり）。
os.environ.setdefault("IG_USER_ID", "build-social-frames")
os.environ.setdefault("IG_ACCESS_TOKEN", "build-social-frames")
os.environ.setdefault("IMAGE_BASE_URL", "https://raw.githubusercontent.com/coranbangkok-del/coran-instagram-autopost/main/images")
os.environ.pop("ANTHROPIC_API_KEY", None)   # 見出しはテンプレ経路に固定する

import config          # noqa: E402
import brandimage      # noqa: E402

OUT_DIR = os.path.join(config.IMAGES_DIR, "social")
MANIFEST_OUT = os.path.join(OUT_DIR, "manifest.json")
# ★参考値。coran-social は「目録を取った URL と同じ場所」から画像を引く（目録と画がズレた commit から
#   来ることを防ぐため）。この値は人が見て場所が分かるように置いてあるだけ。
BASE_URL = "https://raw.githubusercontent.com/coranbangkok-del/coran-instagram-autopost/main/images/social"

# 素材フォルダ（この repo の写真分類）→ coran-social の ServiceCategory と画のタグ。
#   ★categories が空 = どのメニューにも紐づかない汎用（雰囲気・受賞・商品）。
#   ★coran-social 側に "foot" カテゴリは無いので foot は massage に寄せる。
CATEGORY_MAP = {
    "aroma":             (["aromatherapy", "massage"],          ["treatment"]),
    "award":             ([],                                   ["detail"]),
    "body-mask":         (["facial-body-combo"],                ["treatment"]),
    "body-scrub":        (["aromatherapy", "facial-body-combo"], ["treatment"]),
    "coconut":           (["coconut-spa"],                      ["treatment"]),
    "concept":           ([],                                   ["ambiance"]),
    "facial":            (["facial", "facial-body-combo"],      ["treatment"]),
    "foot":              (["massage"],                          ["treatment"]),
    "head-massage":      (["ayurveda", "massage"],              ["treatment"]),
    "herbal-ball":       (["massage"],                          ["treatment"]),
    "herbs":             (["massage", "ayurveda"],              ["product"]),
    "maternity-massage": (["prenatal-postnatal"],               ["treatment"]),
    "milk-spa":          (["milk-spa"],                         ["treatment"]),
    "office-syndrome":   (["massage"],                          ["treatment"]),
    "product":           ([],                                   ["product"]),
    "shirodhara":        (["ayurveda"],                         ["treatment"]),
    "shop":              ([],                                   ["interior", "ambiance"]),
    "thai-massage":      (["massage"],                          ["treatment"]),
}
SKIP_DIRS = {"generated", "social"}

# 見出しに焼いてはいけない主張。
#   ・所要時間: 画を選ぶ側（coran-social の selectFrame）はメニューの分数を見ないので、
#     60分のメニューに「ninety minutes」の画が当たると事実と違う投稿になる。
#   ・価格/割引: 本文と同じく画にも焼かない（価格の正は予約バックエンドとサイト）。
#   例外は award カテゴリの受賞名（実際の受賞・受賞写真にしか使われない）。
FORBIDDEN_HEADLINE = [
    (re.compile(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\s+minutes?\b", re.I), "所要時間"),
    (re.compile(r"\b\d+\s*(minutes?|mins?|hours?|hrs?)\b", re.I), "所要時間"),
    (re.compile(r"\d+\s*(分|時間)"), "所要時間"),
    (re.compile(r"(฿|THB|バーツ|baht|泰铢|泰銖|바트)", re.I), "価格"),
    (re.compile(r"(\d+\s*%|OFF\b|割引|discount|sale)", re.I), "割引"),
]
HEADLINE_GUARD_EXEMPT = {"award"}


def check_headlines(cat, en, ja):
    """見出しに禁止事項が入っていないか調べ、理由のリストを返す。"""
    if cat in HEADLINE_GUARD_EXEMPT:
        return []
    hits = []
    for text in (en, ja):
        for pat, why in FORBIDDEN_HEADLINE:
            m = pat.search(text or "")
            if m:
                hits.append(f'{why}（"{m.group(0)}" in "{text}"）')
    return hits


def frame_id(rel_file):
    """images/manifest.json の "<カテゴリ>/<ファイル名>" から安定した id を作る。"""
    cat, name = rel_file.split("/", 1)
    return f"{cat}-{os.path.splitext(name)[0]}".lower().replace(" ", "-").replace("_", "-")


def targets_from(photos):
    """在庫に入れる写真だけを (rel, cat, categories, tags) で返す。対象外は理由付きで別に返す。"""
    picked, skipped = [], []
    for photo in photos:
        rel = photo.get("file") or ""
        cat = rel.split("/")[0]
        if cat in SKIP_DIRS:
            continue
        if cat not in CATEGORY_MAP:
            skipped.append((rel, "未知のカテゴリ"))
            continue
        categories, tags = CATEGORY_MAP[cat]
        picked.append((photo, rel, cat, categories, tags))
    return picked, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="先頭から N 枚だけ作る（試し刷り）")
    ap.add_argument("--force", action="store_true", help="既にある画も作り直す")
    args = ap.parse_args()

    photos = json.load(open(config.MANIFEST_PATH, encoding="utf-8"))
    picked, skipped = targets_from(photos)

    # ── パス1: 見出しの検査だけを先に全件やる（ファイルは1つも書かない）──
    #   ★書き出しの前に落とすのが肝心。あとで検査すると、違反入りの画と目録が
    #     ディスクに残ったまま exit 1 することになり、exit code を見ない運用で
    #     そのまま公開されうる（2026-09-23 の独立検証で指摘）。
    bad_headlines = []
    for photo, rel, cat, _categories, _tags in picked:
        _eyebrow, _layout_default, en, ja = brandimage.meta_for(photo)
        for why in check_headlines(cat, en, ja):
            bad_headlines.append((rel, why))
    if bad_headlines:
        print(f"見出しに書いてはいけない主張が {len(bad_headlines)} 件:")
        for r, w in bad_headlines:
            print(f"  {r}: {w}")
        print("src/brandimage.py の CATEGORY を直してから作り直してください。")
        print("★ファイルは1つも作っていません（画も目録も書き換えていない）。")
        return 1

    # ── パス2: ここから先で初めて書き出す ──
    # 既存の目録があれば、作り直さない画の layout はそこから引く
    # （素材が小さいと A→C に落ちるので、既定値を書くと実物とズレた目録になる）。
    prev_layout = {}
    if os.path.exists(MANIFEST_OUT):
        try:
            for fr in json.load(open(MANIFEST_OUT, encoding="utf-8")).get("frames", []):
                prev_layout[fr["id"]] = fr.get("layout")
        except Exception:
            pass
    frames, failed = [], []

    for photo, rel, cat, categories, tags in picked:
        fid = frame_id(rel)
        out_rel = f"{cat}/{fid}.jpg"
        out_path = os.path.join(OUT_DIR, out_rel)

        eyebrow, layout_default, en, ja = brandimage.meta_for(photo)

        if os.path.exists(out_path) and not args.force and prev_layout.get(fid):
            layout = prev_layout[fid]
        else:
            try:
                # post_type="service" = 素材のカテゴリ既定のレイアウト（A=写真主役 / C=額装）。
                img, layout = brandimage.render("service", photo)
            except Exception as e:                      # 1枚の失敗で在庫づくりを止めない
                failed.append((rel, f"{type(e).__name__}: {e}"))
                continue
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            img.save(out_path, quality=90, optimize=True, subsampling=1)

        frames.append({
            "id": fid,
            "path": out_rel,
            "ratio": "4:5",
            "categories": categories,
            "tags": tags,
            "headlineEn": en,
            "headlineJa": ja,
            "layout": layout,
            "keyword": cat,     # 素材フォルダ名。メニューとの相性付け（foot / herbal-ball / thai-massage …）に使う
            "source": rel,
        })
        if args.limit and len(frames) >= args.limit:
            break

    manifest = {
        "version": 1,
        "note": "CORAN Frame（見出し焼き込み済み）の在庫。価格・割引・クーポンは焼き込まない。",
        "baseUrl": BASE_URL,   # 参考値（実際の取得元は目録を取った URL と同じディレクトリ）
        "frames": frames,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    total_kb = sum(os.path.getsize(os.path.join(OUT_DIR, fr["path"])) for fr in frames) // 1024
    print(f"作成: {len(frames)}枚 / 合計 {total_kb}KB")
    print(f"目録: {os.path.relpath(MANIFEST_OUT, ROOT)}")
    by_layout = {}
    for fr in frames:
        by_layout[fr["layout"]] = by_layout.get(fr["layout"], 0) + 1
    print(f"レイアウト内訳: {by_layout}")
    if skipped:
        print(f"対象外 {len(skipped)}件: " + ", ".join(f"{r}({w})" for r, w in skipped[:5]))
    if failed:
        print(f"失敗 {len(failed)}件:")
        for r, w in failed:
            print(f"  {r}: {w}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
