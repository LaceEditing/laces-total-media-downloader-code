"""Regression tests for the download pipeline: options, the external-engine
command line, job lifecycle, cancel cleanup, GPU transcoding choices and the
integrity checks on everything the app downloads and runs.

Run with a Python that has the app's dependencies available:

    python test/test_download_flow.py

No display is needed - the app class is imported but never instantiated.
"""

import functools
import hashlib
import http.server
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pygame is only used for the notification sound; stub it so the tests run on
# interpreters that have no pygame wheel available.
if 'pygame' not in sys.modules:
    try:
        import pygame  # noqa: F401
    except ImportError:
        _stub = types.ModuleType('pygame')
        _stub.mixer = types.SimpleNamespace(init=lambda *a, **k: None, music=None)
        sys.modules['pygame'] = _stub

from main import DownloadJob, VideoDownloaderApp  # noqa: E402

YOUTUBE_URL = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
PLAYLIST_URL = 'https://www.youtube.com/playlist?list=PL123'
_ENGINE_DIR = tempfile.mkdtemp(prefix='lace-test-engine-')
GPU = {'h264': 'h264_nvenc', 'hevc': 'hevc_nvenc'}


class _Done:
    """A set threading.Event stand-in: the GPU probe has already finished."""

    def wait(self, timeout=None):
        return True


def make_app(gpu=GPU):
    """A VideoDownloaderApp with just the attributes the pipeline needs."""
    app = object.__new__(VideoDownloaderApp)
    app.cookies_source = 'none'
    app.cookies_file = ''
    app._widen_player_clients = False
    app._browser_profile_dir = lambda browser: None
    app._engine_dir = lambda: _ENGINE_DIR
    app.ffmpeg_available = True
    app.ffmpeg_path = os.path.join(_ENGINE_DIR, 'ffmpeg.exe')
    app.ytdlp_exe_path = os.path.join(_ENGINE_DIR, 'yt-dlp.exe')
    app.hw_encoders = dict(gpu)
    app._hw_probe_done = _Done()
    app.hires_codec_default = 'auto'
    app.ask_hires_codec = True
    app._job = None
    app.after = lambda ms, fn=None, *a: None
    return app


def settings(**overrides):
    base = {'output_folder': _ENGINE_DIR, 'download_type': 'video', 'quality': 'Best',
            'audio_quality': '320 kbps', 'video_format': 'mp4', 'audio_format': 'mp3'}
    base.update(overrides)
    return base


def convertor_args(opts):
    return (opts.get('postprocessor_args') or {}).get('videoconvertor') or []


# --------------------------------------------------------------------------- #
#  The external engine must get the same options as the library                #
# --------------------------------------------------------------------------- #
def all_option_sets():
    app = make_app()
    sets = []
    for fmt in ('mp4', 'mkv', 'webm', 'avi', 'mov', 'flv'):
        for height in (720, 2160, 4320, None):
            for gpu in (True, False):
                sets.append(app._build_ydl_opts(settings(video_format=fmt), True, height,
                                                YOUTUBE_URL, prefer_gpu=gpu))
    for fmt in ('mp3', 'm4a', 'opus', 'ogg', 'wav', 'flac', 'aac'):
        sets.append(app._build_ydl_opts(settings(download_type='audio', audio_format=fmt),
                                        True, url=YOUTUBE_URL))
    sets.append(app._build_ydl_opts(settings(), False, url=PLAYLIST_URL, playlist_all=True))
    sets.append(app._build_ydl_opts(settings(), True, url=PLAYLIST_URL, single_item=True))
    app.cookies_source = 'firefox'
    sets.append(app._build_ydl_opts(settings(), True, url=YOUTUBE_URL))
    return sets


def test_every_option_reaches_the_external_engine():
    """A key with no CLI translation silently does nothing in the frozen build."""
    known = VideoDownloaderApp.ARGV_TRANSLATED_OPTS
    for opts in all_option_sets():
        missing = set(opts) - known
        assert not missing, f'options with no yt-dlp CLI translation: {missing}'


def test_engine_is_asked_for_utf8():
    """Without it the Windows binary writes the ANSI code page and drops characters."""
    argv = make_app()._build_ytdlp_argv({})
    assert argv[1:3] == ['--encoding', 'utf-8'], argv


def test_postprocessor_args_survive_spaces():
    app = make_app()
    args = ['-metadata', 'title=two words', '-c:v', 'h264_nvenc']
    argv = app._build_ytdlp_argv({'postprocessor_args': {'videoconvertor': args}})
    value = argv[argv.index('--postprocessor-args') + 1]
    name, _, joined = value.partition(':')
    assert name == 'videoconvertor'
    assert shlex.split(joined) == args, joined


