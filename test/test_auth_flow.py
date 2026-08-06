"""Regression tests for the YouTube sign-in / cookie handling.

These cover the bug where the sign-in popup appeared for *every* video: the app
attached ``--cookies-from-browser <default browser>`` to every YouTube URL, and
Chromium browsers (Chrome/Edge/Brave) keep their cookie database locked while
they are running, so yt-dlp failed with

    ERROR: Could not copy Chrome cookie database

which the app then misread as "this video is age-restricted".

Run with a Python that has the app's dependencies available:

    python test/test_auth_flow.py

No display is needed - the app class is imported but never instantiated.
"""

import os
import sys
import tempfile
import types

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

from main import VideoDownloaderApp  # noqa: E402

YOUTUBE_URL = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'

# Real yt-dlp output, captured on Windows with Edge running.
COOKIE_DB_LOCKED = (
    'ERROR: ERROR: Could not copy Chrome cookie database. '
    'See  https://github.com/yt-dlp/yt-dlp/issues/7271  for more info'
)
COOKIE_DPAPI = (
    'ERROR: Failed to decrypt with DPAPI. '
    'See  https://github.com/yt-dlp/yt-dlp/issues/10927  for more info'
)
# Captured from live yt-dlp. Note how much cookie wording an age gate contains -
# telling these apart from a cookie *failure* is the whole point of the split.
AGE_GATE = (
    'ERROR: [youtube] Tq92D6wQ1mg: Sign in to confirm your age. This video may be '
    'inappropriate for some users. Use --cookies-from-browser or --cookies for the '
    'authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp'
    '  for how to manually pass cookies. Also see  '
    'https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips '
    'on effectively exporting YouTube cookies'
)
BOT_CHECK = (
    "ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm you're not a bot. "
    'Use --cookies-from-browser or --cookies for the authentication.'
)
NETSCAPE_COOKIES = (
    '# Netscape HTTP Cookie File\n'
    '.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfake-session-value\n'
    '.youtube.com\tTRUE\t/\tTRUE\t2147483647\tPREF\tf6=40000000\n'
)


def make_app():
    """A VideoDownloaderApp with just the attributes the auth helpers need."""
    app = object.__new__(VideoDownloaderApp)
    app.cookies_source = 'none'
    app.cookies_file = ''
    return app


# --------------------------------------------------------------------------- #
#  Which requests get cookies attached                                         #
# --------------------------------------------------------------------------- #
def test_plain_youtube_url_gets_no_cookies():
    """The first attempt must never reach for browser cookies.

    This is the actual bug: an unusable cookie source turned every single
    download into a hard failure before the video was even looked at.
    """
    app = make_app()
    opts = app._apply_auth_opts({}, YOUTUBE_URL)
    assert 'cookiesfrombrowser' not in opts, (
        f"attached browser cookies without a sign-in: {opts['cookiesfrombrowser']}")
    assert 'cookiefile' not in opts


def test_non_youtube_url_gets_no_cookies():
    app = make_app()
    opts = app._apply_auth_opts({}, 'https://vimeo.com/123456')
    assert 'cookiesfrombrowser' not in opts
    assert 'cookiefile' not in opts


def test_signed_in_browser_is_used():
    app = make_app()
    app.cookies_source = 'firefox'
    opts = app._apply_auth_opts({}, YOUTUBE_URL)
    assert opts['cookiesfrombrowser'] == ('firefox',)


def test_cookie_file_is_used():
    app = make_app()
    fd, path = tempfile.mkstemp(suffix='.txt')
    os.close(fd)
    try:
        app.cookies_source = 'file'
        app.cookies_file = path
        opts = app._apply_auth_opts({}, YOUTUBE_URL)
        assert opts['cookiefile'] == path
        assert 'cookiesfrombrowser' not in opts
    finally:
        os.remove(path)


def test_signed_in_cookies_stay_off_other_sites():
    """A YouTube sign-in must not put an unreadable cookie store in the way of
    every other site's downloads."""
    app = make_app()
    app.cookies_source = 'edge'
    opts = app._apply_auth_opts({}, 'https://vimeo.com/123456')
    assert 'cookiesfrombrowser' not in opts


def test_missing_cookie_file_is_not_used():
    app = make_app()
    app.cookies_source = 'file'
    app.cookies_file = os.path.join(tempfile.gettempdir(), 'definitely-not-here.txt')
    opts = app._apply_auth_opts({}, YOUTUBE_URL)
    assert 'cookiefile' not in opts


# --------------------------------------------------------------------------- #
#  Telling "the site wants a login" apart from "we can't read your cookies"    #
# --------------------------------------------------------------------------- #
def test_locked_cookie_db_is_not_an_auth_wall():
    app = make_app()
    assert app._is_auth_error(COOKIE_DB_LOCKED) is False
    assert app._is_cookie_source_error(COOKIE_DB_LOCKED) is True


def test_dpapi_failure_is_not_an_auth_wall():
    app = make_app()
    assert app._is_auth_error(COOKIE_DPAPI) is False
    assert app._is_cookie_source_error(COOKIE_DPAPI) is True


def test_age_gate_is_an_auth_wall():
    app = make_app()
    assert app._is_auth_error(AGE_GATE) is True
    assert app._is_cookie_source_error(AGE_GATE) is False


