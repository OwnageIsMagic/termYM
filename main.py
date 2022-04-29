#!/usr/bin/env python3
import sys
import subprocess
import argparse
import re
import traceback
import unicodedata
from time import sleep
from textwrap import indent
from pathlib import Path
# from threading import

from types import SimpleNamespace
from typing import TYPE_CHECKING, Final, Optional, Tuple, TypeVar, Callable, Union, List, cast
# sys.path.append('~/source/pyt/yandex-music-api/')
# import yandex_music
from yandex_music.album.album import Album
from yandex_music.feed.generated_playlist import GeneratedPlaylist
from yandex_music.playlist.user import User
from yandex_music import Client, TrackShort, SearchResult, Artist, Track, Playlist
from yandex_music.video import Video
# from radio import Radio

T = TypeVar('T')
if TYPE_CHECKING:
    from typing_extensions import TypeVarTuple
    Ts = TypeVarTuple('Ts')

MAX_ERRORS: Final = 3

def handle_args():
    DEFAULT_CACHE_FOLDER = Path(__file__).resolve().parent / '.YMcache'

    parser = argparse.ArgumentParser()
    parser.add_argument('playlist', choices={'likes', 'l', 'playlist', 'p', 'search', 's', 'auto', 'a',
                                             'radio', 'r', 'queue', 'q', 'id'},
                        help='playlist type')
    parser.add_argument('playlist_name', nargs='?',
                        help='name of playlist or search term')

    auto__ = parser.add_argument_group('auto')
    auto__.add_argument('--auto-type', '-tt', choices={'personal-playlists', 'new-playlists', 'new-releases'},
                        default='personal-playlists',
                        help='type of auto playlist.')
    auto__.add_argument('--alice', action='store_true',
                        help='show Alice shots.')

    search = parser.add_argument_group('search')
    search.add_argument('--search-type', '-t', choices={'all', 'artist', 'a', 'user', 'u', 'album', 'b',
                        'playlist', 'p', 'track', 't', 'podcast', 'p', 'podcast_episode', 'pe', 'video', 'v'},
                        default='all',
                        help='type of search. При поиске type=all не возвращаются подкасты и эпизоды.'
                        + ' Указывайте конкретный тип для поиска.')
    search.add_argument('--search-x', '-x', type=int, default=1, metavar='X',
                        help='use specific search result')
    search.add_argument('--search-no-correct', action='store_true',
                        help='no autocorrection for search')

    parser.add_argument('--list', '-l', action='store_true',
                        help='only show tracks')
    parser.add_argument('--skip', '-s', metavar='N', type=int, default=0,
                        help='skip first %(metavar)s tracks')
    parser.add_argument('--show-skiped', '-ss', action='store_true',
                        help='show skiped tracks')
    parser.add_argument('--shuffle', action='store_true',
                        help='randomize tracks order')
    parser.add_argument('--reverse', '-r', action='store_true',
                        help='reverse tracks order')
    parser.add_argument('--show-id', action='store_true',
                        help='show track_id')
    parser.add_argument('--export-list', action='store_true',
                        help='print comma separated track_id list of playlist')
    parser.add_argument('--log-api', action='store_true',
                        help='log YM API requests')
    parser.add_argument('--token', default=DEFAULT_CACHE_FOLDER / 'config',
                        help='YM API token as string or path to file')
    parser.add_argument('--no-save-token', action='store_true',
                        help='don\'t save token in cache folder')
    parser.add_argument('--cache-folder', type=Path, default=DEFAULT_CACHE_FOLDER,
                        help='congig and cached tracks folder')
    parser.add_argument('--audio-player', default='vlc',
                        help='player to use')
    parser.add_argument('--audio-player-arg', action='append', default=[],
                        help='args for --audio-player (can be specified multiple times)')
    parser.add_argument('--print-args', action='store_true',
                        help='print arguments (including default values) and exit')
    args = parser.parse_args()

    if args.audio_player is parser.get_default('audio_player')\
            and args.audio_player_arg is parser.get_default('audio_player_arg'):
        args.audio_player_arg = ['-I', 'dummy', '--play-and-exit', '--quiet']

    args.player_cmd = args.audio_player_arg
    args.player_cmd.insert(0, args.audio_player)
    args.player_cmd.append('')  # will be replaced with filename

    if args.list:
        args.skip = sys.maxsize
        args.show_skiped = True

    if args.playlist == 'l':
        args.playlist = 'likes'
    elif args.playlist == 'p':
        args.playlist = 'playlist'
    elif args.playlist == 's':
        args.playlist = 'search'
    elif args.playlist == 'a':
        args.playlist = 'auto'
    elif args.playlist == 'r':
        args.playlist = 'radio'
    elif args.playlist == 'q':
        args.playlist = 'queue'

    if args.search_type == 'a':
        args.search_type = 'artist'
    elif args.search_type == 'u':
        args.search_type = 'user'
    elif args.search_type == 'b':
        args.search_type = 'album'
    elif args.search_type == 'p':
        args.search_type = 'playlist'
    elif args.search_type == 't':
        args.search_type = 'track'
    elif args.search_type == 'p':
        args.search_type = 'podcast'
    elif args.search_type == 'pe':
        args.search_type = 'podcast_episode'
    elif args.search_type == 'v':
        args.search_type = 'video'

    if args.alice:
        if not args.playlist_name:
            args.playlist_name = 'origin'
        if args.playlist_name != 'origin':
            print('--alice can only be specified for "origin" auto-generated playlist')
            sys.exit(2)

    if args.print_args:
        print(args)
        sys.exit()

    if type(args.token) is str and re.match(r'^[A-z0-9]{39}$', args.token):
        if not args.no_save_token:
            args.cache_folder.write_text(args.token)
    else:
        try:
            args.token = Path(args.token).read_text()
        except FileNotFoundError:
            print('Config file not found. Use --token to create it')
            sys.exit(2)

    return args


