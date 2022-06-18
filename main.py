#!/usr/bin/env python3
import asyncio
import os
import sys
import argparse
import re
import traceback
import unicodedata
from time import sleep
from textwrap import indent
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Final, Optional, Tuple, TypeVar, Callable, Union, List, cast

# sys.path.append('~/source/pyt/yandex-music-api/')
# import yandex_music
from yandex_music.album.album import Album
from yandex_music.feed.generated_playlist import GeneratedPlaylist
from yandex_music.playlist.user import User
from yandex_music import Client, TrackShort, SearchResult, Artist, Track, Playlist
from yandex_music.video import Video
from yandex_music.exceptions import Unauthorized as YMApiUnauthorized, YandexMusicError
# from radio import Radio
from json.decoder import JSONDecodeError

T = TypeVar('T')
if TYPE_CHECKING:
    from typing_extensions import ParamSpec
    P = ParamSpec('P')

MAX_ERRORS: Final = 3


def handle_args() -> argparse.Namespace:
    DEFAULT_CACHE_FOLDER = Path(__file__).resolve().parent / '.YMcache'
    CONFIG_FILE_NAME = 'config'

    class BooleanAction(argparse.Action):
        def __init__(self, option_strings, dest, nargs=None, **kwargs):
            super(BooleanAction, self).__init__(option_strings, dest, nargs=0, **kwargs)

        def __call__(self, parser, namespace, values, option_string=None):
            setattr(namespace, self.dest, False if option_string.startswith('--no-') else True)  # type: ignore

    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices={'likes', 'l', 'playlist', 'p', 'search', 's', 'auto', 'a',
                                         'radio', 'r', 'queue', 'q', 'id'},
                        help='operation mode')
    parser.add_argument('playlist_name', nargs='?',
                        help='name of playlist or search term')

    auto__ = parser.add_argument_group('auto')
    auto__.add_argument('--auto-type', '-tt', choices={'personal-playlists', 'new-playlists', 'new-releases'},
                        default='personal-playlists',
                        help='type of auto playlist. Default: %(default)r')
    auto__.add_argument('--no-alice', dest='alice', action='store_false',
                        help='don\'t show Alice shots')

    search = parser.add_argument_group('search')
    search.add_argument('--search-type', '-t', choices={'all', 'artist', 'a', 'user', 'u', 'album', 'b',
                        'playlist', 'p', 'track', 't', 'podcast', 'c', 'podcast_episode', 'ce', 'video', 'v'},
                        default='all',
                        help='type of search. Default: %(default)r'
                        ' При поиске type=all не возвращаются подкасты и эпизоды.'
                        ' Указывайте конкретный тип для поиска')
    search.add_argument('--search-x', '-x', type=int, default=1, metavar='X',
                        help='use specific search result')
    search.add_argument('--count', '-c', type=int, default=5, metavar='N',
                        help='show %(metavar)s search results')
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
                        help='print comma separated track_id list of playlist and exit')
    parser.add_argument('--log-api', action='store_true',
                        help='log YM API requests')
    parser.add_argument('--token', default=DEFAULT_CACHE_FOLDER / CONFIG_FILE_NAME,
                        help='YM API token as string or path to file')
    parser.add_argument('--no-save-token', action='store_true',
                        help='don\'t save token in cache folder')
    parser.add_argument('--cache-folder', type=Path, default=DEFAULT_CACHE_FOLDER,
                        help='config and cached tracks folder')
    parser.add_argument('--audio-player',
                        default='D:\\Program Files\\VideoLAN\\VLC\\vlc.exe' if os.name == 'nt' else 'vlc',
                        help='player to use')
    parser.add_argument('--audio-player-arg', action='append', default=[],
                        help='args for --audio-player (can be specified multiple times)')
    parser.add_argument('--ignore-retcode', '--no-ignore-retcode', dest='ignore_retcode', action=BooleanAction,
                        default=os.name == 'nt',
                        help='ignore audio player return code. Default on Windows')
    parser.add_argument('--skip-long-path', '--no-skip-long-path', dest='skip_long_path', action=BooleanAction,
                        default=os.name == 'nt',
                        help='skip track if file path is over MAX_PATH. Default on Windows')
    parser.add_argument('--report-new-fields', action='store_true',
                        help='report new fields from API')
    parser.add_argument('--print-args', action='store_true',
                        help='print arguments (including default values) and exit')
    args = parser.parse_args()

    if args.audio_player is parser.get_default('audio_player') \
            and args.audio_player_arg is parser.get_default('audio_player_arg'):
        args.audio_player_arg = ['-I', 'dummy', '--play-and-exit', '--quiet']

    args.player_cmd = args.audio_player_arg
    args.player_cmd.insert(0, args.audio_player)
    args.player_cmd.append('')  # will be replaced with filename

    if args.list:
        args.skip = sys.maxsize
        args.show_skiped = True

    if args.mode == 'l':
        args.mode = 'likes'
    elif args.mode == 'p':
        args.mode = 'playlist'
    elif args.mode == 's':
        args.mode = 'search'
    elif args.mode == 'a':
        args.mode = 'auto'
    elif args.mode == 'r':
        args.mode = 'radio'
    elif args.mode == 'q':
        args.mode = 'queue'

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
    elif args.search_type == 'c':
        args.search_type = 'podcast'
    elif args.search_type == 'ce':
        args.search_type = 'podcast_episode'
    elif args.search_type == 'v':
        args.search_type = 'video'

    if args.mode != 'auto' or args.playlist_name != 'origin':
        args.alice = False

    if args.mode == 'auto' and not args.playlist_name:
        print('playlist_name is not set. Assuming "playlistOfTheDay".')
        args.playlist_name = 'playlistOfTheDay'

    if args.print_args:
        print(args)
        sys.exit()

    if type(args.token) is str and len(args.token) == 39 and re.match(r'^[A-Za-z0-9_]{39}$', args.token):
        if not args.no_save_token:
            (args.cache_folder / CONFIG_FILE_NAME).write_text(args.token)
    else:
        try:
            args.token = Path(args.token).read_text()
        except FileNotFoundError:
            print('Config file not found. Use --token to create it.')
            sys.exit(2)

    return args


