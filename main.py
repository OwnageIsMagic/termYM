#!/usr/bin/env python3
import argparse
import asyncio
from datetime import datetime
import os
from random import random
import re
import sys
import traceback
import unicodedata
from json.decoder import JSONDecodeError
from pathlib import Path
from textwrap import indent
from time import sleep
from types import SimpleNamespace
from typing import TYPE_CHECKING, Callable, Final, Optional, TypeVar, Union, cast

# from radio import Radio
# sys.path.append('~/source/pyt/yandex-music-api/')
from yandex_music import Artist, Client, Playlist, SearchResult, Track, TrackShort
from yandex_music.album.album import Album
from yandex_music.base import YandexMusicObject
from yandex_music.exceptions import NetworkError as YMNetworkError, Unauthorized as YMApiUnauthorized, YandexMusicError
from yandex_music.feed.generated_playlist import GeneratedPlaylist
from yandex_music.playlist.user import User
from yandex_music.video import Video

T = TypeVar('T')
if TYPE_CHECKING:
    from typing_extensions import ParamSpec
    P = ParamSpec('P')

MAX_ERRORS: Final = 3


def handle_args() -> argparse.Namespace:
    DEFAULT_CACHE_FOLDER = Path(__file__).resolve().parent / '.YMcache'
    CONFIG_FILE_NAME = 'config'

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
                        help='do not show Alice shots')

    search = parser.add_argument_group('search')
    search.add_argument('--search-type', '-t', choices={'all', 'artist', 'a', 'user', 'u', 'album', 'b',
                        'playlist', 'p', 'track', 't', 'podcast', 'c', 'podcast_episode', 'ce', 'video', 'v'},
                        default='all',
                        help='type of search. Default: %(default)r'
                        ' При поиске type=all не возвращаются подкасты и эпизоды.'
                        ' Указывайте конкретный тип для поиска')
    search.add_argument('--search-x', '-x', type=int, default=1, metavar='X',
                        help='use specific search result')
    search.add_argument('--search-count', type=int, default=5, metavar='N',
                        help='show %(metavar)s search results')
    search.add_argument('--search-no-correct', action='store_true',
                        help='no autocorrection for search')

    parser.add_argument('--no-send-status', dest='send_status', action='store_false',
                        help='do not send playing status')
    parser.add_argument('--batch-like', action='store_true',
                        help='like all tracks in list')
    parser.add_argument('--batch-remove-like', action='store_true',
                        help='remove like from all tracks in list')
    parser.add_argument('--list', '-l', action='store_true',
                        help='only show tracks')
    parser.add_argument('--skip', '-s', metavar='N', type=int, default=0,
                        help='skip first %(metavar)s tracks')
    parser.add_argument('--count', '-c', metavar='N', type=int, default=0,
                        help='take only first %(metavar)s tracks (after skipped)')
    parser.add_argument('--show-skipped', action='store_true',
                        help='show skipped tracks')
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
    parser.add_argument('--ignore-retcode', action=argparse.BooleanOptionalAction, default=os.name == 'nt',
                        help='ignore audio player return code. Default on Windows')
    parser.add_argument('--skip-long-path', action=argparse.BooleanOptionalAction, default=os.name == 'nt',
                        help='skip track if file path is over MAX_PATH. Default on Windows')
    parser.add_argument('--report-new-fields', action='store_true',
                        help='report new fields from API')
    parser.add_argument('--ignore-ssl', action='store_true',
                        help='ignore SSL errors')
    parser.add_argument('--print-args', action='store_true',
                        help='print arguments (with resolved default values) and exit')
    args = parser.parse_args()

    if args.audio_player is parser.get_default('audio_player') \
            and args.audio_player_arg is parser.get_default('audio_player_arg'):
        args.audio_player_arg = ['-I', 'dummy', '--play-and-exit', '--quiet']

    args.player_cmd = args.audio_player_arg
    args.player_cmd.insert(0, args.audio_player)
    args.player_cmd.append('')  # will be replaced with filename

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

    if type(args.token) is str and len(args.token) == 39 and re.match(r'^\w{39}$', args.token, re.ASCII):
        if not args.no_save_token:
            args.cache_folder.mkdir(parents=True, exist_ok=True)
            (args.cache_folder / CONFIG_FILE_NAME).write_text(args.token)
    else:
        try:
            args.token = Path(args.token).read_text()
        except FileNotFoundError:
            print('Config file not found. Use --token to create it.')
            sys.exit(2)

    return args