def flatten(inp : List[List[T]]) -> List[T]:
     res: List[T] = []
     for l in inp:
         res.extend(l)
     return res


def getTracksFromQueue() -> Tuple[int, List[TrackShort]]:
    print('Not implemented')
    # queue queues_list
    sys.exit(3)
    return 0, []


def getSearchTracks(client: Client, playlist_name: str, search_type: str, search_x: int,
                    search_no_correct: bool) -> Tuple[int, Union[List[Track], List[TrackShort]]]:
    if not playlist_name:
        print('Specify search term (playlist-name)')
        sys.exit(1)
    search = client.search(playlist_name, playlist_in_best=False,
                  nocorrect=search_no_correct, type_=search_type)
    assert search
    print('Search results for',
          f'"{search.text}"' if not search.misspell_corrected \
            else f'"{search.misspell_original}"=>"{search.misspell_result}"')

    for cat in [search.tracks, search.artists, search.albums, search.playlists, search.videos,
                search.users, search.podcasts, search.podcast_episodes]:
        if cat is None:
            continue
        print(f'{cat.type}s: {cat.total} match(es)')
        cat_type = cat.type.replace('_', '-')
        for (i, r) in enumerate(cat.results):
            print(f'{i + 1}.', end='')
            if hasattr(r, 'type') and r.type and r.type != 'music' and r.type != cat_type: # type: ignore
                print(f' ({r.type})', end='')                                              # type: ignore
            if hasattr(r, 'artists_name') and r.artists:                                   # type: ignore
                print(f' {"|".join(r.artists_name())}', end='')                            # type: ignore
            if hasattr(r, 'albums') and r.albums:                                          # type: ignore
                print(f' [{"|".join([(a.title or str(a.id)) if not a.version else f"{a.title}@{a.version}" for a in r.albums])}]', # type: ignore
                      end='')
            if hasattr(r, 'owner') and r.owner:                                            # type: ignore
                print(f' {{{r.owner.login}}}', end='')                                     # type: ignore
            if cat_type != 'podcast':
                print(' ~ ', end='')
            else:
                print(' ', end='')
            print(f'{(r.title if hasattr(r, "title") else r.name)}', end='')               # type: ignore
            if hasattr(r, 'version') and r.version and not r.version.isspace():            # type: ignore
                print(f'@{r.version}', end='')                                             # type: ignore
            if hasattr(r, 'duration_ms') and r.duration_ms:                                # type: ignore
                print(f' {r.duration_ms // 1000 // 60}:{r.duration_ms % 60:02}', end='')   # type: ignore
            print() # new line
            if i >= 4: # 5 per category
                break

    if search.best: #search_type == 'all':
        res = search.best.result
        restype = search.best.type
        print(f'Best match: [{restype}]')
    else:
        searchres: SearchResult = search[search_type + 's']
        if searchres is None or len(searchres.results) == 0:
            print(f'Nothing found for "{search.text}", type={search.type_}')
            sys.exit(1)

        restype = searchres.type
        res = searchres.results[search_x - 1]
        print(f'Selecting {search_x} [{restype}]')

    if restype == 'artist':
        # artists artists_tracks artists_direct_albums
        artisttracks = cast(Artist, res).get_tracks()
        assert artisttracks
        tracks = artisttracks.tracks
        total_tracks = len(tracks)

    elif restype == 'album' or restype == 'podcast':
        # albums albums_with_tracks
        res = cast(Album, res)
        if res.volumes:
            volumes = res.volumes
        else:
            res = res.with_tracks()
            assert res and res.volumes
            volumes = res.volumes

        tracks = flatten(volumes)
        total_tracks = res.track_count if res.track_count else len(tracks)

        show_playing_album(res, total_tracks)
        show_album(tracks)

    elif restype == 'track' or restype == 'podcast_episode':
        tracks = [cast(Track, res)]
        total_tracks = 1

    elif restype == 'playlist':
        res = cast(Playlist, res)
        tracks = res.tracks if res.tracks else res.fetch_tracks()
        total_tracks = res.track_count if res.track_count else len(tracks)
        show_playing_playlist(res, total_tracks)

    elif restype == 'user': # TODO
        res = cast(User, res)
        print('Not implemented', res)
        sys.exit(3)

    elif restype == 'video':  # TODO
        res = cast(Video, res)
        print('Not implemented', res)
        sys.exit(3)

    else: # unreachable
        print('Not implemented', res)
        sys.exit(3)

    # tracks tracks_download_info

    return total_tracks, tracks

