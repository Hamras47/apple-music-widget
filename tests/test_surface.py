"""The face: it draws, it is transparent where it should be, and its buttons are where the
mouse will look for them."""

import unittest

from PIL import Image

import surface
import track

WIDTH = int(surface.WINDOW_W * 1.5)
HEIGHT = surface.height_for(WIDTH)


def playing_view(**changes):
    values = dict(title="Nightcall", artist="Kavinsky", playing=True, position=60,
                  duration=258, art=Image.new("RGB", (64, 64), (200, 30, 60)), idle=False)
    values.update(changes)
    return surface.View(**values)


class SurfaceTests(unittest.TestCase):
    def render(self, view, style="glass", hover=None):
        return surface.Painter().render(view, WIDTH, HEIGHT, style, hover)

    def test_both_styles_draw_at_the_window_size(self):
        for style in surface.STYLES:
            picture = self.render(playing_view(), style)
            self.assertEqual(len(picture.pixels), WIDTH * HEIGHT * 4)

    def test_the_corners_of_the_window_are_the_desktop(self):
        image = surface.straight(self.render(playing_view()))
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(image.getpixel((WIDTH - 1, 0))[3], 0)

    def test_glass_is_solid_in_the_middle_and_clear_is_not(self):
        x, y = WIDTH - 20, HEIGHT // 2 - 30
        glass = surface.straight(self.render(playing_view(), "glass"))
        clear = surface.straight(self.render(playing_view(), "clear"))
        self.assertGreater(glass.getpixel((x, y))[3], 200)
        self.assertLessEqual(clear.getpixel((x, y))[3], 40)

    def test_clear_still_answers_the_mouse_across_the_card(self):
        picture = self.render(playing_view(), "clear")
        alpha = surface.straight(picture).getchannel("A")
        left, top, right, bottom = picture.card
        self.assertGreaterEqual(min(alpha.crop((left, top, right, bottom)).getdata()), 1)

    def test_buttons_are_found_where_they_are_drawn(self):
        picture = self.render(playing_view())
        geo = surface.layout(WIDTH, HEIGHT)
        for name, x, y in geo.button_centres():
            self.assertEqual(picture.button_at(int(x), int(y)), name)
        left, right = picture.bar
        self.assertEqual(picture.button_at((left + right) // 2, int(geo.y(surface.BAR_Y))),
                         "seek")
        self.assertAlmostEqual(picture.seek_fraction((left + right) // 2), 0.5, places=1)

    def test_idle_has_no_seek_bar(self):
        view = surface.view_of(track.IDLE, False, 0)
        self.assertTrue(view.idle)
        picture = self.render(view)
        self.assertNotIn("seek", dict(picture.buttons))

    def test_a_long_title_is_cut_with_an_ellipsis(self):
        face = surface.font(surface.TITLE_FONTS, 22)
        cut = surface.ellipsize("A" * 200, face, 150)
        self.assertTrue(cut.endswith("…"))
        self.assertLessEqual(face.getlength(cut), 150)


if __name__ == "__main__":
    unittest.main()


class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.picture = surface.Painter().render(playing_view(), WIDTH, HEIGHT, "glass", None)
        self.left, self.top, self.right, self.bottom = self.picture.card

    def test_corners_and_edges(self):
        p, l, t, r, b = self.picture, self.left, self.top, self.right, self.bottom
        mid_x, mid_y = (l + r) // 2, (t + b) // 2
        self.assertEqual(p.edge_at(r - 2, b - 2), "se")
        self.assertEqual(p.edge_at(l + 1, t + 1), "nw")
        self.assertEqual(p.edge_at(r - 2, mid_y), "e")
        self.assertEqual(p.edge_at(mid_x, b - 2), "s")
        self.assertEqual(p.edge_at(mid_x, t + 1), "n")

    def test_corner_zone_runs_along_the_edge(self):
        self.assertEqual(self.picture.edge_at(self.right - 2, self.bottom - 20), "se")

    def test_the_inside_and_the_buttons_are_not_edges(self):
        geo = surface.layout(WIDTH, HEIGHT)
        for _, x, y in geo.button_centres():
            self.assertIsNone(self.picture.edge_at(int(x), int(y)))
        self.assertIsNone(self.picture.edge_at(0, 0))
