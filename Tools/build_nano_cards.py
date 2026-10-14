#!/usr/bin/env python3
"""Nano Banana arka planlarindan Fecr kartlari uretir.

Kullanim:
  1) Tools/nano_cards.json icindeki 'prompt' ile metinsiz arka plani uretin
     ve /tmp/nano-bg/<id>.jpg olarak kaydedin (or. ayet-06.jpg).
  2) python3 Tools/build_nano_cards.py [--bg-dir /tmp/nano-bg] [--only ayet-06,hadis-07]

Cikti: ilgili klasore 1200x800 JPG (mevcut kartlarla ayni boyut).
Tasarim: fotograf uzerine koyu degrade + solda serif baslik, referans,
ustte FECR/altin gunes, altta 'Oku - Dusun - Yasa' (mevcut sablonla uyumlu).
Metin AI'a CIZDIRILMEZ; bu script yerlestirir, boylece ayet/hadis hatasiz kalir.
"""
import argparse, json, sys, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "Tools" / "nano_cards.json"
W, H = 1200, 800
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
GOLD = (232, 197, 122)
WHITE = (255, 252, 245)

def font(path, size):
    return ImageFont.truetype(path, size)

def fit_font(draw, text, max_w, start, min_size=30):
    size = start
    while size > min_size:
        f = font(SERIF, size)
        # wrap with this font
        words, lines, cur = text.split(), [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if draw.textlength(t, font=f) <= max_w:
                cur = t
            else:
                if cur: lines.append(cur)
                cur = w_
        if cur: lines.append(cur)
        if len(lines) <= 4 and all(draw.textlength(l, font=f) <= max_w for l in lines):
            return f, lines
        size -= 4
    return font(SERIF, min_size), lines

def render(card, bg_path, out_path):
    bg = Image.open(bg_path).convert("RGB")
    # center-crop to 3:2 then resize
    tw, th = W, H
    scale = max(tw / bg.width, th / bg.height)
    bg = bg.resize((int(bg.width*scale+0.5), int(bg.height*scale+0.5)), Image.LANCZOS)
    x = (bg.width - tw)//2; y = (bg.height - th)//2
    img = bg.crop((x, y, x+tw, y+th))

    # dark overlay: full dim + left/bottom gradient for legibility
    overlay = Image.new("L", (W, H), 0)
    od = ImageDraw.Draw(overlay)
    for yy in range(H):
        # stronger at bottom & middle-left text zone
        a = int(90 + 110 * (yy / H))
        od.line([(0, yy), (W, yy)], fill=a)
    # left vignette
    left = Image.new("L", (W, H), 0)
    ld = ImageDraw.Draw(left)
    for xx in range(W):
        a = int(max(0, 130 * (1 - xx / (W*0.85))))
        ld.line([(xx, 0), (xx, H)], fill=a)
    from PIL import ImageChops
    overlay = ImageChops.lighter(overlay, left)
    black = Image.new("RGB", (W, H), (8, 18, 20))
    img = Image.composite(black, img, overlay.point(lambda v: int(v*0.82)))

    d = ImageDraw.Draw(img, "RGBA")
    # top-left brand
    d.text((64, 62), "FECR", font=font(SANS_B, 26), fill=GOLD)
    d.text((64, 94), card["etiket"], font=font(SANS_B, 24), fill=WHITE)
    # gold sun top-right (mevcut sablon)
    d.ellipse([1015, 62, 1115, 162], fill=GOLD)
    d.ellipse([1104, 148, 1128, 172], fill=GOLD)

    # main text
    f_main, lines = fit_font(d, card["metin"], 1000, 62)
    ty = 235
    # if 3-4 lines, start a bit higher
    if len(lines) >= 3: ty = 205
    for line in lines:
        d.text((64, ty), line, font=f_main, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0))
        ty += int(f_main.size * 1.22)
    ty += 18
    d.text((64, ty), card["referans"], font=font(SANS, 27), fill=(255,252,245))

    # bottom rule + motto
    d.line([(64, 680), (1136, 680)], fill=GOLD, width=3)
    d.text((64, 702), "Oku  \u2022  Düşün  \u2022  Yaşa", font=font(SANS, 26), fill=WHITE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg-dir", default="/tmp/nano-bg")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    bg_dir = Path(args.bg_dir)
    done, missing = 0, []
    for card in data["kartlar"]:
        if only and card["id"] not in only: continue
        bg = bg_dir / f'{card["id"]}.jpg'
        if not bg.exists():
            # fallback png/jpeg
            alt = list(bg_dir.glob(card["id"] + ".*"))
            if alt: bg = alt[0]
            else:
                missing.append(card["id"]); continue
        out = ROOT / card["klasor"] / card["dosya"]
        render(card, bg, out)
        print(f'OK {card["id"]} -> {card["klasor"]}/{card["dosya"]}')
        done += 1
    if missing: print("EKSIK ARKA PLAN:", ", ".join(missing), file=sys.stderr)
    print(f"{done} kart uretildi, {len(missing)} eksik")
    return 0 if done else 1

if __name__ == "__main__":
    sys.exit(main())