def flatten(inp: List[List[T]]) -> List[T]:
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
                    search_no_correct: bool, count:int, show_id: bool
                   ) -> Tuple[int, Union[List[Track], List[TrackShort]]]:
    if not playlist_name:
        print('Specify search term (playlist-name)')
        sys.exit(1)
    search = client.search(playlist_name, playlist_in_best=False,
                           nocorrect=search_no_correct, type_=search_type)
    assert search
    print('Search results for',
          f'"{search.text}"' if not search.misspell_corrected
          else f'"{search.misspell_original}"=>"{search.misspell_result}"')

    for cat in [search.tracks, search.artists, search.albums, search.playlists, search.videos,
                search.users, search.podcasts, search.podcast_episodes]:
        if cat is None:
            continue
        print(f'{cat.type}s: {cat.total} match(es)')
        cat_type = cat.type.replace('_', '-')
        for (i, r) in enumerate(cat.results):
            id = r.track_id if hasattr(r, 'track_id') else r.playlist_id if hasattr(       # type: ignore
                r, 'playlist_id') else r.id                                                # type: ignore
            sid = f' {id:<18}' if show_id else ''

            print(f'{i + 1}.{sid}', end='')                                                # TODO: maybe Protocol?
            if hasattr(r, 'type') and r.type and r.type != 'music' and r.type != cat_type: # type: ignore
                print(f' ({r.type})', end='')                                              # type: ignore
            if hasattr(r, 'artists_name') and r.artists:                                   # type: ignore
                print(' ' + '|'.join(r.artists_name()), end='')                            # type: ignore
            if hasattr(r, 'albums') and r.albums:                                          # type: ignore
                print(' [' + '|'.join([
                      f'{a.title} @ {a.version}' if a.version
                      else a.title or str(a.id)
                      for a in r.albums]) + ']', end='')                                   # type: ignore
            if hasattr(r, 'owner') and r.owner:                                            # type: ignore
                print(f' {{{r.owner.login}}}', end='')                                     # type: ignore
            if cat_type == 'podcast' or cat_type == 'artist':
                print(' ', end='')
            else:
                print(' ~ ', end='')
            print(f'{(r.title if hasattr(r, "title") else r.name)}', end='')               # type: ignore
            if hasattr(r, 'version') and r.version and not r.version.isspace():            # type: ignore
                print(f' @ {r.version}', end='')                                           # type: ignore
            if hasattr(r, 'duration_ms') and r.duration_ms:                                # type: ignore
                print(' ' + duration_str(r.duration_ms), end='')                           # type: ignore
            print() # new line
            if i >= count - 1:
                break

    if search.best:  # search_type == 'all':
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
        show_album(volumes)

    elif restype == 'track' or restype == 'podcast_episode':
        tracks = [cast(Track, res)]
        total_tracks = 1

    elif restype == 'playlist':
        res = cast(Playlist, res)
        tracks = res.tracks if res.tracks else res.fetch_tracks()
        total_tracks = res.track_count if res.track_count else len(tracks)
        show_playing_playlist(res, total_tracks)

    elif restype == 'user':  # TODO
        res = cast(User, res)
        print('Not implemented', res)
        sys.exit(3)

    elif restype == 'video':  # TODO
        res = cast(Video, res)
        print('Not implemented', res)
        sys.exit(3)

    else:  # unreachable
        print('Not implemented', res)
        sys.exit(3)

    # tracks tracks_download_info

    return total_tracks, tracks


