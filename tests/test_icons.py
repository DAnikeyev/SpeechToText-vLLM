from __future__ import annotations

import unittest

from PIL import Image

import app.icons as icons_module


class IconTests(unittest.TestCase):
    def test_fit_icon_to_canvas_reduces_padding(self) -> None:
        source = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        for x in range(4, 12):
            for y in range(4, 12):
                source.putpixel((x, y), (255, 255, 255, 255))

        fitted = icons_module.fit_icon_to_canvas(source)
        source_bbox = source.getchannel("A").getbbox()
        fitted_bbox = fitted.getchannel("A").getbbox()

        self.assertEqual(fitted.size, source.size)
        self.assertEqual(source_bbox, (4, 4, 12, 12))
        self.assertIsNotNone(fitted_bbox)
        self.assertLessEqual(fitted_bbox[0], 1)
        self.assertLessEqual(fitted_bbox[1], 1)
        self.assertGreaterEqual(fitted_bbox[2], 15)
        self.assertGreaterEqual(fitted_bbox[3], 15)

    def test_tint_icon_preserves_alpha_and_applies_color(self) -> None:
        original_base_icon = icons_module._BASE_ICON
        try:
            base_icon = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
            base_icon.putpixel((0, 0), (255, 255, 255, 255))
            base_icon.putpixel((1, 0), (255, 255, 255, 0))
            icons_module._BASE_ICON = base_icon

            active_icon = icons_module.tint_icon(paused=False)
            paused_icon = icons_module.tint_icon(paused=True)

            self.assertEqual(active_icon.getpixel((0, 0))[3], 255)
            self.assertEqual(active_icon.getpixel((1, 0))[3], 0)
            self.assertGreater(active_icon.getpixel((0, 0))[1], active_icon.getpixel((0, 0))[0])
            self.assertGreater(paused_icon.getpixel((0, 0))[0], paused_icon.getpixel((0, 0))[1])
        finally:
            icons_module._BASE_ICON = original_base_icon


if __name__ == "__main__":
    unittest.main()
