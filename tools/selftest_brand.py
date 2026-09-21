# -*- coding: utf-8 -*-
"""
CORAN Frame のセルフテスト（ネットワーク・API・Secrets を一切使わない）。

    python tools/selftest_brand.py

見ているのは「絵が出た」ではなく、投稿事故につながる条件:
  - manifest の実体整合（存在しないファイル・除外したはずのファイル）
  - 3レイアウトが規定サイズ(1080x1350)で必ず出ること
  - 小さすぎる素材が A に回らないこと
  - 生成物が最新1枚だけになること（リポジトリ肥大の防止）
  - 巡回（service→sanctuary→service→review）と旧 rotation.json からの移行
  - 引用できる声が無いときに空の吹き出しを出さないこと
  - 生成に失敗しても素材そのままへ倒れること（投稿を止めない）
"""
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

os.environ.setdefault("IG_USER_ID", "selftest")
os.environ.setdefault("IG_ACCESS_TOKEN", "selftest")
os.environ.setdefault("IMAGE_BASE_URL", "https://raw.githubusercontent.com/o/r/main/images")
os.environ.pop("ANTHROPIC_API_KEY", None)   # テンプレ経路を確実に通す

import config          # noqa: E402
import brandkit        # noqa: E402
import brandimage      # noqa: E402
import photo_picker    # noqa: E402
import caption_ai      # noqa: E402
from PIL import Image  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail else ""))


# ---------------------------------------------------------------- 1. manifest
print("== manifest")
man = json.load(open(config.MANIFEST_PATH, encoding="utf-8"))
check("manifest が空でない", len(man) > 0, f"{len(man)} 枚")
missing = [e["file"] for e in man if not os.path.exists(os.path.join(config.IMAGES_DIR, e["file"]))]
check("manifest の全ファイルが実在する", not missing, str(missing[:3]))
check("生成物(generated/)が素材に混ざっていない",
      not [e for e in man if e["file"].startswith("generated/")])

sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_manifest  # noqa: E402
files = {e["file"] for e in man}
bad = [f for f in build_manifest.EXCLUDE if f in files]
check("除外したファイルが manifest に残っていない", not bad, str(bad))
check("aroma（元の素材）は 15 枚に絞られている",
      len([e for e in man if e["file"].startswith("aroma/") and "-src-" not in e["file"]]) == 15)
# 2026-09-21 追加分（社長の Drive 3フォルダの元写真・-src- の命名）
check("追加素材 29 枚が manifest に入っている",
      len([e for e in man if "-src-" in e["file"]]) == 29)
check("新カテゴリ（シロダーラ・タイ古式）に専用の見出しがある",
      all(c in brandimage.CATEGORY for c in ("shirodhara", "thai-massage")))
check("同じカテゴリでも写真が違えば見出しが変わる（テンプレの反復を防ぐ）",
      len({brandimage.meta_for(e)[2] for e in man if e["file"].startswith("aroma/")}) > 1)
check("お客様の声(B)の和文に施術紹介の一行を流用しない",
      all(j not in {l[1] for v in brandimage.CATEGORY.values() for l in v[2]}
          for j in brandimage.REVIEW_JA))
check("実店舗(shop)に sanctuary タグが付いている",
      all("sanctuary" in e["tags"] for e in man if e["file"].startswith("shop/")))
check("全エントリに file/tags/alt がある",
      all(e.get("file") and e.get("tags") and e.get("alt") for e in man))

# ---------------------------------------------------------------- 2. レイアウト
print("== レイアウト（3型とも 1080x1350 で出るか）")
pick = {c: next((e for e in man if e["file"].startswith(c + "/")), None)
        for c in ("aroma", "shop")}
src_a = os.path.join(config.IMAGES_DIR, pick["aroma"]["file"])
src_c = os.path.join(config.IMAGES_DIR, pick["shop"]["file"])

im = brandkit.layout_editorial(src_a, "Aromatherapy Massage",
                               "The city goes quiet under warm oil.", "温めたオイルが、都会の音を遠ざけていく。")