def show_playing_album(a: Album, total_tracks: int) -> None:
    print(f'Playing {a.title} ({a.id}) by {"|".join(a.artists_name())}.'
          f' {total_tracks} track{plural(total_tracks)} {duration_str(a.duration_ms)}.')
    if a.short_description:
        print(a.short_description)
    if a.description:
        print(a.description)


def show_album(volumes: List[List[Track]]) -> None:
    for (iv, volume) in enumerate(volumes):
        print(f'{iv + 1}.')
        for (i, track) in enumerate(volume):
            print(f'{i + 1:>2}.',
                f'{track.title} @ {track.version}' if track.version else track.title,
                duration_str(track.duration_ms))


def getAutoTracks(client: Client, playlist_name: str, playlist_type: str) -> Tuple[int, List[TrackShort]]:
    if playlist_type == 'personal-playlists':
        # well-known names
        if playlist_name == 'playlistOfTheDay':
            id = '503646255:26954868'
        elif playlist_name == 'origin':
            id = '940441070:17870614'
        elif playlist_name == 'neverHeard':
            id = '692528232:114169885'
        elif playlist_name == 'recentTracks':
            id = '692529388:111791060'
        elif playlist_name == 'missedLikes':
            id = '460141773:108134812'
        elif playlist_name == 'kinopoisk':
            id = '1087766963:2441326'
        else:
            id = None
    else:
        id = None

    if id is not None:
        playlist = client.playlists_list(id)[0]
    else:
        playlist = show_and_search_auto_blocks(client, playlist_name, playlist_type)

    tracks = playlist.tracks if playlist.tracks else playlist.fetch_tracks()
    total_tracks = playlist.track_count if playlist.track_count else len(tracks)
    show_playing_playlist(playlist, total_tracks)

    return total_tracks, tracks