def test_whole_playlist_keeps_going_past_bad_items():
    app = make_app()
    opts = app._build_ydl_opts(settings(), False, url=PLAYLIST_URL, playlist_all=True)
    argv = app._build_ytdlp_argv(opts)
    assert opts['ignoreerrors'] == 'only_download'
    assert '--no-abort-on-error' in argv


def test_single_item_choice_limits_a_playlist_url():
    """noplaylist alone still downloads all of a /playlist?list= URL."""
    app = make_app()
    opts = app._build_ydl_opts(settings(), True, url=PLAYLIST_URL, single_item=True)
    argv = app._build_ytdlp_argv(opts)
    assert argv[argv.index('-I') + 1] == '1'
    assert '--no-playlist' in argv


# --------------------------------------------------------------------------- #
#  GPU transcoding                                                             #
# --------------------------------------------------------------------------- #
def test_4k_mp4_is_transcoded_on_the_gpu():
    opts = make_app()._build_ydl_opts(settings(), True, 2160, YOUTUBE_URL)
    args = convertor_args(opts)
    assert opts['postprocessors'] == [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]
    assert opts['merge_output_format'] == 'mkv'
    assert 'h264_nvenc' in args and '+faststart' in args, args
    assert '+hdr' in opts['format_sort'], 'HDR source would wash out in 8-bit output'


def test_8k_mp4_uses_hevc_tagged_for_editors():
    args = convertor_args(make_app()._build_ydl_opts(settings(), True, 4320, YOUTUBE_URL))
    assert 'hevc_nvenc' in args
    assert args[args.index('-tag:v') + 1] == 'hvc1'


def test_4k_mp4_without_gpu_falls_back_to_mkv():
    for app, gpu in ((make_app(gpu={}), True), (make_app(), False)):
        opts = app._build_ydl_opts(settings(), True, 2160, YOUTUBE_URL, prefer_gpu=gpu)
        assert opts['merge_output_format'] == 'mkv'
        assert 'postprocessors' not in opts and 'postprocessor_args' not in opts


def test_1080p_mp4_is_never_transcoded():
    opts = make_app()._build_ydl_opts(settings(quality='1080p'), True, 1080, YOUTUBE_URL)
    assert opts['merge_output_format'] == 'mp4'
    assert 'postprocessor_args' not in opts


def test_mov_and_flv_use_the_gpu_and_avi_keeps_xvid():
    app = make_app()
    mov = convertor_args(app._build_ydl_opts(settings(video_format='mov'), True, 1080, YOUTUBE_URL))
    flv = convertor_args(app._build_ydl_opts(settings(video_format='flv'), True, 4320, YOUTUBE_URL))
    avi = app._build_ydl_opts(settings(video_format='avi'), True, 1080, YOUTUBE_URL)
    assert 'h264_nvenc' in mov and '+faststart' in mov
    assert 'h264_nvenc' in flv, 'FLV cannot carry HEVC'
    assert '-movflags' not in flv and '-tag:v' not in flv
    assert 'postprocessor_args' not in avi


def test_cpu_retry_uses_software_encoders():
    app = make_app()
    mov = convertor_args(app._build_ydl_opts(settings(video_format='mov'), True, 1080,
                                             YOUTUBE_URL, prefer_gpu=False))
    assert 'libx264' in mov and 'h264_nvenc' not in mov


def test_gpu_failure_is_recognised_for_the_retry():
    app = make_app()
    opts = app._build_ydl_opts(settings(), True, 2160, YOUTUBE_URL)
    assert app._uses_gpu_encoder(opts)
    assert app._is_conversion_error('ERROR: Postprocessing: Conversion failed!')
    assert not app._uses_gpu_encoder(app._build_ydl_opts(settings(), True, 2160, YOUTUBE_URL,
                                                         prefer_gpu=False))


# --------------------------------------------------------------------------- #
#  Reading the engine's output                                                 #
# --------------------------------------------------------------------------- #
def test_progress_template_lines_parse():
    parse = VideoDownloaderApp._parse_progress_line
    assert parse('[lace-progress] 1024 2048 NA 512.5 3') == (1024, 2048, 512.5, 3)
    assert parse('[lace-progress] 1024 NA 4096 NA NA') == (1024, 4096, None, None)
    assert parse('[download]  12.3% of 45.67MiB at 2.34MiB/s ETA 00:16') is None


def test_reported_paths():
    path = VideoDownloaderApp._reported_path
    assert path('[download] Destination: C:\\out\\100% real.f137.mp4') == 'C:\\out\\100% real.f137.mp4'
    assert path('[Merger] Merging formats into "C:\\out\\clip.mp4"') == 'C:\\out\\clip.mp4'
    assert path('[ExtractAudio] Destination: /out/song.mp3') == '/out/song.mp3'
    assert path('[download] clip.mp4 has already been downloaded') is None


