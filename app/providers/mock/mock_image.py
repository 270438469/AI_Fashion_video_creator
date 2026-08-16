from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from app.domain.models import Asset
from app.providers.base.image_provider import ImageProvider


class MockImageProvider(ImageProvider):
    async def generate_keyframe(self, character_refs: list[Path], product_image: Path, prompt: str, output_path: Path) -> Asset:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(product_image) as source:
            source = source.convert("RGB")
            source.thumbnail((280, 390))
            background = Image.new("RGB", (360, 640), "#eee7df")
            backdrop = Image.new("RGB", background.size, "#c9b7a8").filter(ImageFilter.GaussianBlur(20))
            background = Image.blend(background, backdrop, 0.18)
            x = (360 - source.width) // 2
            y = 100 + (390 - source.height) // 2
            shadow = Image.new("RGBA", background.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle((x-10, y-10, x+source.width+10, y+source.height+10), 20, fill=(40,30,25,45))
            shadow = shadow.filter(ImageFilter.GaussianBlur(14))
            background = Image.alpha_composite(background.convert("RGBA"), shadow)
            background.paste(source, (x, y))
            draw = ImageDraw.Draw(background)
            shot = output_path.stem
            draw.rounded_rectangle((18, 18, 342, 72), 12, fill=(34, 29, 26, 220))
            draw.text((34, 32), f"MOCK KEYFRAME  {shot}", fill="white")
            draw.text((20, 604), "AI Fashion Video Director · offline mock", fill="#403832")
            background.convert("RGB").save(output_path, "PNG")
        return Asset(path=str(output_path), media_type="image/png")