check("A エディトリアル", im.size == (brandkit.W, brandkit.H), str(im.size))
im_b = brandkit.layout_testimonial(src_c, "The best massage I have had in Bangkok.",
                                   "ありがとうございます。", "Guest Review · Google")
check("B お客様の声", im_b.size == (brandkit.W, brandkit.H), str(im_b.size))
im_c = brandkit.layout_sanctuary(src_c, "Our Sanctuary",
                                 "A quiet street, a quieter room.", "スクンビット soi 15、静かな一角に。")
check("C サンクチュアリ", im_c.size == (brandkit.W, brandkit.H), str(im_c.size))

# 長文・空文字でも落ちない（Claude の出力がぶれても投稿を止めない）
long_en = "A very long headline that should wrap across several lines without breaking the layout at all"
im_long = brandkit.layout_editorial(src_a, "Aromatherapy", long_en, "とても長い日本語の見出しでも折り返して崩れないことを確認するための文字列です。")
check("長文の見出しでも崩れない", im_long.size == (brandkit.W, brandkit.H))
im_empty = brandkit.layout_editorial(src_a, "Aromatherapy", "", "")
check("見出しが空でも落ちない", im_empty.size == (brandkit.W, brandkit.H))

# 4:5 に切ったあとの素材が 1080 未満＝拡大する場合でも、規定サイズで出る
with Image.open(src_a) as s:
    check("16:9 素材は smart_crop で 4:5 になる",
          brandkit.smart_crop(s).size == (brandkit.W, brandkit.H))

# ---------------------------------------------------------------- 3. レイアウト選択
print("== 組み方の選択")
aroma_e = pick["aroma"]
shop_e = pick["shop"]
check("service × aroma → A", brandimage.choose_layout("service", aroma_e, False) == "A")
check("service × shop  → C", brandimage.choose_layout("service", shop_e, False) == "C")
check("sanctuary → C", brandimage.choose_layout("sanctuary", aroma_e, False) == "C")
check("review(声あり) → B", brandimage.choose_layout("review", shop_e, True) == "B")
check("review(声なし) → 素材の既定", brandimage.choose_layout("review", aroma_e, False) == "A")
check("manifest の layout 上書きが効く",
      brandimage.choose_layout("service", {"file": "x/y.png", "layout": "C"}, False) == "C")

# ---------------------------------------------------------------- 4. build()
print("== build()")
before = set(os.listdir(config.GENERATED_DIR)) if os.path.isdir(config.GENERATED_DIR) else set()
url, rel, lay = brandimage.build("service", aroma_e, None, ("Warm oil, quiet city.", "静かな時間を。"))
check("A を生成できる", bool(url) and lay == "A", str(rel))
check("公開URLが IMAGE_BASE_URL から始まる", bool(url) and url.startswith(config.IMAGE_BASE_URL))
out_path = os.path.join(config.IMAGES_DIR, rel) if rel else ""
check("生成物が 1080x1350 の JPEG", bool(rel) and Image.open(out_path).size == (1080, 1350))
check("生成物が 2MB 未満（IG の取得に無理がない）",
      bool(rel) and os.path.getsize(out_path) < 2 * 1024 * 1024,
      f"{os.path.getsize(out_path)//1024}KB" if rel else "")

url2, rel2, lay2 = brandimage.build("sanctuary", shop_e, None, None)
check("C を生成できる", bool(url2) and lay2 == "C", str(rel2))
left = [f for f in os.listdir(config.GENERATED_DIR) if f.endswith(".jpg")]
check("生成物は最新1枚だけが残る", len(left) == 1, str(left))

url3, rel3, lay3 = brandimage.build("review", shop_e,
                                    {"text": "Truly the best massage I have had in Bangkok, thank you."}, None)
check("B を生成できる", bool(url3) and lay3 == "B", str(rel3))
url4, rel4, lay4 = brandimage.build("review", shop_e, {"text": "   "}, None)
check("引用できる声が無ければ B にしない（空の吹き出しを出さない）", lay4 == "C", str(lay4))

