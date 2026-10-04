"""Windows' media session, read on a thread of its own.

Apple Music for Windows publishes what it plays to the System Media Transport Controls -- the
panel behind the volume flyout -- so the widget needs no Apple account and no API: it asks
Windows.  WinRT calls are async, so they live on a private asyncio loop; the UI thread only
ever reads `snapshot` (replaced whole, never mutated) and queues commands.
"""

from __future__ import annotations

import asyncio
import io
import threading
import time
import traceback
from typing import Callable

from PIL import Image

import track

POLL_SECONDS = 0.5
#: Polls after a track change during which the cover is fetched again: Apple Music updates the
#: title a moment before the thumbnail, so the first fetch can be the previous song's cover.
ART_RECHECKS = 4
ART_SIZE = 600


class MediaWatcher:
    def __init__(self, log: Callable[[str], None], on_change: Callable[[], None],
                 any_player: Callable[[], bool]) -> None:
        self.log = log
        self.on_change = on_change
        self.any_player = any_player
        self.snapshot: track.NowPlaying = track.IDLE
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager = None
        self._stop = threading.Event()
        self._art_key: tuple = ()
        self._art_bytes = b""
        self._art: Image.Image | None = None
        self._art_checks = 0

    # ---------------------------------------------------------------- life

    def start(self) -> None:
        threading.Thread(target=self._run, name="media", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        except Exception:
            self.log("media watcher died:\n" + traceback.format_exc())

    async def _main(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )

        self._manager = await SessionManager.request_async()
        self.log("media session manager ready")
        while not self._stop.is_set():
            try:
                await self._poll()
            except Exception:
                self.log("media poll failed:\n" + traceback.format_exc())
            await asyncio.sleep(POLL_SECONDS)

    # ---------------------------------------------------------------- read

    def _session(self):
        sessions = {s.source_app_user_model_id: s for s in self._manager.get_sessions()}
        current = self._manager.get_current_session()
        current_id = current.source_app_user_model_id if current else None
        chosen = track.pick_source(list(sessions), current_id, self.any_player())
        return sessions.get(chosen) if chosen else None

    async def _poll(self) -> None:
        session = self._session()
        if session is None:
            self._publish(track.IDLE)
            return
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        timeline = session.get_timeline_properties()
        artist, album = track.split_artist(props.artist or "", props.album_title or "")
        title = props.title or ""
        key = (session.source_app_user_model_id, title, artist, album)
        if key != self._art_key:
            self._art_key = key
            self._art_checks = ART_RECHECKS
        if self._art_checks > 0:
            self._art_checks -= 1
            await self._fetch_art(props.thumbnail)

        updated = timeline.last_updated_time
        stamp = updated.timestamp() if updated and updated.year > 2000 else time.time()
        start = timeline.start_time.total_seconds()
        self._publish(
            track.NowPlaying(
                source=session.source_app_user_model_id,
                title=title,
                artist=artist,
                album=album,
                playing=int(info.playback_status) == 4,
                position=timeline.position.total_seconds() - start,
                duration=max(0.0, timeline.end_time.total_seconds() - start),
                updated=stamp,
                art=self._art,
            )
        )

    async def _fetch_art(self, thumbnail) -> None:
        if thumbnail is None:
            if self._art_checks == 0 and self._art_bytes:
                self._art_bytes, self._art = b"", None
            return
        from winrt.windows.storage.streams import Buffer, InputStreamOptions

        stream = await thumbnail.open_read_async()
        buffer = Buffer(stream.size)
        await stream.read_async(buffer, buffer.capacity, InputStreamOptions.READ_AHEAD)
        data = bytes(buffer)
        if not data or data == self._art_bytes:
            return
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((ART_SIZE, ART_SIZE), Image.LANCZOS)
        self._art_bytes, self._art = data, image

    def _publish(self, now: track.NowPlaying) -> None:
        old = self.snapshot
        self.snapshot = now
        if now != old or now.art is not old.art:
            if (now.title, now.artist, now.playing) != (old.title, old.artist, old.playing):
                self.log(f"now: {'>' if now.playing else '||'} {now.title} - {now.artist}")
            self.on_change()

    # ------------------------------------------------------------- control

    def command(self, name: str, value: float = 0.0) -> None:
        """play | pause | toggle | next | prev | seek(value seconds) -- fire and forget."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._command(name, value), self._loop)

    async def _command(self, name: str, value: float) -> None:
        try:
            session = self._session()
            if session is None:
                return
            if name == "toggle":
                await session.try_toggle_play_pause_async()
            elif name == "play":
                await session.try_play_async()
            elif name == "pause":
                await session.try_pause_async()
            elif name == "next":
                await session.try_skip_next_async()
            elif name == "prev":
                await session.try_skip_previous_async()
            elif name == "seek":
                start = session.get_timeline_properties().start_time.total_seconds()
                await session.try_change_playback_position_async(
                    int((start + value) * 10_000_000)
                )
            await self._poll()
        except Exception:
            self.log(f"command {name} failed:\n" + traceback.format_exc())

    def has_apple_session(self) -> bool:
        if self._manager is None:
            return False
        try:
            return any(
                track.is_apple(s.source_app_user_model_id) for s in self._manager.get_sessions()
            )
        except Exception:
            return False
