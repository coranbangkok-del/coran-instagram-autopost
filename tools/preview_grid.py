# -*- coding: utf-8 -*-
"""
巡回どおりに9枚組んで、プロフィールのグリッドでどう見えるかを1枚の画像にする。

    python tools/preview_grid.py [出力先.jpg]

確かめたいのは1枚の出来ではなく「3列に並べたときに明暗のリズムが出るか」。
出力はリポジトリに入れない（既定の出力先は .preview/）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
os.environ.setdefault("IG_USER_ID", "preview")
os.environ.setdefault("IG_ACCESS_TOKEN", "preview")
os.environ.setdefault("IMAGE_BASE_URL", "https://example.invalid/images")

import json           # noqa: E402
import config         # noqa: E402
import brandkit       # noqa: E402
import brandimage     # noqa: E402
from PIL import Image  # noqa: E402

CYCLE = ["service", "sanctuary", "service", "review"]
REVIEW = {"text": "The best massage I have had in Bangkok. I slept like a child that night."}

TW, TH, GAP = 360, 450, 4


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(config.ROOT, ".preview", "grid.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    man = json.load(open(config.MANIFEST_PATH, encoding="utf-8"))

    def pool(tag):
        return [e for e in man if tag in e["tags"]]

    service = pool("service")
    sanctuary = pool("sanctuary")
    interior = pool("interior")
    tiles, si, ci = [], 0, 0
    for i in range(9):
        kind = CYCLE[i % len(CYCLE)]
        if kind == "service":
            photo = service[si * 7 % len(service)]
            si += 1
            review = None
        elif kind == "review":
            photo = interior[ci * 5 % len(interior)]
            ci += 1
            review = REVIEW
        else:
            photo = sanctuary[ci * 5 % len(sanctuary)]
            ci += 1
            review = None
        img, layout = brandimage.render(kind, photo, review, None)
        print(f"{i+1}. {kind:9s} {layout}  {photo['file']}")
        tiles.append(img.resize((TW, TH), Image.LANCZOS))

    sheet = Image.new("RGB", (3 * TW + 2 * GAP, 3 * TH + 2 * GAP), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * (TW + GAP), (i // 3) * (TH + GAP)))
    sheet.save(out, quality=90)
    print("→", out, sheet.size)


if __name__ == "__main__":
    main()
