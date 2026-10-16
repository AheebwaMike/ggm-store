from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT_DIR / 'static' / 'icons'
ORANGE = '#ea580c'
WHITE = '#ffffff'


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_paths = [
        Path('C:/Windows/Fonts/arialbd.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ]
    for font_path in font_paths:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)
    return ImageFont.truetype('DejaVuSans-Bold.ttf', size)


def make_icon(size: int, maskable: bool = False) -> Image.Image:
    image = Image.new('RGB', (size, size), ORANGE)
    draw = ImageDraw.Draw(image)
    font_size = round(size * (0.6 if maskable else 0.72))
    draw.text(
        (size / 2, size / 2),
        'G',
        fill=WHITE,
        font=load_font(font_size),
        anchor='mm',
    )
    return image


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        ('icon-192.png', make_icon(192)),
        ('icon-512.png', make_icon(512)),
        ('icon-maskable-192.png', make_icon(192, maskable=True)),
        ('icon-maskable-512.png', make_icon(512, maskable=True)),
        ('apple-touch-icon.png', make_icon(180)),
        ('favicon.ico', make_icon(32)),
    ]
    for filename, image in files:
        image.save(ICONS_DIR / filename)

    print('Generated PWA icons:')
    for filename, _ in files:
        print(f'- {ICONS_DIR / filename}')


if __name__ == '__main__':
    main()
