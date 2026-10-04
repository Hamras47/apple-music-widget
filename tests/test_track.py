"""The wording and arithmetic, with no player and no window."""

import unittest

import track


class SplitArtistTests(unittest.TestCase):
    def test_apple_music_puts_the_album_in_the_artist_field(self):
        self.assertEqual(
            track.split_artist("Kavinsky — OutRun", ""), ("Kavinsky", "OutRun")
        )

    def test_only_the_first_separator_splits(self):
        self.assertEqual(
            track.split_artist("A — B — Deluxe", ""), ("A", "B — Deluxe")
        )

    def test_a_real_album_field_wins(self):
        self.assertEqual(track.split_artist("Kavinsky", "OutRun"), ("Kavinsky", "OutRun"))

    def test_a_plain_hyphen_is_part_of_the_name(self):
        self.assertEqual(track.split_artist("Jay-Z", ""), ("Jay-Z", ""))


class TimeTests(unittest.TestCase):
    def test_minutes_and_seconds(self):
        self.assertEqual(track.fmt_time(187), "3:07")
        self.assertEqual(track.fmt_time(0), "0:00")
        self.assertEqual(track.fmt_time(-4), "0:00")

    def test_past_the_hour(self):
        self.assertEqual(track.fmt_time(3729), "1:02:09")


class PositionTests(unittest.TestCase):
    def test_playing_moves_on_from_the_last_report(self):
        now = track.NowPlaying(source="x", title="t", playing=True, position=10,
                               duration=100, updated=1000)
        self.assertAlmostEqual(now.position_at(1005.5), 15.5)

    def test_paused_stays_put(self):
        now = track.NowPlaying(source="x", title="t", playing=False, position=10,
                               duration=100, updated=1000)
        self.assertEqual(now.position_at(2000), 10)

    def test_never_past_the_end(self):
        now = track.NowPlaying(source="x", title="t", playing=True, position=95,
                               duration=100, updated=1000)
        self.assertEqual(now.position_at(1100), 100)


class SourceTests(unittest.TestCase):
    apple = track.APPLE_MUSIC_AUMID

    def test_apple_music_first(self):
        self.assertEqual(track.pick_source(["Spotify.exe", self.apple], "Spotify.exe", True),
                         self.apple)

    def test_other_players_only_when_allowed(self):
        self.assertIsNone(track.pick_source(["Spotify.exe"], "Spotify.exe", False))
        self.assertEqual(track.pick_source(["Spotify.exe"], "Spotify.exe", True), "Spotify.exe")

    def test_idle_without_a_title(self):
        self.assertTrue(track.NowPlaying(source=self.apple).idle)
        self.assertTrue(track.IDLE.idle)


if __name__ == "__main__":
    unittest.main()
