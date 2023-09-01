from random import random
from typing import Union

from yandex_music import Client, Track
from yandex_music.rotor.station_tracks_result import StationTracksResult

# based on https://github.com/MarshalX/yandex-music-api/blob/main/examples/radio_example/radio.py
class Radio:
    __slots__ = ('client', 'play_id' ,'station_id' ,'station_from' ,'index' ,'current_track' ,'station_tracks')

    client: Client
    play_id: str
    station_id: str
    station_from: str
    index: int
    current_track: Track
    station_tracks: StationTracksResult

    def __init__(self, client: Client) -> None:
        self.client = client

    def start_radio(self, station_id: str, station_from: str) -> Track:
        self.station_id = station_id
        self.station_from = station_from

        # get first 5 tracks
        self.__update_radio_batch(None)

        # setup current track
        self.current_track = self.__update_current_track()
        return self.current_track

    def play_next(self) -> Track:
        # send prev track finalize info
        self.__send_play_end_track(self.current_track, self.play_id)
        self.__send_play_end_radio(self.current_track, self.station_tracks.batch_id)

        # get next index
        self.index += 1
        if self.index >= len(self.station_tracks.sequence):
            # get next 5 tracks. Set index to 0
            self.__update_radio_batch(self.current_track.track_id)

        # setup next track
        self.current_track = self.__update_current_track()
        return self.current_track

    def __update_radio_batch(self, queue: Union[str, int, None] = None) -> None:
        self.index = 0
        tracks = self.client.rotor_station_tracks(self.station_id, queue=queue)
        assert tracks
        self.station_tracks = tracks
        self.__send_start_radio(self.station_tracks.batch_id)

    def __update_current_track(self) -> Track:
        self.play_id = self.__generate_play_id()
        track = self.client.tracks([self.station_tracks.sequence[self.index].track.track_id])[0]
        self.__send_play_start_track(track, self.play_id)
        self.__send_play_start_radio(track, self.station_tracks.batch_id)
        return track

    def __send_start_radio(self, batch_id: str):
        self.client.rotor_station_feedback_radio_started(
            station=self.station_id, from_=self.station_from, batch_id=batch_id
        )

    def __send_play_start_track(self, track: Track, play_id: str) -> None:
        assert track.duration_ms
        total_seconds = track.duration_ms // 1000
        self.client.play_audio(
            from_="desktop_win-home-playlist_of_the_day-playlist-default",
            track_id=track.id,
            album_id=track.albums[0].id,
            play_id=play_id,
            track_length_seconds=0,
            total_played_seconds=0,
            end_position_seconds=total_seconds,
        )

    def __send_play_start_radio(self, track: Track, batch_id: str) -> None:
        self.client.rotor_station_feedback_track_started(station=self.station_id, track_id=track.id, batch_id=batch_id)

    def __send_play_end_track(self, track: Track, play_id: str) -> None:
        # played_seconds = 5.0
        assert track.duration_ms
        total_seconds = track.duration_ms // 1000
        played_seconds = total_seconds
        self.client.play_audio(
            from_="desktop_win-home-playlist_of_the_day-playlist-default",
            track_id=track.id,
            album_id=track.albums[0].id,
            play_id=play_id,
            track_length_seconds=total_seconds,
            total_played_seconds=played_seconds,
            end_position_seconds=played_seconds,
        )

    def __send_play_end_radio(self, track: Track, batch_id: str) -> None:
        assert track.duration_ms
        played_seconds = track.duration_ms // 1000
        self.client.rotor_station_feedback_track_finished(
            station=self.station_id, track_id=track.id, total_played_seconds=played_seconds, batch_id=batch_id
        )

    @staticmethod
    def __generate_play_id() -> str:
        return "%s-%s-%s" % (int(random() * 1000), int(random() * 1000), int(random() * 1000))