def test_bot_check_is_an_auth_wall():
    """Mentions --cookies-from-browser, but it is YouTube asking for a login."""
    app = make_app()
    assert app._is_auth_error(BOT_CHECK) is True
    assert app._is_cookie_source_error(BOT_CHECK) is False


def test_unrelated_error_is_neither():
    app = make_app()
    msg = 'ERROR: unable to download video data: HTTP Error 404: Not Found'
    assert app._is_auth_error(msg) is False
    assert app._is_cookie_source_error(msg) is False


# --------------------------------------------------------------------------- #
#  Signing in has to actually restart the download                             #
# --------------------------------------------------------------------------- #
def test_signin_starts_the_download_again():
    """Choosing a working source must retry - not dead-end on an open browser."""
    app = make_app()
    restarted = []
    app._restart_download = restarted.append
    app._verify_cookie_source = lambda source: (True, '')

    started = app._use_signin_source(YOUTUBE_URL, 'firefox')

    assert started is True
    assert restarted == [YOUTUBE_URL], 'sign-in did not retry the download'
    assert app.cookies_source == 'firefox'


def test_unusable_source_does_not_retry():
    """A source we already know is unreadable must not be retried in a loop."""
    app = make_app()
    restarted = []
    problems = []
    app._restart_download = restarted.append
    app._verify_cookie_source = lambda source: (False, 'Edge is open')

    started = app._use_signin_source(YOUTUBE_URL, 'edge', on_problem=problems.append)

    assert started is False
    assert restarted == [], 'retried with a cookie source that cannot be read'
    assert app.cookies_source == 'none', 'kept a broken cookie source'
    assert problems == ['Edge is open']


def test_cookies_txt_with_a_youtube_login_verifies():
    app = make_app()
    fd, path = tempfile.mkstemp(suffix='.txt')
    with os.fdopen(fd, 'w') as f:
        f.write(NETSCAPE_COOKIES)
    try:
        app.cookies_source = 'file'
        app.cookies_file = path
        ok, problem = app._verify_cookie_source('file')
        assert ok is True, problem
    finally:
        os.remove(path)


def test_cookies_txt_without_a_youtube_login_is_rejected():
    """Otherwise the retry fails on the site instead of explaining itself here."""
    app = make_app()
    fd, path = tempfile.mkstemp(suffix='.txt')
    with os.fdopen(fd, 'w') as f:
        f.write('# Netscape HTTP Cookie File\n'
                '.example.com\tTRUE\t/\tFALSE\t2147483647\tfoo\tbar\n')
    try:
        app.cookies_source = 'file'
        app.cookies_file = path
        ok, problem = app._verify_cookie_source('file')
        assert ok is False
        assert 'sign-in' in problem.lower(), problem
    finally:
        os.remove(path)


def test_unreadable_cookies_txt_is_explained():
    app = make_app()
    fd, path = tempfile.mkstemp(suffix='.txt')
    with os.fdopen(fd, 'w') as f:
        f.write('this is not a cookies file\n')
    try:
        app.cookies_source = 'file'
        app.cookies_file = path
        ok, problem = app._verify_cookie_source('file')
        assert ok is False
        assert 'netscape' in problem.lower(), problem
    finally:
        os.remove(path)


def test_non_youtube_auth_error_shows_no_signin_popup():
    """A login wall on another site gets the plain error, not a YouTube popup."""
    app = make_app()
    scheduled = []
    app.after = lambda ms, fn=None, *a: scheduled.append(fn)

    handled = app._route_auth_failure('https://vimeo.com/123456',
                                      'ERROR: login required')

    assert handled is False
    assert scheduled == []


def test_youtube_auth_error_opens_the_popup():
    app = make_app()
    prompts = []
    app.after = lambda ms, fn=None, *a: fn() if fn else None
    app.prompt_signin = lambda url, *a, **kw: prompts.append(url)

    handled = app._route_auth_failure(YOUTUBE_URL, AGE_GATE)

    assert handled is True
    assert prompts == [YOUTUBE_URL]


def test_unreadable_cookie_store_drops_the_source():
    """Otherwise the next plain download fails on the same broken cookies."""
    app = make_app()
    app.cookies_source = 'edge'
    kwargs = []
    app.after = lambda ms, fn=None, *a: fn() if fn else None
    app.prompt_signin = lambda url, *a, **kw: kwargs.append(kw)

    handled = app._route_auth_failure(YOUTUBE_URL, COOKIE_DB_LOCKED)

    assert handled is True
    assert app.cookies_source == 'none'
    assert kwargs[0]['preselect'] == 'edge'
    assert 'Close Edge' in kwargs[0]['cookie_problem'], kwargs[0]['cookie_problem']


def test_cookie_problem_message_explains_locked_browser():
    app = make_app()
    msg = app._cookie_problem_message('edge', COOKIE_DB_LOCKED)
    low = msg.lower()
    assert 'edge' in low
    assert 'clos' in low, f'no "close the browser" advice in: {msg}'


def test_cookie_problem_message_explains_missing_browser():
    app = make_app()
    msg = app._cookie_problem_message('brave', 'ERROR: could not find brave cookies database')
    assert 'brave' in msg.lower()


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