def flatten(inp: list[list[T]]) -> list[T]:
    res: list[T] = []
    for l in inp:
        res.extend(l)
    return res


def try_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None


# def try_int_or(value: str, default: T) -> Union[tuple[int, Literal[True]], tuple[T, Literal[False]]]:
#     try:
#         return int(value), True
#     except ValueError:
#         return default, False


def show_attributes(obj: Union[YandexMusicObject, list, None], ignored: set[str] = {
            'available_for_mobile', 'available_for_premium_users', 'available',
            'client', 'cover_uri', 'cover', 'download_info', 'og_image', 'preview_duration_ms', 'storage_dir'
        }) -> None:
    if obj is None:
        print('None')
        return
    from pprint import pprint

    def attributes(obj: Union[YandexMusicObject, list], ignored: set[str],
            types: tuple[type, ...] = (YandexMusicObject, list)) -> Union[list, dict]:

        if isinstance(obj, list):
            return [v if not isinstance(v, types) else attributes(v, ignored) for v in obj]

        return {
            k: v if not isinstance(v, types) else attributes(v, ignored)
                for k, v in vars(obj).items()
                    if k[0] != '_' and k not in ignored and v  # ignore falsy values
            }

    pprint(attributes(obj, ignored))


def getTracksFromQueue(client: Client) -> tuple[int, list[TrackShort]]:
    # queue queues_list
    queues = client.queues_list()
    print(len(queues), 'queues')
    for q in queues:
        show_attributes(q)
    print('Not implemented')
    sys.exit(3)
    return 0, []