def show_and_search_auto_blocks(client: Client, playlist_name: str, playlist_type: str) -> Playlist:
    # new-releases: List[Album]
    # new-playlists: List[Playlist]
    # personal-playlists: List[GeneratedPlaylist]
    # 'personal-playlists, new-releases, new-playlists'
    landings = client.landing(playlist_type)
    # landings = client.landing('personal-playlists')  # same as 'personalplaylists'
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
                assert genPl.ready  # just check
                assert not genPl.description
            elif e.type == 'playlist':
                pl = cast(Playlist, e.data)
            else:
                print('Not implemented')
                sys.exit(3)

            assert not pl.type and not pl.playlist_uuid  # just check
            assert not pl.dummy_description and not pl.dummy_page_description
            assert not pl.og_data

            g = pl.generated_playlist_type
            if g and pl.id_for_from:
                g = f'{g} {pl.id_for_from}'
            elif pl.id_for_from:
                g = pl.id_for_from

            print(f'{tab * i}"{pl.title}"{f" {g}" if g else ""}',
                  f'({pl.uid}:{pl.kind} {pl.modified.split("T")[0] if pl.modified else "???"})'
                  f'\n{indent(pl.description.strip(), tab * (i + 1))}' if pl.description else '')
            assert pl.owner and pl.owner.uid == pl.uid  # just check

            if (genPl and genPl.type == playlist_name) or pl.id_for_from == playlist_name \
                    or (pl.title and playlist_name_icase in pl.title.casefold()):
                playlist = pl

    if playlist is None:
        print(f'auto playlist "{playlist_name}" not found')
        sys.exit(1)

    return playlist


def show_playing_playlist(playlist: Playlist, total_tracks: int) -> None:
    assert playlist.owner

    print(f'Playing {playlist.title}',
          f'({playlist.playlist_id} {playlist.modified.split("T")[0] if playlist.modified else "???"})',
          f'by {playlist.owner.login}.',
          f'{total_tracks} track{plural(total_tracks)} {duration_str(playlist.duration_ms)}.')
    if playlist.description:
        print(playlist.description)

    if playlist.generated_playlist_type == 'playlistOfTheDay':
        assert playlist.play_counter
        print(f'Playlist of the day streak: {playlist.play_counter.value}.',
              f'Updated: {playlist.play_counter.updated}')


def plural(count: int) -> str:
    return 's' if count != 1 else ''


def duration_str(duration_ms: Optional[int]) -> str:
    if duration_ms:
        sec = duration_ms // 1000
        min = sec // 60
        if min > 60:
            return f'{min // 60}:{min % 60:02}:{sec % 60:02}'
        else:
            return f'{min}:{sec % 60:02}'
    else:
        return '-:--'


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


def show_alice_shot(client: Client, track: Union[TrackShort, Track]) -> None:
    ev = client.after_track(track.track_id, '940441070:17870614')
    if not ev:
        print('Can\'t fetch after_track')
        return
    for shot in ev.shots:
        d = shot.shot_data
        assert shot.order == 0 and shot.status == 'ready', ev  # just check
        assert d.shot_type.id == 'alice' and d.shot_type.title == 'Шот от Алисы', ev
        # d.mds_url
        print(ev.event_id, d.shot_text)


def slugify(value: str) -> str:
    value = unicodedata.normalize('NFKC', value)  # normalized combined form
    value = value.strip()
    value = re.sub(r'\s+', ' ', value)  # collapse inner whitespace
    value = re.sub(r'^(\s*(?:CON|CONIN\$|CONOUT\$|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\s*(?:\..*)?)$',
                   r'_\1', value, flags=re.IGNORECASE)  # common special names
    return re.sub(r'[\x00-\x1F\x7F"*/:<>?|\\]', '_', value)  # reserved chars


