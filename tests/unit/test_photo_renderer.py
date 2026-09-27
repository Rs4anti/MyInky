from PIL import Image

from inkdisplay.presentation.rendering.photo_renderer import (
    PhotoProcessingOptions,
    PhotoRenderer,
)


def test_photo_renderer_outputs_400x300_one_bit_for_each_dither() -> None:
    source = Image.new("RGB", (900, 600), color=(120, 80, 40))
    renderer = PhotoRenderer()

    for mode in ("none", "floyd_steinberg", "atkinson"):
        frame = renderer.render(source, PhotoProcessingOptions(dithering=mode))
        assert frame.size == (400, 300)
        assert frame.mode == "1"


def test_photo_renderer_accepts_all_fit_modes() -> None:
    source = Image.new("RGB", (300, 900), color="white")
    renderer = PhotoRenderer()

    for mode in ("contain", "cover", "center_crop"):
        frame = renderer.render(source, PhotoProcessingOptions(fit_mode=mode))
        assert frame.size == (400, 300)
        assert frame.mode == "1"