def getSearchTracks(client: Client, playlist_name: str, search_type: str, search_x: int,
                    search_no_correct: bool, search_count:int, show_id: bool
                   ) -> tuple[int, Union[list[Track], list[TrackShort]]]:
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
        for (i, r) in enumerate(cat.results, 1):                                           # TODO: maybe Protocol?
            if isinstance(r, Artist):
                w = 18 if show_id else 8
                print(f'{i}. {r.id:<{w}} {r.name}', end='')
                if r.genres: print(f' [{", ".join(r.genres)}]')
                else: print()
                continue

            if show_id:
                id = r.track_id if hasattr(r, 'track_id') else r.playlist_id if hasattr(   # type: ignore
                    r, 'playlist_id') else r.id                                            # type: ignore
                sid = f' {id:<18}'
            else: sid = ''

            print(f'{i}.{sid}', end='')
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
            if isinstance(r, Album):
                print(f' [{get_album_year(r)}]', end='')
            if hasattr(r, 'duration_ms') and r.duration_ms:                                # type: ignore
                print(' ' + duration_str(r.duration_ms), end='')                           # type: ignore
            print() # new line
            if i >= search_count:
                break

    if search.best:  # 'all'
        res = search.best.result
        restype = search.best.type
        print(f'Best match: [{restype}]')
    else:
        searchres: SearchResult
        if search_type == 'all'\
            or (searchres := search[search_type + 's']) is None\
            or len(searchres.results) == 0:
            print(f'Nothing found for "{search.text}", type={search.type_}')
            show_attributes(search)
            sys.exit(1)

        restype = searchres.type
        res = searchres.results[search_x - 1]
        print(f'Selecting {search_x} [{restype}]')

    if restype == 'artist':
        # artists artists_tracks artists_direct_albums
        artist = cast(Artist, res)
        print(artist.name, f'({artist.id})', artist.aliases or '', artist.db_aliases or '')
        while True:
            inp = input('[p]opular*/[a]ll/al[b]ums/[i]nfo/du[m]p? ')
            if not inp or inp == 'p' or inp == 'popular':
                artist_tracks = artist.get_tracks()  # popular_tracks
                assert artist_tracks
                tracks = artist_tracks.tracks
                total_tracks = len(tracks)
                break

            elif inp == 'b' or inp == 'albums':
                artist_albums = artist.get_albums(page_size=250)
                assert artist_albums
                assert len(artist_albums.albums) != 250  # just in case
                albums = artist_albums.albums
                for i, b in enumerate(albums, 1):
                    print(f'{i:>2}.',
                         (f'{b.id:<8} ' if show_id else '') +
                         (f'({b.type}) ' if b.type else '') +
                         (f'{b.title} @ {b.version}' if b.version else b.title or '???'),
                         f'[{get_album_year(b)}]')

                while True:
                    ind = try_int(input('Which one? '))
                    if ind is not None and 0 < ind <= len(albums):
                        break
                album = albums[ind - 1]
                total_tracks, tracks = getAlbumTracks(album)
                break

            elif inp == 'a' or inp == 'all':
                artist_tracks = artist.get_tracks(0, 250)  # TODO
                assert artist_tracks
                tracks = artist_tracks.tracks
                total_tracks = len(tracks)
                break

            elif inp == 'i' or inp == 'info':
                brief = client.artists_brief_info(artist.id)
                show_attributes(brief)
                continue

            elif inp == 'm' or inp == 'dump':
                show_attributes(artist)
                continue

    elif restype == 'album' or restype == 'podcast':
        # albums albums_with_tracks
        res = cast(Album, res)
        total_tracks, tracks = getAlbumTracks(res)

    elif restype == 'track' or restype == 'podcast_episode':
        tracks = [cast(Track, res)]
        total_tracks = 1

    elif restype == 'playlist':
        res = cast(Playlist, res)
        tracks = res.tracks or res.fetch_tracks()
        total_tracks = res.track_count or len(tracks)
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


def getAlbumTracks(album: Album) -> tuple[int, list[Track]]:
    if not album.volumes:
        album = album.with_tracks()  # type: ignore
        assert album and album.volumes
    volumes = album.volumes

    tracks = flatten(volumes)
    total_tracks = album.track_count or len(tracks)

    show_playing_album(album, total_tracks)
    show_album(volumes)

    return total_tracks, tracks


def show_playing_album(a: Album, total_tracks: int) -> None:
    print(f'Playing {a.title} ({a.id}) by {"|".join([f"{i.name} ({i.id})" for i in a.artists])}.'
          f' {total_tracks} track{plural(total_tracks)} {duration_str(a.duration_ms)}.')
    if a.short_description:
        print(a.short_description)
    if a.description:
        print(a.description)


def show_album(volumes: list[list[Track]]) -> None:
    for (iv, volume) in enumerate(volumes, 1):
        print(f'vol {iv}.')
        for (i, track) in enumerate(volume, 1):
            print(f'{i:>2}.',
                f'{track.title} @ {track.version}' if track.version else track.title,
                duration_str(track.duration_ms))


def getAutoTracks(client: Client, playlist_name: str, playlist_type: str) -> tuple[int, list[TrackShort]]:
    id = None
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

    if id is not None:
        playlist = client.playlists_list(id)[0]
    else:
        playlist = show_and_search_auto_blocks(client, playlist_name, playlist_type)

    tracks = playlist.tracks or playlist.fetch_tracks()
    total_tracks = playlist.track_count or len(tracks)
    show_playing_playlist(playlist, total_tracks)

    return total_tracks, tracks