def retry(func: 'Callable[P, T]', *args: 'P.args', **kwargs: 'P.kwargs') -> Union[T, Exception]:
    error_count = 0
    while error_count < MAX_ERRORS:
        try:
            return func(*args, **kwargs)
        except YMApiUnauthorized as e:
            print(' ', type(e), e)
            return e
        except YandexMusicError as e:
            # print(' YandexMusicError:', type(e).__name__, e, flush=True)
            if e.__context__ is JSONDecodeError:
                json_err = cast(JSONDecodeError, e.__context__)
                print(f' JSONDecodeError.doc: "{json_err.doc}"', flush=True)
            traceback.print_exc()
            error_count += 1
            sleep(3)
        except Exception as e:
            # print(' Exception:', type(e).__name__, e, flush=True)
            traceback.print_exc()
            error_count += 1
            sleep(1)

    return e  # type: ignore


def get_album_year(album: Album) -> int:
    y1 = int(album.release_date[:4]) if album.release_date else 9999
    y2 = int(album.original_release_year) if album.original_release_year else 9999
    y3 = album.year or 9999
    return min(y1, y2, y3)


def get_cache_path_for_track(track: Track, cache_folder: Path) -> Path:
    artist = track.artists[0] if track.artists \
        else SimpleNamespace(name='#_' + track.type if track.type else 'unknown', id=0)
    album = track.albums[0] if track.albums \
        else SimpleNamespace(id=0, version=None, track_position=None, title='')
    album_version = f' ({album.version})' if album.version and not album.version.isspace() else ''
    album_year = get_album_year(album) if not isinstance(album, SimpleNamespace) else 9999
    if album_year == 9999:
        album_year = ''
    track_version = f' ({track.version})' if track.version and not track.version.isspace() else ''
    tp = album.track_position
    track_pos = f'{tp.volume}-{tp.index}' if tp else ''

    artist_dir = slugify(f'{artist.name}_{artist.id}')
    album_dir = slugify(f'{album_year}_{album.title}{album_version}_{album.id}')
    filename = slugify(f'{track_pos}_{track.title}{track_version}_{track.id}.mp3')
    return cache_folder / artist_dir / album_dir / filename


def download_track(track: Track, cache_folder: Path, skip_long_path: bool) -> Optional[Path]:
    file_path = get_cache_path_for_track(track, cache_folder)
    if skip_long_path and len(str(file_path)) > 255:
        print('path is too long (MAX_PATH):', file_path)
        return None
    # vlc doesn't recognize \\?\ prefix :(
    # if (os.name == 'nt'):
    #     file_path = Path('\\\\?\\' + os.path.normpath(file_path))
    assert track.file_size is None or track.file_size == 0  # just check
    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        print('Downloading...', end='', flush=True)  # flush before stderr in retry
        err = retry(lambda x: track.download(x), file_path)
        if err:
            print(f'Error while downloading track_id: {track.track_id}'
            + f' real_id: {track.real_id}' if track.id != track.real_id else '')
            return None
        print('ok')
    return file_path


# class MyProtocol(asyncio.SubprocessProtocol):
#     def __init__(self, exit_future: asyncio.Future[bool]) -> None:
#         self.exit_future = exit_future
#
#     def process_exited(self) -> None:
#         if not self.exit_future.cancelled():
#             self.exit_future.set_result(True)


class AsyncInput:
    __slots__ = ('_loop', '_inp_future')
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._inp_future = None

    def readline(self) -> asyncio.Future[str]:
        if not self._inp_future or self._inp_future.done():
            self._inp_future = self._read_line_async()
        return self._inp_future

    def _read_line_async(self) -> asyncio.Future[str]:
        return self._loop.run_in_executor(None, sys.stdin.readline)  # TODO: daemon thread


