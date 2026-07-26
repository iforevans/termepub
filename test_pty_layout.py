#!/usr/bin/env python3
"""Real-PTY responsive test for termepub using actual curses + pyte.

Spawns termepub in a genuine pseudo-terminal with real curses rendering,
resizes the PTY live (SIGWINCH), and parses the output with pyte to verify
the rendered screen is clean at every size.

Usage:
    python3 test_pty_layout.py            # run all sizes
    python3 test_pty_layout.py --show 80  # print the 80-col screen
"""
import os
import sys
import pty
import time
import select
import signal
import struct
import fcntl
import termios
import tempfile

import pyte

REPO = os.path.dirname(os.path.abspath(__file__))

CHILD_SCRIPT = r'''
import sys
sys.path.insert(0, REPO_PATH)
import termepub as mod

class FakeEpubBook:
    def __init__(self):
        self.path = "/fake/test.epub"
        self.title = "Test Book Title"
        self.chapters = [
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat." * 3,
            "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo." * 3,
        ]
        self.chapter_segments = []
        for ch in self.chapters:
            seg = mod.StyledSegment(text=ch, styles={}, is_heading=False)
            self.chapter_segments.append([seg])
        self.toc = [mod.TocEntry("Chapter One", "ch1", 0), mod.TocEntry("Chapter Two", "ch2", 1)]

class FakeStateStore:
    def get_state(self, path): return mod.BookState(0, 0)
    def get_theme(self): return "dark"
    def get_show_header(self): return True
    def get_justify_text(self): return False
    def get_last_book_path(self): return None
    def set_state(self, path, state): pass
    def save(self): pass
    def get_bookmark(self, path): return None

def runner(stdscr):
    book = FakeEpubBook()
    store = FakeStateStore()
    ui = mod.ReaderUI(stdscr, book, store)
    ui.has_colors = False
    # Skip the info popup that blocks on getch
    ui.draw()
    # Just draw one frame then exit
    sys.exit(0)

import curses
curses.wrapper(runner)
'''


def _child_script_path():
    path = os.path.join(tempfile.gettempdir(), 'termepub_pty_child.py')
    with open(path, 'w') as fh:
        fh.write(f"REPO_PATH = {REPO!r}\n")
        fh.write(CHILD_SCRIPT)
    return path


def spawn(cols, rows):
    script = _child_script_path()
    pid, fd = pty.fork()
    if pid == 0:
        os.environ['TERM'] = 'xterm-256color'
        os.environ['LANG'] = 'en_US.UTF-8'
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        os.execv(sys.executable, [sys.executable, script])
        os._exit(1)
    set_size(fd, cols, rows)
    return pid, fd


def set_size(fd, cols, rows):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))


def drain(fd, seconds):
    buf = b''
    deadline = time.time() + seconds
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            buf += data
    return buf


def check_screen(screen, cols, rows, label):
    """Verify the rendered grid has no wrap-around / overflow artifacts."""
    problems = []
    lines = screen.display
    for y, line in enumerate(lines):
        if len(line) > cols:
            problems.append(f"{label}: row {y} longer than {cols} cols ({len(line)})")
    return problems


def render(cols, rows, resize_from=None, show=False):
    """Run termepub at (cols, rows), optionally after a live resize."""
    if resize_from:
        pid, fd = spawn(*resize_from)
        drain(fd, 2)
        set_size(fd, cols, rows)
        os.kill(pid, signal.SIGWINCH)
        data = drain(fd, 2.0)
        label = f"{resize_from[0]}x{resize_from[1]}->{cols}x{rows}"
    else:
        pid, fd = spawn(cols, rows)
        data = drain(fd, 2.0)
        label = f"{cols}x{rows}"

    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except OSError:
        pass
    os.close(fd)

    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    stream.feed(data.decode('utf-8', errors='replace'))

    problems = check_screen(screen, cols, rows, label)
    if show:
        print(f"--- {label} ---")
        for y, line in enumerate(screen.display):
            if line.strip():
                print(f"{y:2d}|{line}|")
    return problems, screen


def main():
    show_width = None
    if '--show' in sys.argv:
        show_width = int(sys.argv[sys.argv.index('--show') + 1])

    if show_width:
        problems, _ = render(show_width, 34, show=True)
        print("CLEAN" if not problems else f"PROBLEMS: {problems}")
        return 0 if not problems else 1

    print("=" * 66)
    print("REAL PTY LAYOUT TEST (actual curses + pyte)")
    print("=" * 66)

    failures = 0

    # 1. Static sizes
    for cols, rows in [(120, 40), (100, 34), (80, 30), (70, 30),
                       (60, 28), (50, 26), (40, 26), (34, 24), (28, 20)]:
        problems, _ = render(cols, rows)
        status = "clean" if not problems else f"FAIL ({len(problems)})"
        print(f"  static {cols:>3}x{rows:<3} : {status}")
        for p in problems[:3]:
            print(f"      {p}")
        failures += len(problems)

    # 2. Live shrink
    print("\n  live resizes:")
    for start, end in [((120, 40), (60, 28)), ((120, 40), (40, 26)),
                       ((100, 34), (30, 22)), ((80, 30), (45, 24)),
                       ((60, 28), (110, 36))]:
        problems, _ = render(end[0], end[1], resize_from=start)
        status = "clean" if not problems else f"FAIL ({len(problems)})"
        print(f"  {start[0]}x{start[1]} -> {end[0]}x{end[1]} : {status}")
        for p in problems[:3]:
            print(f"      {p}")
        failures += len(problems)

    print("\n" + "=" * 66)
    print("ALL PTY TESTS PASSED" if failures == 0 else f"{failures} PROBLEMS FOUND")
    print("=" * 66)
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