def test_warnings_do_not_decide_how_a_failure_is_handled():
    detail = VideoDownloaderApp._error_detail([
        "WARNING: [youtube] Sign in to confirm you're not a bot",
        'ERROR: unable to download video data: HTTP Error 404: Not Found',
    ])
    assert detail == 'ERROR: unable to download video data: HTTP Error 404: Not Found'
    assert make_app()._is_auth_error(detail) is False


def test_webpage_errors_are_not_called_age_restricted():
    reason = VideoDownloaderApp._auth_reason('ERROR: Unable to download webpage: login required')
    assert 'age' not in reason.lower(), reason
    assert 'bot' in VideoDownloaderApp._auth_reason(
        "Sign in to confirm you're not a bot. This helps protect our community").lower()


# --------------------------------------------------------------------------- #
#  Job lifecycle                                                               #
# --------------------------------------------------------------------------- #
def lifecycle_app():
    app = make_app()
    ended = []
    app.after = lambda ms, fn=None, *a: fn() if fn else None
    app._end_download = ended.append
    app.update_status = lambda *a, **k: None
    app.progress_bar = types.SimpleNamespace(set=lambda v: None)
    app.engine_version_label = lambda: 'test engine'
    return app, ended


def test_handing_off_to_a_dialog_keeps_the_job_running():
    """The old finally-block reset let a second download start during a playlist."""
    app, ended = lifecycle_app()
    job = DownloadJob(YOUTUBE_URL, settings())
    app._run_job(job, lambda j: True)
    assert ended == [], 'job ended while a dialog still owned it'


def test_a_finished_or_failed_stage_ends_the_job_once():
    app, ended = lifecycle_app()
    job = DownloadJob('https://vimeo.com/1', settings())
    app._run_job(job, lambda j: False)

    def boom(j):
        raise Exception('ERROR: unable to download video data: HTTP Error 404')
    app._run_job(job, boom)
    assert ended == [job, job]


def test_end_download_is_idempotent():
    app = make_app()
    calls = []
    app.download_btn = types.SimpleNamespace(configure=lambda **kw: calls.append(kw))
    app.progress_label = types.SimpleNamespace(configure=lambda **kw: None)
    job = DownloadJob(YOUTUBE_URL, settings())
    app._job = job
    app._end_download(job)
    app._end_download(job)
    assert app._job is None and app.is_downloading is False
    assert len(calls) == 1 and calls[0]['text'] == 'DOWNLOAD'


def test_self_update_is_only_offered_to_a_built_app():
    """From source, the old updater moved the downloaded exe over main.py."""
    assert VideoDownloaderApp._can_self_update() is False
    with patch.object(sys, 'frozen', True, create=True):
        assert VideoDownloaderApp._can_self_update() is True


# --------------------------------------------------------------------------- #
#  Cancel                                                                       #
# --------------------------------------------------------------------------- #
def test_cancel_cleanup_only_touches_this_jobs_files():
    folder = Path(tempfile.mkdtemp(prefix='lace-test-cancel-'))
    fragment = folder / 'clip.f137.mp4'
    finished = folder / 'earlier item.mp4'
    unrelated = folder / 'my own video.mp4'
    for path in (fragment.with_name(fragment.name + '.part'),
                 fragment.with_name(fragment.name + '.ytdl'), finished, unrelated):
        path.write_bytes(b'x')
    job = DownloadJob(YOUTUBE_URL, settings())
    job.paths = {str(fragment), str(finished)}
    job.saved = [str(finished)]

    make_app()._remove_partial_files(job)

    assert sorted(p.name for p in folder.iterdir()) == ['earlier item.mp4', 'my own video.mp4']


def test_kill_process_tree_takes_the_grandchild_too():
    """yt-dlp runs ffmpeg as its own child; killing yt-dlp alone orphaned it."""
    child = (
        'import subprocess, sys, time\n'
        'g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        'print(g.pid, flush=True)\n'
        'time.sleep(60)\n'
    )
    app = make_app()
    process = app._popen_for_job(None, [sys.executable, '-c', child],
                                 stdout=subprocess.PIPE, text=True)
    grandchild = int(process.stdout.readline())
    VideoDownloaderApp._kill_process_tree(process)
    process.stdout.close()
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert process.poll() is not None
    assert not _alive(grandchild), 'grandchild survived'


def _alive(pid):
    if sys.platform == 'win32':
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
#  Integrity of what the app downloads and runs                                #
# --------------------------------------------------------------------------- #
SUMS = ('61db8e295ad89bd214e0ef52c11111f6f345fc530a5e2e52200ba3b4b4b09edb  yt-dlp.exe\n'
        'e96ebc0e090ad01514ed97f87f13f31abd3711a5ca595fbcc0544cde4227f96b  yt-dlp_linux\n')
