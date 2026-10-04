"""The face, drawn by us -- the same reason as the clock's surface.py.

A WebView2 window cannot be see-through on this machine, so the widget is a 32-bit image
handed to Windows as a per-pixel alpha layered window.  Two styles:

* glass -- a rounded card filled with the cover art, blurred, deepened and tinted, so the
  widget takes its colour from the song.  A soft shadow lifts it off the wallpaper.
* clear -- no card at all: the cover, the text and the controls float on the wallpaper with a
  halo behind them, like the clock.  The card area carries an alpha of 1 so it still drags.

Everything is laid out in CSS pixels on a fixed design (WINDOW_W x WINDOW_H) and scaled by
`u`, physical pixels per design pixel, so a resize scales the whole widget.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import track

MARGIN = 10.0
CARD_W, CARD_H = 340.0, 112.0
WINDOW_W, WINDOW_H = CARD_W + 2 * MARGIN, CARD_H + 2 * MARGIN
RADIUS = 26.0
PAD = 12.0
ART = 88.0
ART_RADIUS = 15.0
GAP = 15.0
RIGHT_PAD = 18.0
#: Rows, measured from the card's top edge.
TITLE_Y, ARTIST_Y, CONTROLS_Y, BAR_Y = 15.0, 37.0, 66.0, 95.0
TITLE_SIZE, ARTIST_SIZE, TIME_SIZE = 15.0, 12.5, 10.0
BUTTON_R = 16.0
SKIP_DX = 44.0
PLAY_SIZE, SKIP_SIZE = 19.0, 24.0
TIME_W = 30.0
BAR_H, BAR_H_HOVER = 4.0, 6.0
#: Resizing: a band this wide just inside every edge of the card, and corners this long.
EDGE = 8.0
CORNER = 24.0

#: Shapes are drawn this many times larger and scaled down: PIL does not antialias polygons.
SS = 3
HIT_ALPHA = 1
GLASS_ALPHA = 232
STYLES = ("glass", "clear")

TITLE_FONTS = ("seguisb.ttf", "segoeuib.ttf", "arial.ttf")
TEXT_FONTS = ("segoeui.ttf", "arial.ttf")
NUMBER_FONTS = ("seguisb.ttf", "segoeui.ttf", "arial.ttf")
SYMBOL_FONTS = ("seguisym.ttf", "segoeui.ttf")

WHITE = (255, 255, 255)


@dataclass(frozen=True)
class View:
    """What the face shows, already decided: the host turns a NowPlaying into this."""

    title: str
    artist: str
    playing: bool
    position: float
    duration: float
    art: object  # PIL image or None
    idle: bool


@dataclass(frozen=True)
class Render:
    pixels: bytes
    width: int
    height: int
    card: tuple[int, int, int, int]
    #: The resize band's width and the corner zones' length, in image pixels.
    edge: int
    corner: int
    buttons: tuple[tuple[str, tuple[int, int, int, int]], ...]
    #: The seek bar's left and right ends, in image pixels.
    bar: tuple[int, int]

    def button_at(self, x: int, y: int) -> str | None:
        for name, box in self.buttons:
            if _inside(box, x, y):
                return name
        return None

    def in_card(self, x: int, y: int) -> bool:
        return _inside(self.card, x, y)

    def edge_at(self, x: int, y: int) -> str | None:
        """Which resize zone the point is in: n, s, e, w, ne, nw, se, sw -- or None."""
        if not self.in_card(x, y):
            return None
        left, top, right, bottom = self.card
        across = "w" if x < left + self.edge else "e" if x >= right - self.edge else ""
        down = "n" if y < top + self.edge else "s" if y >= bottom - self.edge else ""
        if across and not down:
            down = "n" if y < top + self.corner else "s" if y >= bottom - self.corner else ""
        elif down and not across:
            across = "w" if x < left + self.corner else "e" if x >= right - self.corner else ""
        return (down + across) or None

    def seek_fraction(self, x: int) -> float:
        left, right = self.bar
        if right <= left:
            return 0.0
        return max(0.0, min(1.0, (x - left) / (right - left)))


def _inside(box: tuple[int, int, int, int], x: int, y: int) -> bool:
    left, top, right, bottom = box
    return left <= x < right and top <= y < bottom


def height_for(width: int) -> int:
    return max(1, int(round(width * WINDOW_H / WINDOW_W)))


@lru_cache(maxsize=64)
def _font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for name in candidates:
        path = Path(r"C:\Windows\Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), max(1, size))
            except OSError:
                continue
    return ImageFont.load_default(max(1, size))


def font(candidates: tuple[str, ...], size: float) -> ImageFont.FreeTypeFont:
    return _font(candidates, int(round(size)))


@lru_cache(maxsize=16)
def _rounded_mask(width: int, height: int, radius: int) -> Image.Image:
    big = Image.new("L", (width * 4, height * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, width * 4 - 1, height * 4 - 1), radius=radius * 4, fill=255
    )
    return big.resize((width, height), Image.LANCZOS)


@lru_cache(maxsize=1)
def placeholder_art(size: int = 512) -> Image.Image:
    """Apple Music's own pink-to-red, with a note: what shows when nothing is playing."""
    corners = Image.new("RGB", (2, 2))
    corners.putdata([(255, 112, 140), (252, 72, 104), (250, 60, 90), (214, 22, 52)])
    image = corners.resize((size, size), Image.BICUBIC)
    draw = ImageDraw.Draw(image)
    draw.text((size * 0.5, size * 0.53), "\u266b", font=font(SYMBOL_FONTS, size * 0.5),
              fill=WHITE, anchor="mm")
    return image


