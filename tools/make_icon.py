"""Gera o icone do aplicativo (assets/app.ico) sem dependencias externas alem do Pillow."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "app.ico")
SIZE = 256
BG = (14, 22, 32, 255)
ACCENT = (0, 210, 180, 255)
DARK = (8, 18, 26, 255)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=56, fill=ACCENT)
d.rounded_rectangle((34, 34, SIZE - 34, SIZE - 34), radius=40, fill=BG)

font = None
for candidate in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
    if os.path.exists(candidate):
        font = ImageFont.truetype(candidate, 132)
        break
text = "A"
if font:
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((SIZE - w) / 2 - box[0], (SIZE - h) / 2 - box[1] - 6), text, font=font, fill=ACCENT)
else:
    d.text((96, 84), text, fill=ACCENT)

# seta de backup no canto
d.polygon([(150, 168), (188, 168), (188, 140), (210, 176), (188, 212), (188, 184), (150, 184)],
          fill=DARK)
d.ellipse((60, 176, 84, 200), fill=DARK)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT, format="ICO", sizes=sizes)
print("icone:", OUT, os.path.getsize(OUT), "bytes")