def show_playing_album(res, total_tracks):
    print(f'Playing {res.title} ({res.id}) by {"|".join(res.artists_name())}. {total_tracks} track(s).')


def show_album(tracks):
    for (i, track) in enumerate(tracks):
        print(f'{i + 1:>2}.',
              f'{track.title}@{track.version}' if track.version else track.title,
              f'{track.duration_ms // 1000 // 60}:{track.duration_ms % 60:02}' if track.duration_ms else '-:--')


def getAutoTracks(client: Client, playlist_name: str, playlist_type: str, show_alice: bool) -> Tuple[int, List[TrackShort]]:
    if not playlist_name:
        print('playlist_name is not set. Assuming "playlistOfTheDay"')
        playlist_name = 'playlistOfTheDay'

    # new-releases: List[Album]
    # new-playlists: List[Playlist]
    # personal-playlists: List[GeneratedPlaylist]
    # 'personal-playlists, new-releases, new-playlists'
    landings = client.landing(playlist_type)  # same as 'personalplaylists'
    # landings = client.landing('personal-playlists') # same as 'personalplaylists'
    assert landings
    playlist: Optional[Playlist] = None
    playlist_name_icase = playlist_name.casefold()
    print(f'Blocks: ({playlist_type})')
    for block in landings.blocks:
        print(f'"{block.title}" {block.description} {block.data}')

        # sanity check
        assert block.type == playlist_type and block.type == block.type_for_from, landings

        for e in block.entities:
            pl: Playlist
            genPl = None
            i = 1
            tab = '    '
            if e.type == 'personal-playlist':
                genPl = cast(GeneratedPlaylist, e.data)
                assert genPl.data, genPl
                pl = genPl.data

                print(f'{tab * i}{genPl.type}{" *" if genPl.notify else ""}')
                i += 1
                # sanity check
                assert genPl.type == pl.generated_playlist_type or pl.generated_playlist_type is None
                assert genPl.ready # just check
                assert not genPl.description
            elif e.type == 'playlist':
                pl = cast(Playlist, e.data)
            else:
                print('Not implemented')
                sys.exit(3)

            assert not pl.type and not pl.playlist_uuid # just check
            assert not pl.dummy_description and not pl.dummy_page_description
            assert not pl.og_data

            g = pl.generated_playlist_type
            if g and pl.id_for_from:
                g = f'{g} {pl.id_for_from}'
            elif pl.id_for_from:
                g = pl.id_for_from

            print(f'{tab * i}"{pl.title}"{f" {g}" if g else ""} ({pl.uid}:{pl.kind})'
                  + f'\n{indent(pl.description.strip(), tab * (i + 1))}' if pl.description else '')
            assert pl.owner.uid == pl.uid # type: ignore

            if (genPl and genPl.type == playlist_name) or pl.id_for_from == playlist_name \
                or (pl.title and playlist_name_icase in pl.title.casefold()):
                playlist = pl

    if playlist is None:
        print(f'auto playlist "{playlist_name}" not found')
        sys.exit(1)

    if playlist.generated_playlist_type == 'playlistOfTheDay':
        assert playlist.play_counter
        print(f'Playlist of the day streak: {playlist.play_counter.value}.',
              f'Updated: {playlist.play_counter.updated}')

    tracks = playlist.tracks if playlist.tracks else playlist.fetch_tracks()
    total_tracks = playlist.track_count if playlist.track_count else len(tracks)
    show_playing_playlist(playlist, total_tracks)

    return total_tracks, tracks