def ellipsize(text: str, face: ImageFont.FreeTypeFont, limit: float) -> str:
    if face.getlength(text) <= limit:
        return text
    while text and face.getlength(text + "\u2026") > limit:
        text = text[:-1]
    return text.rstrip() + "\u2026"


def _shadow(alpha: Image.Image, opacity: float, blur: float,
            offset: tuple[int, int] = (0, 0)) -> Image.Image:
    """A black layer shaped like `alpha`, softened."""
    shaped = Image.new("L", alpha.size, 0)
    shaped.paste(alpha.point(lambda v: int(v * opacity)), offset)
    if blur > 0:
        shaped = shaped.filter(ImageFilter.GaussianBlur(blur))
    black = Image.new("L", alpha.size, 0)
    return Image.merge("RGBA", (black, black, black, shaped))


# ------------------------------------------------------------------ layout ---


@dataclass(frozen=True)
class Layout:
    u: float
    width: int
    height: int
    card: tuple[int, int, int, int]
    art: tuple[int, int, int]  # x, y, size
    text_left: int
    text_right: int

    @property
    def controls_mid(self) -> float:
        return (self.text_left + self.text_right) / 2

    def y(self, row: float) -> float:
        return self.card[1] + row * self.u

    def bar(self) -> tuple[int, int]:
        return (int(self.text_left + TIME_W * self.u), int(self.text_right - TIME_W * self.u))

    def button_centres(self) -> tuple[tuple[str, float, float], ...]:
        cy = self.y(CONTROLS_Y)
        mid = self.controls_mid
        return (
            ("prev", mid - SKIP_DX * self.u, cy),
            ("play", mid, cy),
            ("next", mid + SKIP_DX * self.u, cy),
        )


def layout(width: int, height: int) -> Layout:
    u = width / WINDOW_W
    left, top = round(MARGIN * u), round(MARGIN * u)
    card = (left, top, left + round(CARD_W * u), top + round(CARD_H * u))
    art = (left + round(PAD * u), top + round(PAD * u), round(ART * u))
    text_left = art[0] + art[2] + round(GAP * u)
    return Layout(u, width, height, card, art, text_left, card[2] - round(RIGHT_PAD * u))


# ------------------------------------------------------------------ drawing ---