DENO_WINDOWS = ('\nAlgorithm : SHA256\nHash      : CBA84B26E0DF5AE7F74FC66B86A95B866872A86292EBD84F'
                'A1E959927EDD93BF\nPath      : C:\\a\\deno-x86_64-pc-windows-msvc.zip\n')


def test_checksum_listings_parse():
    parse = VideoDownloaderApp._parse_sha256
    assert parse(SUMS, 'yt-dlp_linux').startswith('e96ebc0e')
    assert parse(SUMS, 'yt-dlp_macos') is None, 'must never fall back to another file\'s hash'
    assert parse(DENO_WINDOWS) == 'cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf'
    assert parse(None) is None


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(folder):
    handler = functools.partial(_QuietHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}/'


def test_verified_download_accepts_good_and_rejects_bad():
    source = Path(tempfile.mkdtemp(prefix='lace-test-src-'))
    dest = Path(tempfile.mkdtemp(prefix='lace-test-dst-'))
    payload = os.urandom(200_000)
    (source / 'engine.bin').write_bytes(payload)
    good = hashlib.sha256(payload).hexdigest()
    server, base = serve(source)
    try:
        path = VideoDownloaderApp._download_to(base + 'engine.bin', str(dest), good, min_size=1000)
        assert Path(path).read_bytes() == payload
        os.remove(path)
        for expected, min_size in (('0' * 64, 1000), (good, 10_000_000)):
            try:
                VideoDownloaderApp._download_to(base + 'engine.bin', str(dest), expected,
                                                min_size=min_size)
            except Exception:
                pass
            else:
                raise AssertionError('a bad download was accepted')
        assert list(dest.iterdir()) == [], 'a rejected download left its temp file'
    finally:
        server.shutdown()


def test_swap_replaces_and_cleans_up():
    folder = Path(tempfile.mkdtemp(prefix='lace-test-swap-'))
    dest, new = folder / 'yt-dlp.exe', folder / 'incoming.tmp'
    dest.write_bytes(b'old')
    new.write_bytes(b'new')
    VideoDownloaderApp._swap_in(str(new), str(dest))
    assert dest.read_bytes() == b'new'
    assert sorted(p.name for p in folder.iterdir()) == ['yt-dlp.exe']


def test_leftover_cleanup_only_removes_our_own_old_files():
    folder = Path(tempfile.mkdtemp(prefix='lace-test-old-'))
    exe = folder / 'LacesTotalMediaDownloader_v3.9.0.exe'
    ours = folder / (exe.name + '.123-456.old')
    users = folder / 'notes.old'
    for path in (exe, ours, users):
        path.write_bytes(b'x')
    app = make_app()
    app._engine_dir = lambda: str(folder / 'engine-does-not-exist')
    with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(exe)):
        app._cleanup_replaced_binaries()
    assert not ours.exists()
    assert users.exists(), "deleted a user's .old file"


# --------------------------------------------------------------------------- #
#  Settings and folders                                                        #
# --------------------------------------------------------------------------- #
def test_damaged_config_does_not_stop_startup():
    home = Path(tempfile.mkdtemp(prefix='lace-test-home-'))
    (home / '.lace_downloader_config.json').write_text('["not", "a", "dict"]', encoding='utf-8')
    with patch.object(Path, 'home', return_value=home):
        assert make_app().load_config() == {}


def test_config_round_trips_atomically():
    home = Path(tempfile.mkdtemp(prefix='lace-test-home-'))
    app = make_app()
    app.recent_folders = ['C:\\Users\\Zoë\\Videos']
    with patch.object(Path, 'home', return_value=home):
        app.save_config()
        assert app.load_config()['recent_folders'] == ['C:\\Users\\Zoë\\Videos']
    assert sorted(p.name for p in home.iterdir()) == ['.lace_downloader_config.json']


def test_recent_folder_labels_stay_unique():
    app = make_app()
    tail = '\\' + 'x' * 40
    app.recent_folders = ['C:\\one' + tail, 'D:\\two' + tail]
    shown = []
    app.recent_dropdown = types.SimpleNamespace(configure=lambda values: shown.extend(values))
    app.update_recent_dropdown()
    assert len(set(shown)) == 2, shown
    assert sorted(app._recent_display_to_path.values()) == sorted(app.recent_folders)


def main():
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith('test_') and callable(obj)]
    failures = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append((name, f'FAIL: {e}'))
            print(f'FAIL  {name}: {e}')
        except Exception as e:
            failures.append((name, f'ERROR: {type(e).__name__}: {e}'))
            print(f'ERROR {name}: {type(e).__name__}: {e}')
        else:
            print(f'ok    {name}')
    print(f'\n{len(tests) - len(failures)}/{len(tests)} passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