def show_playing_playlist(playlist: Playlist, total_tracks: int):
    assert playlist.owner
    print(f'Playing {playlist.title}',
          f'({playlist.playlist_id} {playlist.modified.split("T")[0] if playlist.modified else "???"})',
          f'by {playlist.owner.login}.',
          f'{total_tracks} track(s).')


def getPlaylistTracks(client: Client, playlist_name: str) -> Tuple[int, List[TrackShort]]:
    user_playlists = client.users_playlists_list()

    playlist = next((p for p in user_playlists if p.title == playlist_name), None) if playlist_name else None
    if playlist is None:
        if not playlist_name:
            print('Specify playlist_name.', end='')
        else:
            print(f'Playlist "{playlist_name}" not found.', end='')
        print(' Available:', list(p.title for p in user_playlists))
        sys.exit(1)

    tracks = playlist.tracks if playlist.tracks else playlist.fetch_tracks()
    total_tracks = playlist.track_count if playlist.track_count else len(tracks)
    show_playing_playlist(playlist, total_tracks)

    return total_tracks, tracks


def show_alice_shot(client: Client, track: Union[TrackShort, Track]):
    ev = client.after_track(track.track_id, '940441070:17870614')
    if not ev:
        return
    for shot in ev.shots:
        d = shot.shot_data
        assert shot.order == 0 and shot.status == 'ready', ev  # just check
        assert d.shot_type.id == 'alice' and d.shot_type.title == 'Шот от Алисы', ev
        # d.mds_url
        print(ev.event_id, d.shot_text)


def slugify(value: str):
    value = unicodedata.normalize('NFKC', value) # normalized combined form
    value = value.strip()
    value = re.sub(r'\s+', ' ', value) # collapse inner whitespace
    value = re.sub(r'^(\s*(?:CON|CONIN\$|CONOUT\$|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\s*(?:\..*)?)$',
        r'_\1', value, flags=re.IGNORECASE) # common special names
    return re.sub(r'[\x00-\x1F\x7F"*/:<>?|\\]', '_', value) # reserved chars


def retry(func: 'Callable[[*Ts], T]', *args: '*Ts', **kwargs) -> T:
    error_count = 0
    while error_count < MAX_ERRORS:
        try:
            return func(*args, **kwargs)
        except Exception:
            # print('Error:', type(e).__name__, ' ', e)
            traceback.print_exc()
            error_count += 1
            sleep(1)
    else:
        sys.exit(10)


def get_album_year(album: Album):
    y1 = int(album.release_date[:4]) if album.release_date else 9999
    y2 = int(album.original_release_year) if album.original_release_year else 9999
    y3 = album.year or 9999
    return min(y1, y2, y3)


def get_cache_path_for_track(track: Track, cache_folder: Path):
    assert track.albums
    artist = track.artists[0] if track.artists \
        else SimpleNamespace(name='#_' + track.type if track.type else 'unknown', id=0)
    album = track.albums[0]
    album_version = f' ({album.version})' if album.version and not album.version.isspace() else ''
    album_year = get_album_year(album)
    track_version = f' ({track.version})' if track.version and not track.version.isspace() else ''
    track_pos = album.track_position
    track_pos = f'{track_pos.volume}-{track_pos.index}' if track_pos else ''

    artist_dir = slugify(f'{artist.name}_{artist.id}')
    album_dir = slugify(f'{album_year}_{album.title}{album_version}_{album.id}')
    filename = slugify(f'{track_pos}_{track.title}{track_version}_{track.id}.mp3')
    return cache_folder / artist_dir / album_dir / filename


def download_track(track: Track, cache_folder: Path) -> Path:
    file_path = get_cache_path_for_track(track, cache_folder)
    assert track.file_size is None or track.file_size == 0 # just check
    if not file_path.exists():
        print('Downloading...', end='')
        file_path.parent.mkdir(parents=True, exist_ok=True)
        retry(lambda x: track.download(x), file_path)
        print('ok')
    return file_path