def show_and_search_auto_blocks(client: Client, playlist_name: str, playlist_type: str) -> Playlist:
    # new-releases: list[Album]
    # new-playlists: list[Playlist]
    # personal-playlists: list[GeneratedPlaylist]
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
            l = 1
            tab = '    '
            if e.type == 'personal-playlist':
                genPl = cast(GeneratedPlaylist, e.data)
                assert genPl.data, genPl
                pl = genPl.data

                print(f'{tab * l}{genPl.type}{" *" if genPl.notify else ""}')
                l += 1
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

            print(f'{tab * l}"{pl.title}"{f" {g}" if g else ""}',
                  f'({pl.uid}:{pl.kind} {pl.modified.split("T")[0] if pl.modified else "???"})'
                  f'\n{indent(pl.description.strip(), tab * (l + 1))}' if pl.description else '')
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

    # if playlist.generated_playlist_type == 'playlistOfTheDay':
    #     assert playlist.play_counter
    #     print(f'Playlist of the day streak: {playlist.play_counter.value}. '
    #           f'Updated: {playlist.play_counter.updated}')


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


def getPlaylistTracks(client: Client, playlist_name: str) -> tuple[int, list[TrackShort]]:
    user_playlists = client.users_playlists_list()

    playlist = next((p for p in user_playlists if p.title == playlist_name), None) if playlist_name else None
    if playlist is None:
        if not playlist_name:
            print('Specify playlist_name.', end='')
        else:
            print(f'Playlist "{playlist_name}" not found.', end='')
        print(' Available:', [p.title for p in user_playlists])
        sys.exit(1)

    tracks = playlist.tracks or playlist.fetch_tracks()
    total_tracks = playlist.track_count or len(tracks)
    show_playing_playlist(playlist, total_tracks)

    return total_tracks, tracks


def show_alice_shot(client: Client, track: Union[TrackShort, Track]) -> None:
    ev = client.after_track(track.track_id, '940441070:17870614')  # origin
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
                   r'_\1', value, 1, flags=re.IGNORECASE)  # common special names
    return re.sub(r'[\x00-\x1F\x7F"*/:<>?|\\]', '_', value)  # reserved chars


def get_exception_root(exception: BaseException) -> BaseException:
    while exception.__context__:
        exception = exception.__context__
    return exception


def retry(func: 'Callable[P, T]', *args: 'P.args', **kwargs: 'P.kwargs') -> Union[T, Exception]:
    error_count = 0
    while error_count < MAX_ERRORS:
        try:
            err = None
            if error_count > 0:
                print('RETRYING', error_count)
            return func(*args, **kwargs)
        except YMNetworkError as e:
            error_count += 1
            err = e
            if error_count == 1:
                print(f' {type(e).__name__} {get_exception_root(e)} '
                    if 'SSL' not in type(e.__context__).__name__ else ' SSL ', end='')
            else:
                traceback.print_exc()
                print()  # new line
                sleep(3)
        except YMApiUnauthorized as e:
            print(' ', type(e).__name__, e)
            return e
        except YandexMusicError as e:
            # print(' YandexMusicError:', type(e).__name__, e, flush=True)
            if isinstance(e.__context__, JSONDecodeError):
                print(f' JSONDecodeError.doc: "{cast(JSONDecodeError, e.__context__).doc}"', flush=True)
            error_count += 1
            err = e
            traceback.print_exc()
            print()  # new line
            sleep(3)
        except Exception as e:
            # print(' Exception:', type(e).__name__, e, flush=True)
            error_count += 1
            err = e
            traceback.print_exc()
            print()  # new line
            sleep(1)

    return err  # type: ignore


def get_album_year(album: Album) -> int:
    y1 = int(album.release_date[:4]) if album.release_date else 9999
    y2 = int(album.original_release_year) if album.original_release_year else 9999
    y3 = album.year or 9999
    return min(y1, y2, y3)


