"""What is playing, as plain data: no window, no WinRT, nothing to mock.

The media watcher fills these in from Windows' media session; the face reads them.  Keeping
the wording and the arithmetic here is what lets the tests run without a player.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Apple Music for Windows, as the media session names it.  The publisher hash is Apple's and
#: does not change between versions.
APPLE_MUSIC_AUMID = "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"
APPLE_MUSIC_PREFIX = "AppleInc.AppleMusicWin"

#: Apple Music leaves the album field empty and reports "Artist — Album" as the artist.
ARTIST_ALBUM_SEPARATORS = (" — ", " – ")


@dataclass(frozen=True)
class NowPlaying:
    """One sample of the player's state."""

    source: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    playing: bool = False
    #: Seconds into the track at `updated` (epoch seconds), and the track length.
    position: float = 0.0
    duration: float = 0.0
    updated: float = 0.0
    #: Cover art as a PIL image, or None; compared by identity, so it is only replaced when the
    #: picture really changed.
    art: object = field(default=None, compare=False)

    @property
    def idle(self) -> bool:
        return not self.source or not self.title

    @property
    def is_apple(self) -> bool:
        return is_apple(self.source)

    def position_at(self, now: float) -> float:
        """Where playback is now: the last report, plus the time since it if playing."""
        position = self.position
        if self.playing and self.updated:
            position += max(0.0, now - self.updated)
        if self.duration > 0:
            position = min(position, self.duration)
        return max(0.0, position)


IDLE = NowPlaying()


def is_apple(source: str) -> bool:
    return source.startswith(APPLE_MUSIC_PREFIX)


def split_artist(artist: str, album: str) -> tuple[str, str]:
    """(artist, album), undoing Apple Music's "Artist — Album" in the artist field."""
    artist = (artist or "").strip()
    album = (album or "").strip()
    if album:
        return artist, album
    for separator in ARTIST_ALBUM_SEPARATORS:
        if separator in artist:
            name, _, rest = artist.partition(separator)
            return name.strip(), rest.strip()
    return artist, ""


def fmt_time(seconds: float) -> str:
    """3:07, or 1:02:09 past the hour."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def pick_source(sources: list[str], current: str | None, any_player: bool) -> str | None:
    """Which session to follow: Apple Music first; anything else only if allowed."""
    for source in sources:
        if is_apple(source):
            return source
    if any_player:
        if current in sources:
            return current
        return sources[0] if sources else None
    return None