def play_track(i: int, total_tracks: int, track_or_short: Union[Track, TrackShort],
               cache_folder: Path, player_cmd: List[str], show_id: bool):
    try:
        track = track_from_short(track_or_short)
        show_playing_track(i, total_tracks, track, show_id)

        file_path = download_track(track, cache_folder)

        player_cmd[-1] = str(file_path)
        subprocess.run(player_cmd, stderr=subprocess.DEVNULL)
    except KeyboardInterrupt:
        try:
            sleep(0.7)
        except KeyboardInterrupt:
            print('Goodbye.')
            sys.exit()


def track_from_short(track_or_short: Union[Track, TrackShort]):
    if isinstance(track_or_short, Track):
        track = track_or_short
    else:
        track = track_or_short.track if track_or_short.track else track_or_short.fetch_track()

    if track.real_id and track.id != track.real_id:
        print(f'track.id ({track.id}) != track.real_id ({track.real_id})')

    return track


def show_playing_track(i: int, total_tracks: int, track: Track, show_id: bool):
    assert track.albums
    track_type = f'({track.type}) ' if track.type and track.type != 'music' and track.type != 'podcast-episode' else ''
    track_id = f'{"<" + track.track_id + ">":<20} ' if show_id else ''
    print(f'{i + 1}/{total_tracks}:',
          track_id + track_type + # no space if omitted
          '|'.join(track.artists_name()),
          f"[{'|'.join((a.title or str(a.id)) if not a.version else f'{a.title}@{a.version}' for a in track.albums)}]",
          '~', track.title if not track.version else f'{track.title}@{track.version}',
          f'{track.duration_ms // 1000 // 60}:{track.duration_ms % 60:02}' if track.duration_ms else '-:--')


def main():
    args = handle_args()

    if args.log_api:
        import logging
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    Client.notice_displayed = True
    client = Client.from_token(args.token, report_new_fields=True)

    assert client.me and client.me.account
    acc = client.me.account
    print('Hello,', acc.first_name)
    if acc.now and acc.birthday and acc.now[5:10] == acc.birthday[5:10]:
        print('Happy birthday!')

    permission_alerts = client.permission_alerts()
    if permission_alerts and permission_alerts.alerts:
        print('PERMISSION_ALERTS:')
        for a in permission_alerts.alerts:
            print(a)

    if args.playlist == 'playlist':
        total_tracks, tracks = getPlaylistTracks(client, args.playlist_name)

    elif args.playlist == 'likes':
        tracks_list = client.users_likes_tracks()
        assert tracks_list
        tracks = tracks_list.tracks
        total_tracks = len(tracks)
        print(f'Playing liked tracks. {total_tracks} track(s).')

    elif args.playlist == 'search':
        total_tracks, tracks = getSearchTracks(
            client, args.playlist_name, args.search_type, args.search_x, args.search_no_correct)

    elif args.playlist == 'auto':
        total_tracks, tracks = getAutoTracks(client, args.playlist_name, args.auto_type, args.alice)

    elif args.playlist == 'radio':
        print('Not implemented')
        # TODO: use examples\Radio
        # rotor_stations_dashboard rotor_stations_list rotor_station_tracks
        sys.exit(3)

    elif args.playlist == 'queue':
        # queue queues_list
        total_tracks, tracks = getTracksFromQueue()

    elif args.playlist == 'id':
        if not args.playlist_name:
            print('Specify comma (",") separated track id list')
            sys.exit(1)
        tracks = client.tracks(args.playlist_name.split(','))
        total_tracks = len(tracks)

    else: # unreachable
        sys.exit(3)

    if args.shuffle:
        from random import shuffle
        shuffle(tracks)

    if args.reverse:
        tracks.reverse()

    if args.export_list:
        print(','.join(t.track_id for t in tracks))
        return

    for (i, track_or_short) in enumerate(tracks):
        if args.skip > i:
            if args.show_skiped:
                track = track_from_short(track_or_short)
                show_playing_track(i, total_tracks, track, args.show_id)
            continue

        if args.alice:
            show_alice_shot(client, track_or_short)

        retry(play_track, i, total_tracks, track_or_short,
              args.cache_folder, args.player_cmd, args.show_id)


if __name__ == '__main__':
    main()