def get_cache_path_for_track(track: Track, cache_folder: Path) -> Path:
    artist = track.artists[0] if track.artists else SimpleNamespace(id=0, name='#_' + (track.type or 'unknown'))
    album = track.albums[0] if track.albums else SimpleNamespace(id=0, version=None, track_position=None, title='')

    album_version = f' ({album.version})' if album.version and not album.version.isspace() else ''
    album_year = get_album_year(album) if not isinstance(album, SimpleNamespace) else ''

    track_version = f' ({track.version})' if track.version and not track.version.isspace() else ''
    tp = album.track_position
    track_pos = f'{tp.volume}-{tp.index}' if tp else ''

    artist_dir = slugify(f'{artist.name}_{artist.id}')
    album_dir = slugify(f'{album_year}_{album.title}{album_version}_{album.id}')
    filename = slugify(f'{track_pos}_{track.title}{track_version}_{track.id}.mp3')
    return cache_folder / artist_dir / album_dir / filename


def download_track(track: Track, cache_folder: Path, skip_long_path: bool) -> Optional[Path]:
    file_path = get_cache_path_for_track(track, cache_folder)
    if skip_long_path and len(str(file_path)) >= 260:
        print('path is too long (MAX_PATH):', file_path)
        return None
    # vlc doesn't recognize \\?\ prefix :(
    # if os.name == 'nt':
    #     file_path = Path('\\\\?\\' + os.path.normpath(file_path))
    assert track.file_size is None or track.file_size == 0  # just check
    fsize = 0
    if not file_path.exists() or (fsize := file_path.stat().st_size) < 16:
        if fsize > 0:
            print(f'Overwriting {fsize} bytes ({file_path})')
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
                    cache_folder: Path, player_cmd: list[str], async_input: AsyncInput,
                    show_id: bool, ignore_retcode: bool, skip_long_path: bool) -> Optional[Track]:
    track = track_from_short(track_or_short)
    show_playing_track(i, total_tracks, track, show_id)

    file_path = download_track(track, cache_folder, skip_long_path)
    if file_path is None:
        return None

    liked = False
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

                elif inp == 'l' or inp == 'like':
                    if liked:
                        print('already liked')
                    else:
                        if track.like():
                            print('liked')
                            liked = True
                        else:
                            print('like error')

                elif inp == 't' or inp == 'text':
                    sup = track.get_supplement()
                    if sup and sup.description:
                        print(sup.description)
                    if not sup or not sup.lyrics:
                        print('no lyrics')
                        if track.lyrics_available:  # just check
                            print(f'track.lyrics_available, but no sup or no sup.lyrics. sup:', sup)
                    else:
                        assert track.lyrics_available  # just check
                        lyrics = sup.lyrics
                        if not lyrics.has_rights:
                            print(f'lyrics.has_rights:', lyrics.has_rights)
                        print(f'id: {lyrics.id} lang: {lyrics.text_language} '
                              f'show_translation: {lyrics.show_translation} url: {lyrics.url}\n')
                        print(lyrics.full_lyrics)

                elif inp == 'k' or inp == 'link':
                    al = f'/album/{track.albums[0].id}' if track.albums else ''
                    print(f'https://music.yandex.ru{al}/track/{track.id}')
                    print(f'"{file_path}"')

                elif inp == 'm' or inp == 'dump':
                    show_attributes(track)

                elif inp == 'x' or inp == 'exit':
                    raise KeyboardInterrupt()  # TODO: cancelation

                elif len(inp) == 0:
                    pass

                else:
                    if inp != 'h' or inp != 'help':
                        print('Unknown command:', inp)
                    print('s: skip\ni: id\np: pause\nl: like\nt: text\nk: link\nm: dump\nx: exit\nh: help')

                inp_future = async_input.readline()
    finally:
        if not exit_future.done():
            proc.terminate()
            await exit_future

        if not ignore_retcode:
            rc = proc.returncode
            if rc:
                raise Exception(f'Command {player_cmd} returned non-zero exit status {rc}.')

    return track


