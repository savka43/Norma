from dataclasses import dataclass
from io import BytesIO
from warnings import catch_warnings, simplefilter

from PIL import Image

IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG"}
MAX_IMAGE_PIXELS = 20_000_000


class InvalidImage(ValueError):
    pass


class ImageLimitExceeded(InvalidImage):
    pass


@dataclass(frozen=True)
class NormalizedImage:
    data: bytes
    width: int
    height: int


def normalize_image(
    data: bytes, *, media_type: str | None = None, pixel_limit: int = MAX_IMAGE_PIXELS
) -> NormalizedImage:
    formats = [IMAGE_FORMATS[media_type]] if media_type else list(IMAGE_FORMATS.values())
    try:
        with catch_warnings():
            simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=formats) as image:
                if image.width * image.height > pixel_limit:
                    raise ImageLimitExceeded("Image pixel limit exceeded")
                image.load()
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                output = BytesIO()
                with image.convert("RGBA" if has_alpha else "RGB") as clean:
                    clean.info.clear()
                    clean.save(output, format="PNG")
                return NormalizedImage(output.getvalue(), image.width, image.height)
    except ImageLimitExceeded:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ImageLimitExceeded("Image pixel limit exceeded") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise InvalidImage("Expected a decodable PNG or JPEG image matching Content-Type") from exc