u, r, l = brandimage.build("service", {"file": "no/such-file.png"}, None, None)
check("素材が無いときは None を返す（呼び出し側が素材そのままへ倒れる）",
      (u, r, l) == (None, None, None))

# 小さすぎる素材は A ではなく C へ逃がす
tiny = os.path.join(config.IMAGES_DIR, "generated", "_tiny.png")
Image.new("RGB", (950, 360), (120, 90, 70)).save(tiny)
try:
    _, _, lt = brandimage.build("service", {"file": "generated/_tiny.png"}, None, None)
    check("横が細い素材は A→C に逃げる", lt == "C", str(lt))
finally:
    if os.path.exists(tiny):
        os.remove(tiny)

# ---------------------------------------------------------------- 5. 巡回
print("== 投稿の巡回")
import main as main_mod  # noqa: E402


def next_of(state):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(state, fh)
        path = fh.name
    old = config.ROTATION_STATE_PATH
    config.ROTATION_STATE_PATH = path
    try:
        return main_mod._next_post_type()
    finally:
        config.ROTATION_STATE_PATH = old
        os.remove(path)


check("巡回は 4 手（明暗が交互になる）", main_mod.POST_CYCLE == ["service", "sanctuary", "service", "review"])
seq = []
st = {"last": "review", "seq": 3}
for _ in range(8):
    t, n = next_of(st)
    seq.append(t)
    st = {"last": t, "seq": n}
check("8回まわして巡回どおり",
      seq == ["service", "sanctuary", "service", "review"] * 2, str(seq))
check("旧 rotation.json（last だけ）から移行できる", next_of({"last": "service"})[0] == "sanctuary")
check("壊れた rotation.json でも落ちない", next_of({})[0] == "service")

# ---------------------------------------------------------------- 6. 見出し
print("== 見出し")
check("APIキーが無ければ None（テンプレへ）",
      caption_ai.build_image_headline("service", aroma_e, None, "Aromatherapy") is None)
check("英語42字に丸める", len(caption_ai._clip("x" * 80, 42)) == 42)
check("日本語26字に丸める", len(caption_ai._clip("あ" * 80, 26)) == 26)
e, l, en, ja = brandimage.meta_for(aroma_e)[0], None, None, None
check("カテゴリ別の小見出しが引ける", brandimage.meta_for(aroma_e)[0] == "Aromatherapy Massage")
check("未知カテゴリでも既定に落ちる", brandimage.meta_for({"file": "zzz/a.png"})[1] == "A")

# ---------------------------------------------------------------- 7. 写真選択
print("== 写真選択")
# main.py が実際に使う条件で20回引き、実店舗/受賞だけが出ることを確かめる
#   （"ambience" を条件に入れると施術写真も一致してしまう＝一度踏んだ穴）
import importlib  # noqa: E402
src_main = io.open(os.path.join(ROOT, "src", "main.py"), encoding="utf-8").read()
check("sanctuary の条件に ambience を入れていない",
      '"sanctuary": ["sanctuary"],' in src_main)
check("お客様の声(B)は室内だけを引く（外観をアーチ窓に入れない）",
      '"review":    ["interior"],' in src_main)
ext = [e for e in man if "exterior" in e["tags"]]
check("建物の外観は interior から外れている",
      bool(ext) and all("interior" not in e["tags"] for e in ext), str([e["file"] for e in ext]))
for _ in range(20):
    pi, _u = photo_picker.pick_photo(preferred_tags=["interior"])
    if "interior" not in pi["tags"]:
        break
else:
    pi = None
check("interior 条件で外観が出てこない", pi is None)
cats = set()
for _ in range(20):
    p1, _u = photo_picker.pick_photo(preferred_tags=["sanctuary"])
    cats.add(p1["file"].split("/")[0])
check("sanctuary タグは実店舗/受賞しか引かない", cats <= {"shop", "award"}, str(sorted(cats)))
p2, u2 = photo_picker.pick_photo(preferred_tags=["service", "treatment"])
check("service タグで素材が選ばれる", bool(p2["file"]))

print()
print(f"== {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