def track_from_short(track_or_short: Union[Track, TrackShort]) -> Track:
    if isinstance(track_or_short, Track):
        track = track_or_short
    else:
        track = track_or_short.track or track_or_short.fetch_track()

    if track.real_id and (track.id != track.real_id and int(track.id) != int(track.real_id)):
        print(f'track.id ({track.id}) != track.real_id ({track.real_id})')

    if track.meta_data:
        show_attributes(track.meta_data, { 'client' })

    return track


def show_playing_track(n: int, total_tracks: int, track: Track, show_id: bool) -> None:
    # assert track.albums  # not available tracks doesn't have album: 4101273:4218688 Tilman Sillescu [] ~ No Escape
    track_type = f'({track.type}) ' if track.type and track.type != 'music' and track.type != 'podcast-episode' else ''
    track_id = f'{track.track_id:<18} ' if show_id else ''
    print(f'{n:>2}/{total_tracks}:',
          track_id + track_type +  # no space if omitted
          '|'.join(track.artists_name()),
          f"[{'|'.join((a.title or str(a.id)) if not a.version else f'{a.title} @ {a.version}' for a in track.albums)}]",
          '~', track.title if not track.version else f'{track.title} @ {track.version}',
          duration_str(track.duration_ms))
    if track.short_description:
        print(track.short_description)


def generate_play_id() -> str:
    return f"{int(random() * 1000)}-{int(random() * 1000)}-{int(random() * 1000)}"


def main(args: argparse.Namespace) -> None:
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
        tracks_list = client.users_likes_tracks()  # TODO: if_modified_since_revision tracks_list.revision
        assert tracks_list
        tracks = tracks_list.tracks
        total_tracks = len(tracks)
        print(f'Playing liked tracks. {total_tracks} track{plural(total_tracks)}.')

    elif args.mode == 'search':
        total_tracks, tracks = getSearchTracks(
            client, args.playlist_name, args.search_type, args.search_x, args.search_no_correct,
            args.search_count, args.show_id)

    elif args.mode == 'auto':
        total_tracks, tracks = getAutoTracks(client, args.playlist_name, args.auto_type)

    elif args.mode == 'radio':
        print('Not implemented')
        # TODO: use examples\Radio
        # rotor_stations_dashboard rotor_stations_list rotor_station_tracks
        sys.exit(3)

    elif args.mode == 'queue':
        total_tracks, tracks = getTracksFromQueue(client)

    elif args.mode == 'id':
        if not args.playlist_name:
            print('Specify comma (",") separated track id list')
            sys.exit(1)
        ids = [id for id in args.playlist_name.split(',') if len(id)]  # type: list[str]

        d = { 't': list[str](), 'b': list[str](), 'p': list[str]() }

        for id in ids:
            prefix = id[0]
            if prefix.isdigit():
                d['t'].append(id)
                continue
            if prefix not in d:
                raise Exception('Unknown prefix ' + prefix)
            d[prefix].append(id[1:])

        tracks = list[Union[Track, TrackShort]]()
        total_tracks = 0

        tracks_ids = d['t']
        if tracks_ids:
            tracks.extend(client.tracks(tracks_ids))  # type: ignore
            total_tracks += len(tracks)

        albums_ids = d['b']
        if albums_ids:
            for id in albums_ids:
                album = client.albums_with_tracks(id)
                assert album and album.volumes
                album_tracks = flatten(album.volumes)
                tracks.extend(album_tracks)
                total_tracks += len(album_tracks)

        playlist_ids = d['p']
        if playlist_ids:
            for id in playlist_ids:
                if id.find(':'):
                    ownerid, kind = id.split(':', 2)
                else:
                    ownerid, kind = None, id

                playlist: Playlist = client.users_playlists(kind, ownerid)  # type: ignore
                tracks.extend(playlist.tracks)
                total_tracks += len(playlist.tracks)

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

    if args.batch_remove_like:
        if client.users_likes_tracks_remove([t.track_id for t in tracks]):
            print('removed likes')
        else:
            print('error users_likes_tracks_remove')

    if args.batch_like:
        if client.users_likes_tracks_add([t.track_id for t in tracks]):
            print('liked')
        else:
            print('error users_likes_tracks_add')

    if args.list or args.skip >= sys.maxsize:  # no need for async runtime
        skip_all_loop(args, client, total_tracks, tracks, args.skip, args.count)
        return

    asyncio.run(async_main(args, client, total_tracks, tracks))


