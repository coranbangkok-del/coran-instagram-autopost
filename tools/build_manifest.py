# -*- coding: utf-8 -*-
"""
images/manifest.json を images/ の実体から作り直す（再現可能にするためのスクリプト）。

    python tools/build_manifest.py

【除外の方針】
- EXCLUDE … 掲載してはいけない／掲載したくない実害のあるもの（理由を必ず書く）
- AROMA_KEEP … aroma は 40枚中ほぼ全部が「オイルを塗った背中に手」の同じ構図だった。
  被写体が重ならない15枚だけを残す。残りはファイルとしては消さない（manifest から外すだけ）。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(ROOT, "images")
MANIFEST = os.path.join(IMAGES, "manifest.json")

EXCLUDE = {
    # 第三者のマーク。Adobe Stock の「ai」バッジが右下に焼き込まれている（実測）
    "aroma/coran-spa-bangkok-aromatherapy-massage-04.png":
        "Adobe Stock の ai バッジが写り込んでいる",
    # CORAN 自身の旧ロゴ透かし。新しいロックアップと二重になる＋素材が 950x360 と小さい
    "herbs/coran-spa-bangkok-thai-herbal-remedy-07.png":
        "旧ロゴの透かし入り・950x360 で 4:5 に使えない",
    # Canva テンプレの告知カード。価格が焼き込まれており（TH2,000 と誤記）変更に追随できない
    "maternity-massage/coran-spa-bangkok-prenatal-maternity-massage-02.png":
        "価格を焼き込んだ Canva カード（TH2,000 は THB の誤記）",
    # Night Hotel のロビー。CORAN の空間ではなく、青紫のLED照明はブランドの配色と衝突する。
    # 建物の外観（nighthotel.building / outside-building）は「場所」として残す。
    "shop/lobby01.jpg":  "Night Hotel のロビー（CORANの空間ではない・配色が合わない）",
    "shop/lobby_01.png": "Night Hotel のロビー（CORANの空間ではない・配色が合わない）",
    "shop/lobby_02.png": "Night Hotel のロビー（CORANの空間ではない・配色が合わない）",
}

AROMA_KEEP = {
    "01", "03", "07", "13", "14", "17", "18", "21", "27", "28", "29", "36", "38",
}
AROMA_KEEP_FILES = {
    "aroma/coran-spa-bangkok-deep-tissue-massage-40.png",
    "aroma/coran-spa-bangkok-deep-tissue-massage-42.png",
}

# 建物の外観は「場所」としては使えるが、アーチ窓（お客様の声）に入れると暗く騒がしい。
# 室内と外観を分け、お客様の声は室内だけを引く。
EXTERIOR = ("building", "outside", "nighthotel")

# カテゴリ → タグ
TAGS = {
    "shop":  ["sanctuary", "interior", "shop", "ambience"],
    "award": ["sanctuary", "award", "guest"],
    "product": ["service", "product"],
}
DEFAULT_TAGS = ["service", "treatment", "ambience"]

# alt はキャプション生成に渡す「写真カテゴリ」の説明でもある。機械的な文字列にしない。
ALT = {
    "aroma": "CORAN aromatherapy oil massage",
    "award": "CORAN team with the World Luxury Spa Awards trophy",
    "body-mask": "CORAN body mask and wrap treatment",
    "body-scrub": "CORAN body scrub and exfoliation",
    "coconut": "CORAN coconut oil and hair treatment",
    "facial": "CORAN organic facial treatment",
    "foot": "CORAN foot massage and reflexology",
    "head-massage": "CORAN head, scalp and hair treatment",
    "herbal-ball": "CORAN Thai herbal compress ball",
    "herbs": "Thai herbs and remedies used at CORAN",
    "maternity-massage": "CORAN maternity and postnatal massage",
    "milk-spa": "CORAN milk bath spa treatment",
    "office-syndrome": "CORAN office syndrome relief massage",
    "product": "CORAN spa products",
    "shop": "the CORAN spa itself (reception, treatment rooms, entrance)",
}

# 1枚だけ組み方を変えたいもの
LAYOUT_OVERRIDE = {
    # 大理石に「蓮 Lotus Body Scrub & Mask」の文字が入った商品グラフィック。
    # 全面(A)にすると見出しと文字がぶつかる → 切らずに額装する C で出す
    "product/coran-spa-bangkok-lotus-body-scrub-product-01.png": "C",
}


def keep(rel):
    if rel in EXCLUDE:
        return False
    if rel.startswith("aroma/"):
        if rel in AROMA_KEEP_FILES:
            return True
        base = os.path.splitext(os.path.basename(rel))[0]
        return base.split("-")[-1] in AROMA_KEEP
    return True


def main():
    old = {}
    if os.path.exists(MANIFEST):
        for e in json.load(open(MANIFEST, encoding="utf-8")):
            old[e["file"]] = e

    out, dropped = [], []
    for root, dirs, files in os.walk(IMAGES):
        dirs[:] = [d for d in dirs if d != "generated"]   # 生成物は素材ではない
        for f in sorted(files):
            if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            rel = os.path.relpath(os.path.join(root, f), IMAGES).replace(os.sep, "/")
            if not keep(rel):
                dropped.append(rel)
                continue
            cat = rel.split("/")[0]
            tags = list(TAGS.get(cat, DEFAULT_TAGS))
            if cat == "shop" and any(k in os.path.basename(rel).lower() for k in EXTERIOR):
                tags = ["sanctuary", "exterior", "shop"]
            if cat not in tags:
                tags.append(cat)
            entry = {
                "file": rel,
                "tags": tags,
                "alt": ALT.get(cat, f"CORAN {cat.replace('-', ' ')}"),
            }
            if rel in LAYOUT_OVERRIDE:
                entry["layout"] = LAYOUT_OVERRIDE[rel]
            out.append(entry)

    out.sort(key=lambda e: e["file"])
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"manifest: {len(out)} 枚（除外 {len(dropped)} 枚）")
    cats = {}
    for e in out:
        cats[e["file"].split("/")[0]] = cats.get(e["file"].split("/")[0], 0) + 1
    for k in sorted(cats):
        print(f"  {k:20s} {cats[k]}")
    print("除外:")
    for r in dropped:
        print(f"  - {r}  {EXCLUDE.get(r, '(aroma 同一構図の間引き)')}")


if __name__ == "__main__":
    main()
