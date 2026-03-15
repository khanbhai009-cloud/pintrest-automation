import io
import logging
import httpx
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Pinterest optimal size
PIN_WIDTH  = 1000
PIN_HEIGHT = 1500


async def _download_image(url: str) -> Image.Image:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, follow_redirects=True)
    return Image.open(io.BytesIO(r.content)).convert("RGBA")


def _add_overlay(image: Image.Image, title: str, cta: str = "Tap to Learn More →") -> Image.Image:
    """Resize + dark gradient overlay + text"""
    
    # Resize to Pinterest ratio
    image = image.resize((PIN_WIDTH, PIN_HEIGHT), Image.LANCZOS)
    
    # Dark gradient from bottom half
    overlay = Image.new("RGBA", (PIN_WIDTH, PIN_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    for y in range(PIN_HEIGHT // 2, PIN_HEIGHT):
        alpha = int(220 * (y - PIN_HEIGHT // 2) / (PIN_HEIGHT // 2))
        draw.rectangle([(0, y), (PIN_WIDTH, y + 1)], fill=(0, 0, 0, alpha))

    result = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(result)

    # Load fonts (fallback to default if not found)
    try:
        font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 58
        )
        font_reg = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36
        )
    except:
        font_bold = ImageFont.load_default()
        font_reg  = ImageFont.load_default()

    # Title (wrap long text)
    words = title.split()
    lines, line = [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if len(test) <= 28:
            line = test
        else:
            lines.append(line)
            line = word
    lines.append(line)

    y_text = PIN_HEIGHT - 280
    for line in lines[-3:]:  # max 3 lines
        draw.text((60, y_text), line, font=font_bold, fill=(255, 255, 255, 255))
        y_text += 70

    # CTA
    draw.text((60, PIN_HEIGHT - 80), cta, font=font_reg, fill=(200, 200, 200, 220))

    return result.convert("RGB")


async def process_product_image(image_url: str, title: str) -> bytes | None:
    """Full pipeline → returns JPEG bytes"""
    try:
        image = await _download_image(image_url)
        enhanced = _add_overlay(image, title)
        
        buf = io.BytesIO()
        enhanced.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    
    except Exception as e:
        logger.error(f"❌ Image processing failed: {e}")
        return None

# ─────────────────────────────────────────
# FUTURE: Add generate_ai_image() using
# Stability AI for Level 3 full AI images
# ─────────────────────────────────────────
