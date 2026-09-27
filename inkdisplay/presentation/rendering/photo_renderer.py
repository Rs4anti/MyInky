"""Pure Pillow pipeline for 400x300 monochrome photo frames."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

WIDTH = 400
HEIGHT = 300
FIT_MODES = {"contain", "cover", "center_crop"}
DITHER_MODES = {"none", "floyd_steinberg", "atkinson"}


@dataclass(frozen=True)
class PhotoProcessingOptions:
    fit_mode: str = "contain"
    dithering: str = "floyd_steinberg"
    contrast: float = 1.2
    sharpness: float = 1.0


class PhotoRenderer:
    @staticmethod
    def render_unavailable() -> Image.Image:
        image = Image.new("1", (WIDTH, HEIGHT), color=1)
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 18, WIDTH - 19, HEIGHT - 19), outline=0, width=2)
        message = "NESSUNA FOTO ATTIVA"
        font = ImageFont.load_default()
        text_bounds = draw.textbbox((0, 0), message, font=font)
        text_x = (WIDTH - (text_bounds[2] - text_bounds[0])) // 2
        text_y = (HEIGHT - (text_bounds[3] - text_bounds[1])) // 2
        draw.text((text_x, text_y), message, font=font, fill=0)
        return image

    def render(
        self,
        source: Image.Image,
        options: PhotoProcessingOptions | None = None,
    ) -> Image.Image:
        options = options or PhotoProcessingOptions()
        self._validate_options(options)
        corrected = ImageOps.exif_transpose(source).convert("RGB")
        fitted = self._fit(corrected, options.fit_mode)
        contrasted = ImageEnhance.Contrast(fitted).enhance(options.contrast)
        sharpened = ImageEnhance.Sharpness(contrasted).enhance(options.sharpness)
        grayscale = ImageOps.grayscale(sharpened)
        return self._dither(grayscale, options.dithering)

    @staticmethod
    def _validate_options(options: PhotoProcessingOptions) -> None:
        if options.fit_mode not in FIT_MODES:
            raise ValueError("fit_mode must be contain, cover, or center_crop.")
        if options.dithering not in DITHER_MODES:
            raise ValueError("dithering must be none, floyd_steinberg, or atkinson.")
        if not 0.0 <= options.contrast <= 3.0:
            raise ValueError("contrast must be between 0 and 3.")
        if not 0.0 <= options.sharpness <= 3.0:
            raise ValueError("sharpness must be between 0 and 3.")

    @staticmethod
    def _fit(image: Image.Image, fit_mode: str) -> Image.Image:
        target = (WIDTH, HEIGHT)
        if fit_mode == "contain":
            contained = ImageOps.contain(image, target, method=Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", target, color="white")
            offset = ((WIDTH - contained.width) // 2, (HEIGHT - contained.height) // 2)
            canvas.paste(contained, offset)
            return canvas
        if fit_mode == "cover":
            return ImageOps.fit(
                image,
                target,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )

        source_ratio = image.width / image.height
        target_ratio = WIDTH / HEIGHT
        if source_ratio > target_ratio:
            crop_width = round(image.height * target_ratio)
            left = (image.width - crop_width) // 2
            crop_box = (left, 0, left + crop_width, image.height)
        else:
            crop_height = round(image.width / target_ratio)
            top = (image.height - crop_height) // 2
            crop_box = (0, top, image.width, top + crop_height)
        return image.crop(crop_box).resize(target, Image.Resampling.LANCZOS)

    @classmethod
    def _dither(cls, grayscale: Image.Image, mode: str) -> Image.Image:
        if mode == "none":
            thresholded = grayscale.point(lambda value: 255 if value >= 128 else 0)
            return thresholded.convert("1", dither=Image.Dither.NONE)
        if mode == "floyd_steinberg":
            return grayscale.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        return cls._atkinson(grayscale)

    @staticmethod
    def _atkinson(grayscale: Image.Image) -> Image.Image:
        width, height = grayscale.size
        pixels = list(grayscale.tobytes())
        for y in range(height):
            for x in range(width):
                index = y * width + x
                old_value = pixels[index]
                new_value = 255 if old_value >= 128 else 0
                pixels[index] = new_value
                error = (old_value - new_value) // 8
                for offset_x, offset_y in (
                    (1, 0),
                    (2, 0),
                    (-1, 1),
                    (0, 1),
                    (1, 1),
                    (0, 2),
                ):
                    next_x = x + offset_x
                    next_y = y + offset_y
                    if 0 <= next_x < width and 0 <= next_y < height:
                        next_index = next_y * width + next_x
                        pixels[next_index] = max(
                            0, min(255, pixels[next_index] + error)
                        )
        output = Image.new("L", grayscale.size)
        output.putdata(pixels)
        return output.convert("1", dither=Image.Dither.NONE)