async def async_main(args: argparse.Namespace, client: Client,
                     total_tracks: int, tracks: Union[list[TrackShort], list[Track], list[Union[Track, TrackShort]]]
                    ) -> None:
    my_input = AsyncInput(asyncio.get_event_loop())
    try:
        return await main_loop(args, client, total_tracks, tracks, my_input)
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print('Goodbye.')
    except BaseException as e:
        handle_exception(e)


async def main_loop(args: argparse.Namespace, client: Client,
                    total_tracks: int, tracks: Union[list[TrackShort], list[Track], list[Union[Track, TrackShort]]],
                    async_input: AsyncInput) -> None:
    for (i, track_or_short) in enumerate(tracks, 1):
        if args.skip >= i:
            if args.show_skipped:
                track = track_from_short(track_or_short)
                show_playing_track(i, total_tracks, track, args.show_id)
            continue

        if args.alice:
            show_alice_shot(client, track_or_short)

        track = await play_track(i, total_tracks, track_or_short,
              args.cache_folder, args.player_cmd, async_input,
              args.show_id, args.ignore_retcode, args.skip_long_path)

        if args.send_status and track:
            now = f'{datetime.now().isoformat()}Z'
            played_seconds = (track.duration_ms or 0) // 1000
            ret = client.play_audio(track.id, "termYM", track.albums[0].id or 0 if track.albums else 0,
                              track_length_seconds=played_seconds,
                              end_position_seconds=played_seconds,
                              total_played_seconds=played_seconds,
                              #   playlist_id,
                              play_id=generate_play_id(), timestamp=now, client_now=now)
            assert ret

        if args.count and args.skip + args.count <= i:
            break


def skip_all_loop(args: argparse.Namespace, client: Client,
                  total_tracks: int, tracks: Union[list[TrackShort], list[Track], list[Union[Track, TrackShort]]],
                  skip: int, count: int) -> None:
    for (i, track_or_short) in enumerate(tracks, 1):
        if skip >= i:
            continue
        track = track_from_short(track_or_short)
        show_playing_track(i, total_tracks, track, args.show_id)
        if args.alice:
            show_alice_shot(client, track_or_short)

        if count and skip + count <= i:
            break


def handle_exception(e: BaseException) -> None:
    print('Error:', type(e).__name__, f'"{e}"', flush=True)
    print('Cause:', type(e.__cause__).__name__, f'"{e.__cause__}"', flush=True)        # type: ignore
    print('Context:', type(e.__context__).__name__, f'"{e.__context__}"', flush=True)  # type: ignore
    if isinstance(e.__context__, JSONDecodeError):
        print(f' JSONDecodeError.doc: "{cast(JSONDecodeError, e.__context__).doc}"', flush=True)
    print()  # new line
    # print('Exception:', type(e).__name__, e, flush=True)
    traceback.print_exc()
    print()  # new line


if __name__ == '__main__':
    try:
        args = handle_args()
        if args.ignore_ssl:
            from no_ssl_ctx import no_ssl_verification
            with no_ssl_verification():
                main(args)
        else:
            main(args)
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        pass
    except Exception as e:
        handle_exception(e)