async def play_track(i: int, total_tracks: int, track_or_short: Union[Track, TrackShort],
                    cache_folder: Path, player_cmd: List[str], async_input: AsyncInput,
                    show_id: bool, ignore_retcode: bool, skip_long_path: bool) -> None:
    track = track_from_short(track_or_short)
    show_playing_track(i, total_tracks, track, show_id)

    file_path = download_track(track, cache_folder, skip_long_path)
    if file_path == None:
        return

    player_cmd[-1] = str(file_path)

    # exit_future = asyncio.Future(loop=loop)
    # proc, myprot = await loop.subprocess_exec(lambda: MyProtocol(exit_future), *player_cmd)
    proc = await asyncio.create_subprocess_exec(*player_cmd, stderr=asyncio.subprocess.DEVNULL)
    exit_future = asyncio.create_task(proc.wait())
    try:
        inp_future = async_input.readline()

        while (True):
            done, pending = await asyncio.wait((exit_future, inp_future), return_when=asyncio.FIRST_COMPLETED)
            assert len(done) == 1, done

            f = done.pop()
            if f == exit_future:
                break
            else:
                assert f == inp_future
                inp = cast(str, f.result()).strip()
                if inp == 's' or inp == 'skip':
                    break
                elif inp == 'i' or inp == 'id':
                    print('id', track.track_id)
                elif inp == 'p' or inp == 'pause':
                    print('pause after this track. Press Any key to continue...')
                    await async_input.readline()
                elif inp == 't' or inp == 'text':
                    assert track.client
                    sup = track.client.track_supplement(track.track_id)
                    if sup and sup.description:
                        print(sup.description)
                    if not sup or not sup.lyrics:
                        print('no lyrics')
                        assert not track.lyrics_available  # just check
                    else:
                        assert track.lyrics_available  # just check
                        lyrics = sup.lyrics
                        if not lyrics.has_rights:
                            print(f'lyrics.has_rights:', lyrics.has_rights)
                        print(f'id: {lyrics.id} lang: {lyrics.text_language} '
                              f'show_translation: {lyrics.show_translation} url: {lyrics.url}\n')
                        print(lyrics.full_lyrics)
                elif inp == 'x' or inp == 'exit':
                    raise KeyboardInterrupt()  # TODO: cancelation
                else:
                    if inp != 'h' or inp != 'help':
                        print('Unknown command:', inp)
                    print('s: skip\ni: id\np: pause\nt: text\nx: exit\nh: help')

                inp_future = async_input.readline()
    finally:
        if not exit_future.done():
            proc.terminate()
            await exit_future

        if not ignore_retcode:
            rc = proc.returncode
            if rc:
                raise Exception(f'Command {player_cmd} returned non-zero exit status {rc}.')


def track_from_short(track_or_short: Union[Track, TrackShort]) -> Track:
    if isinstance(track_or_short, Track):
        track = track_or_short
    else:
        track = track_or_short.track if track_or_short.track else track_or_short.fetch_track()

    if track.real_id and track.id != track.real_id:
        print(f'track.id ({track.id}) != track.real_id ({track.real_id})')

    return track


def show_playing_track(i: int, total_tracks: int, track: Track, show_id: bool) -> None:
    # assert track.albums
    track_type = f'({track.type}) ' if track.type and track.type != 'music' and track.type != 'podcast-episode' else ''
    track_id = f'{track.track_id:<18} ' if show_id else ''
    print(f'{i + 1:>2}/{total_tracks}:',
          track_id + track_type +  # no space if omitted
          '|'.join(track.artists_name()),
          f"[{'|'.join((a.title or str(a.id)) if not a.version else f'{a.title} @ {a.version}' for a in track.albums)}]",
          '~', track.title if not track.version else f'{track.title} @ {track.version}',
          duration_str(track.duration_ms))
    if track.short_description:
        print(track.short_description)