def _base(view: View, geo: Layout, style: str) -> Image.Image:
    """Everything that changes only with the track: card, cover, title, artist."""
    u, (cx0, cy0, cx1, cy1) = geo.u, geo.card
    cw, ch = cx1 - cx0, cy1 - cy0
    image = Image.new("RGBA", (geo.width, geo.height), (0, 0, 0, 0))
    art = view.art if view.art is not None else placeholder_art()

    if style == "glass":
        mask = _rounded_mask(cw, ch, round(RADIUS * u))
        whole = Image.new("L", image.size, 0)
        whole.paste(mask, (cx0, cy0))
        image = Image.alpha_composite(
            image, _shadow(whole, 0.42, 6 * u, (0, round(2 * u)))
        )
        small = ImageOps.fit(art, (max(1, cw // 10), max(1, ch // 10)), Image.BICUBIC)
        small = small.filter(ImageFilter.GaussianBlur(2.2))
        fill = small.resize((cw, ch), Image.BICUBIC)
        fill = ImageEnhance.Color(fill).enhance(1.45)
        fill = ImageEnhance.Brightness(fill).enhance(0.52)
        # A faint sheen down from the top edge, the way light sits on glass.
        sheen = Image.linear_gradient("L").resize((cw, ch)).point(lambda v: int((255 - v) * 0.09))
        fill = Image.composite(Image.new("RGB", (cw, ch), WHITE), fill, sheen)
        card = fill.convert("RGBA")
        card.putalpha(mask.point(lambda v: v * GLASS_ALPHA // 255))
        image.alpha_composite(card, (cx0, cy0))
        rim = Image.new("RGBA", (cw * 4, ch * 4), (0, 0, 0, 0))
        ImageDraw.Draw(rim).rounded_rectangle(
            (0, 0, cw * 4 - 1, ch * 4 - 1), radius=round(RADIUS * u) * 4,
            outline=(*WHITE, 40), width=max(2, round(4 * u)),
        )
        image.alpha_composite(rim.resize((cw, ch), Image.LANCZOS), (cx0, cy0))

    ax, ay, size = geo.art
    cover = ImageOps.fit(art, (size, size), Image.LANCZOS)
    if not view.playing and not view.idle:
        cover = ImageEnhance.Brightness(cover).enhance(0.7)
    cover = cover.convert("RGBA")
    cover_mask = _rounded_mask(size, size, round(ART_RADIUS * u))
    cover.putalpha(cover_mask)
    lifted = Image.new("L", image.size, 0)
    lifted.paste(cover_mask, (ax, ay))
    image = Image.alpha_composite(image, _shadow(lifted, 0.55, 5 * u, (0, round(2 * u))))
    image.alpha_composite(cover, (ax, ay))

    limit = geo.text_right - geo.text_left
    title_font = font(TITLE_FONTS, TITLE_SIZE * u)
    artist_font = font(TEXT_FONTS, ARTIST_SIZE * u)
    title = ellipsize(view.title, title_font, limit)
    artist = ellipsize(view.artist, artist_font, limit)
    title_xy = (geo.text_left, geo.y(TITLE_Y))
    artist_xy = (geo.text_left, geo.y(ARTIST_Y))
    if style == "clear":
        halo = Image.new("RGBA", image.size, (0, 0, 0, 0))
        halo_draw = ImageDraw.Draw(halo)
        halo_draw.text(title_xy, title, font=title_font, fill=(0, 0, 0, 170), anchor="la")
        halo_draw.text(artist_xy, artist, font=artist_font, fill=(0, 0, 0, 150), anchor="la")
        image = Image.alpha_composite(halo.filter(ImageFilter.GaussianBlur(max(1, 2.2 * u))),
                                      image)
    draw = ImageDraw.Draw(image)
    draw.text(title_xy, title, font=title_font, fill=(*WHITE, 255), anchor="la")
    draw.text(artist_xy, artist, font=artist_font, fill=(*WHITE, 175), anchor="la")
    return image


def _play_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    draw.polygon(
        [(cx - 0.36 * s, cy - 0.5 * s), (cx - 0.36 * s, cy + 0.5 * s), (cx + 0.5 * s, cy)],
        fill=fill,
    )


def _pause_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    bar, gap = 0.3 * s, 0.22 * s
    for left in (cx - gap / 2 - bar, cx + gap / 2):
        draw.rounded_rectangle((left, cy - 0.5 * s, left + bar, cy + 0.5 * s),
                               radius=bar * 0.3, fill=fill)


def _skip_icon(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill,
               forward: bool) -> None:
    half_h, w = 0.3 * s, 0.5 * s
    for start in (cx - w, cx):
        if forward:
            points = [(start, cy - half_h), (start, cy + half_h), (start + w, cy)]
        else:
            points = [(start + w, cy - half_h), (start + w, cy + half_h), (start, cy)]
        draw.polygon(points, fill=fill)


def _controls(view: View, geo: Layout, style: str, hover: str | None,
              position: float) -> tuple[Image.Image, list[tuple[str, tuple[int, int, int, int]]]]:
    u, k = geo.u, geo.u * SS
    big = Image.new("RGBA", (geo.width * SS, geo.height * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    buttons: list[tuple[str, tuple[int, int, int, int]]] = []
    for name, cx, cy in geo.button_centres():
        r = BUTTON_R * u
        buttons.append((name, (int(cx - r), int(cy - r), int(cx + r), int(cy + r))))
        X, Y = cx * SS, cy * SS
        if hover == name:
            R = r * SS
            draw.ellipse((X - R, Y - R, X + R, Y + R), fill=(*WHITE, 46))
        ink = (*WHITE, 255 if hover == name else 235)
        if name == "play":
            (_pause_icon if view.playing else _play_icon)(draw, X, Y, PLAY_SIZE * k, ink)
        else:
            _skip_icon(draw, X, Y, SKIP_SIZE * k, ink, forward=name == "next")

    left, right = geo.bar()
    cy = geo.y(BAR_Y)
    showing_bar = not view.idle
    if showing_bar:
        thick = (BAR_H_HOVER if hover == "seek" else BAR_H) * k
        Y = cy * SS
        draw.rounded_rectangle((left * SS, Y - thick / 2, right * SS, Y + thick / 2),
                               radius=thick / 2, fill=(*WHITE, 62))
        fraction = position / view.duration if view.duration > 0 else 0.0
        fraction = max(0.0, min(1.0, fraction))
        filled = left * SS + (right - left) * SS * fraction
        if filled - left * SS >= thick:
            draw.rounded_rectangle((left * SS, Y - thick / 2, filled, Y + thick / 2),
                                   radius=thick / 2, fill=(*WHITE, 235))
        if hover == "seek":
            knob = 6.0 * k
            draw.ellipse((filled - knob, Y - knob, filled + knob, Y + knob), fill=(*WHITE, 255))
        buttons.append(("seek", (left, int(cy - 9 * u), right, int(cy + 9 * u))))

    layer = big.resize((geo.width, geo.height), Image.LANCZOS)
    if showing_bar and view.duration > 0:
        numbers = font(NUMBER_FONTS, TIME_SIZE * u)
        text = ImageDraw.Draw(layer)
        text.text((geo.text_left, cy), track.fmt_time(position), font=numbers,
                  fill=(*WHITE, 160), anchor="lm")
        text.text((geo.text_right, cy), "-" + track.fmt_time(view.duration - position),
                  font=numbers, fill=(*WHITE, 160), anchor="rm")
    if hover is not None:
        # The resize grip, while the pointer is on the widget: two short diagonals tucked into
        # the bottom-right curve.
        grip = ImageDraw.Draw(layer)
        right, bottom = geo.card[2] - 9 * u, geo.card[3] - 9 * u
        for length in (5.0, 9.0):
            grip.line((right - length * u, bottom, right, bottom - length * u),
                      fill=(*WHITE, 150), width=max(1, round(1.3 * u)))
    if style == "clear":
        layer = Image.alpha_composite(_shadow(layer.getchannel("A"), 0.6, 2.0 * u), layer)
    return layer, buttons


class Painter:
    """Draws faces, keeping the expensive per-track part between frames."""

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._base: Image.Image | None = None

    def render(self, view: View, width: int, height: int, style: str = "glass",
               hover: str | None = None, position: float | None = None) -> Render:
        style = style if style in STYLES else "glass"
        geo = layout(width, height)
        key = (id(view.art), view.title, view.artist, view.playing, view.idle, style,
               width, height)
        if key != self._key or self._base is None:
            self._base = _base(view, geo, style)
            self._key = key
        position = view.position if position is None else position
        dynamic, buttons = _controls(view, geo, style, hover, position)
        image = Image.alpha_composite(self._base, dynamic)

        # The whole card answers the mouse even where nothing is painted (the
        # clear style), at an alpha of one step: Rainmeter's SolidColor trick.
        block = Image.new("L", image.size, 0)
        block_draw = ImageDraw.Draw(block)
        block_draw.rectangle((geo.card[0], geo.card[1], geo.card[2] - 1, geo.card[3] - 1),
                             fill=HIT_ALPHA)
        image.putalpha(ImageChops.lighter(image.getchannel("A"), block))

        red, green, blue, alpha = image.convert("RGBa").split()
        bgra = Image.merge("RGBa", (blue, green, red, alpha))
        return Render(
            pixels=bgra.tobytes(),
            width=width,
            height=height,
            card=geo.card,
            edge=max(3, round(EDGE * geo.u)),
            corner=max(6, round(CORNER * geo.u)),
            buttons=tuple(buttons),
            bar=geo.bar(),
        )


def view_of(now: track.NowPlaying, apple_running: bool, at: float) -> View:
    if now.idle:
        return View(
            title="Not playing",
            artist="Press play to start Apple Music" if not apple_running else "Apple Music",
            playing=False, position=0.0, duration=0.0, art=None, idle=True,
        )
    return View(
        title=now.title,
        artist=now.artist or now.album,
        playing=now.playing,
        position=now.position_at(at),
        duration=now.duration,
        art=now.art,
        idle=False,
    )


def straight(picture: Render) -> Image.Image:
    """The premultiplied BGRA back to an ordinary RGBA image, for looking at."""
    raw = Image.frombytes("RGBA", (picture.width, picture.height), picture.pixels)
    blue, green, red, alpha = raw.split()
    return Image.merge("RGBa", (red, green, blue, alpha)).convert("RGBA")
