from pathlib import Path
from PIL import Image, ImageDraw


root = Path(r"C:\Users\jctx\Desktop\AR\output\meetings\render_mentor_brief")
pages = sorted(root.glob("page-*.png"))
thumb_w = 510
gap = 24
label_h = 30
for start in range(0, len(pages), 4):
    subset = pages[start:start + 4]
    thumbs = []
    for page in subset:
        img = Image.open(page).convert("RGB")
        ratio = thumb_w / img.width
        thumb = img.resize((thumb_w, int(img.height * ratio)))
        thumbs.append((page, thumb))
    h = max(t.height for _, t in thumbs)
    sheet = Image.new("RGB", (2 * thumb_w + 3 * gap, 2 * (h + label_h) + 3 * gap), "#D9DEE7")
    draw = ImageDraw.Draw(sheet)
    for idx, (page, thumb) in enumerate(thumbs):
        row, col = divmod(idx, 2)
        x = gap + col * (thumb_w + gap)
        y = gap + row * (h + label_h + gap)
        sheet.paste(thumb, (x, y + label_h))
        draw.text((x, y + 6), page.stem, fill="#17365D")
    sheet.save(root / f"contact-{start // 4 + 1}.png")
print(len(pages), "pages", (len(pages) + 3) // 4, "contact sheets")