def main() -> None:
    args = handle_args()

    if args.log_api:
        import logging
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    Client.notice_displayed = True
    client = Client.from_token(args.token, report_new_fields=args.report_new_fields)

    assert client.me and client.me.account
    acc = client.me.account
    print('Hello,', acc.first_name)
    if acc.now and acc.birthday and acc.now[5:10] == acc.birthday[5:10]:
        print('Happy birthday!')

    permission_alerts = client.permission_alerts()
    if permission_alerts and permission_alerts.alerts:
        print('\n==================\nPERMISSION_ALERTS:')
        for a in permission_alerts.alerts:
            print(a)
        print('==================')

    if args.mode == 'playlist':
        total_tracks, tracks = getPlaylistTracks(client, args.playlist_name)

    elif args.mode == 'likes':
        tracks_list = client.users_likes_tracks()
        assert tracks_list
        tracks = tracks_list.tracks
        total_tracks = len(tracks)
        print(f'Playing liked tracks. {total_tracks} track{plural(total_tracks)}.')

    elif args.mode == 'search':
        total_tracks, tracks = getSearchTracks(
            client, args.playlist_name, args.search_type, args.search_x, args.search_no_correct,
            args.count, args.show_id)

    elif args.mode == 'auto':
        total_tracks, tracks = getAutoTracks(client, args.playlist_name, args.auto_type)

    elif args.mode == 'radio':
        print('Not implemented')
        # TODO: use examples\Radio
        # rotor_stations_dashboard rotor_stations_list rotor_station_tracks
        sys.exit(3)

    elif args.mode == 'queue':
        # queue queues_list
        total_tracks, tracks = getTracksFromQueue()

    elif args.mode == 'id':
        if not args.playlist_name:
            print('Specify comma (",") separated track id list')
            sys.exit(1)
        tracks = client.tracks(args.playlist_name.split(','))  # TODO: trim empty (,,)
        total_tracks = len(tracks)

    else:  # unreachable
        sys.exit(3)

    if args.shuffle:
        from random import shuffle
        shuffle(tracks)

    if args.reverse:
        tracks.reverse()

    if args.export_list:
        print(','.join(t.track_id for t in tracks))
        return

    if args.skip == sys.maxsize:  # no need for async runtime
        skip_all_loop(args, client, total_tracks, tracks)
        return

    asyncio.run(async_main(args, client, total_tracks, tracks))


async def async_main(args: argparse.Namespace, client: Client,
                    total_tracks: int, tracks: Union[List[TrackShort], List[Track]]) -> None:
    my_input = AsyncInput(asyncio.get_event_loop())
    try:
        return await main_loop(args, client, total_tracks, tracks, my_input)
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print('Goodbye.')
    except BaseException as e:
        handle_exception(e)


async def main_loop(args: argparse.Namespace, client: Client,
                    total_tracks: int, tracks: Union[List[TrackShort], List[Track]],
                    async_input: AsyncInput) -> None:
    for (i, track_or_short) in enumerate(tracks):
        if args.skip > i:
            if args.show_skiped:
                track = track_from_short(track_or_short)
                show_playing_track(i, total_tracks, track, args.show_id)
            continue

        if args.alice:
            show_alice_shot(client, track_or_short)

        await play_track(i, total_tracks, track_or_short,
              args.cache_folder, args.player_cmd, async_input,
              args.show_id, args.ignore_retcode, args.skip_long_path)


def skip_all_loop(args: argparse.Namespace, client: Client,
                  total_tracks: int, tracks: Union[List[TrackShort], List[Track]]) -> None:
    for (i, track_or_short) in enumerate(tracks):
        track = track_from_short(track_or_short)
        show_playing_track(i, total_tracks, track, args.show_id)
        if args.alice:
            show_alice_shot(client, track_or_short)


def handle_exception(e: BaseException) -> None:
    print('Error:', type(e).__name__, f'"{e}"', flush=True)
    print('Cause:', type(e.__cause__).__name__, f'"{e.__cause__}"', flush=True)        # type: ignore
    print('Context:', type(e.__context__).__name__, f'"{e.__context__}"', flush=True)  # type: ignore
    print()  # new line
    # print('Exception:', type(e).__name__, e, flush=True)
    traceback.print_exc()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        pass
    except Exception as e:
        handle_exception(e)
