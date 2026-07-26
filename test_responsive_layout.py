#!/usr/bin/env python3
"""MockStdscr-based responsive layout test for termepub.

Renders the ReaderUI and FilePicker at many terminal sizes and asserts no
write lands outside the terminal grid (the wrap-around overflow bug).

Usage:
    python3 test_responsive_layout.py [--render 80,50,30]
"""
import sys
import os

# --- Mock curses ---
class FakeCurses:
    A_NORMAL = 0
    A_REVERSE = 0x100000
    A_BOLD = 0x200000
    A_ITALIC = 0x400000
    A_DIM = 0x800000
    A_UNDERLINE = 0x01000000
    A_STANDOUT = 0x02000000
    A_PROTECT = 0x04000000
    A_INVIS = 0x08000000
    A_LEFT = 0x10000000
    A_RIGHT = 0x20000000
    A_ALTCHARSET = 0x40000000
    COLOR_WHITE = 0
    COLOR_GREEN = 1
    COLOR_YELLOW = 2
    COLOR_CYAN = 3
    COLOR_MAGENTA = 4
    COLOR_BLUE = 5
    COLOR_RED = 6
    KEY_RESIZE = 0x161
    KEY_LEFT = 0x108
    KEY_RIGHT = 0x105
    KEY_UP = 0x107
    KEY_DOWN = 0x106
    KEY_NPAGE = 0x109
    KEY_PPAGE = 0x10a
    KEY_ENTER = 0x10b
    KEY_BACKSPACE = 0x10c
    error = type('error', (Exception,), {})

    @staticmethod
    def color_pair(n):
        return n << 8

    @staticmethod
    def init_pair(*a):
        pass

    @staticmethod
    def start_color():
        pass

    @staticmethod
    def use_default_colors():
        pass

    @staticmethod
    def cbreak():
        pass

    @staticmethod
    def nocbreak():
        pass

    @staticmethod
    def echo():
        pass

    @staticmethod
    def noecho():
        pass

    @staticmethod
    def curs_set(n):
        pass

    @staticmethod
    def resizeterm(h, w):
        pass

    @staticmethod
    def update_lines_cols():
        pass

    @staticmethod
    def wrapper(func, stdscr=None):
        if stdscr is None:
            stdscr = MockStdscr(30, 80)
        func(stdscr)

    @staticmethod
    def inchstr(y, x):
        return ""

    @staticmethod
    def has_colors():
        return True


class MockStdscr:
    """Records every write into a grid and flags out-of-bounds writes."""

    def __init__(self, h, w):
        self._h, self._w = h, w
        self._grid = {}
        self._current_attr = 0
        self.overflow_x = []
        self.overflow_y = []

    def getmaxyx(self):
        return (self._h, self._w)

    def _write(self, y, x, text, attr):
        if y < 0 or y >= self._h:
            self.overflow_y.append((y, x, text))
            return
        for i, ch in enumerate(text):
            col = x + i
            if col < 0 or col >= self._w:
                self.overflow_x.append((y, col, ch))
                continue
            self._grid[(y, col)] = ch

    def addstr(self, y, x, *args):
        attr = self._current_attr
        if len(args) == 1:
            text = args[0]
        elif len(args) == 2:
            text, attr = args
        else:
            text = args[0]
        if isinstance(text, int):
            text = chr(text)
        self._write(y, x, text, attr)

    def addnstr(self, y, x, text, n, attr=None):
        self._write(y, x, text[:n], attr if attr is not None else self._current_attr)

    def addch(self, y, x, ch, attr=0):
        self._write(y, x, chr(ch) if isinstance(ch, int) else ch, attr)

    def attron(self, a):
        self._current_attr |= a

    def attroff(self, a):
        self._current_attr &= ~a

    def attrset(self, a):
        self._current_attr = a

    def bkgd(self, ch, attr=0):
        for y in range(self._h):
            for x in range(self._w):
                self._grid[(y, x)] = ch if isinstance(ch, str) else chr(ch)

    def erase(self):
        self._grid = {}

    def clear(self):
        self._grid = {}

    def refresh(self):
        pass

    def nodelay(self, f):
        pass

    def timeout(self, ms):
        pass

    def getch(self):
        return -1

    def getstr(self, y, x, n):
        return b""

    def keypad(self, f):
        pass

    def move(self, y, x):
        pass

    def clrtoeol(self):
        pass

    def lines(self):
        return [
            "".join(self._grid.get((y, x), ' ') for x in range(self._w))
            for y in range(self._h)
        ]

    def render(self):
        return '\n'.join(self.lines())

    def has_overflow(self):
        return len(self.overflow_x) > 0 or len(self.overflow_y) > 0


def main():
    # Mock curses before importing termepub
    sys.modules['curses'] = FakeCurses

    # Import termepub
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'termepub.py')
    if not os.path.isfile(target):
        print(f"ERROR: termepub.py not found at {target}")
        return 2

    import importlib.util
    module_name = 'termepub'
    spec = importlib.util.spec_from_file_location(module_name, target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)

    fake_curses = sys.modules['curses']

    # Create minimal mock EpubBook
    class FakeEpubBook:
        def __init__(self):
            self.path = "/fake/test.epub"
            self.title = "Test Book Title"
            # Long chapter text to exercise wrapping at all widths
            self.chapters = [
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
                * 3,
                "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt."
                * 3,
            ]
            self.chapter_segments = []
            for ch in self.chapters:
                StyledSegment = mod.StyledSegment
                seg = StyledSegment(text=ch, styles={}, is_heading=False)
                self.chapter_segments.append([seg])
            self.toc = [mod.TocEntry("Chapter One", "ch1", 0), mod.TocEntry("Chapter Two", "ch2", 1)]

    class FakeStateStore:
        def __init__(self):
            pass
        def get_state(self, path):
            return mod.BookState(0, 0)
        def get_theme(self):
            return "dark"
        def get_show_header(self):
            return True
        def get_justify_text(self):
            return False
        def get_last_book_path(self):
            return None
        def set_state(self, path, state):
            pass
        def save(self):
            pass
        def get_bookmark(self, path):
            return None

    render_widths = set()
    for arg in sys.argv[1:]:
        if arg.startswith('--render'):
            vals = arg.split('=', 1)[1] if '=' in arg else sys.argv[sys.argv.index(arg) + 1]
            render_widths = {int(v) for v in vals.split(',')}

    print("=" * 72)
    print(f"RESPONSIVE LAYOUT TEST: termepub")
    print("=" * 72)

    failures = 0
    checks = 0

    # --- Test ReaderUI.draw() at every width 20..160 ---
    for height in (10, 15, 24, 30, 45):
        for width in range(20, 161):
            mock = MockStdscr(height, width)
            curses_mod = sys.modules['curses']
            book = FakeEpubBook()
            store = FakeStateStore()
            ui = mod.ReaderUI(mock, book, store)
            ui.has_colors = False

            # Prevent the info popup from blocking on getch
            # (show_info_popup is called from load_book -> run, but we call draw directly)
            try:
                ui.draw()
            except Exception as e:
                import traceback
                failures += 1
                if width <= 40 or height <= 15:
                    print(f"\nEXCEPT [{width}x{height}]: {type(e).__name__}: {e}")
                continue

            checks += 1
            problems = []
            for (y, x, ch) in mock.overflow_x[:4]:
                problems.append(f"X-OVERFLOW row {y} col {x} char {ch!r} (width {width})")
            for (y, x, t) in mock.overflow_y[:4]:
                problems.append(f"Y-OVERFLOW row {y} (height {height}) text {t[:30]!r}")

            if problems:
                failures += 1
                print(f"\nFAIL [{width}x{height}]:")
                for p in problems[:4]:
                    print(f"   {p}")

    print(f"\nSwept {checks} render configurations.")
    print(f"Failures: {failures}")

    # --- Visual renders for eyeballing ---
    for w in sorted(render_widths):
        mock = MockStdscr(30, w)
        book = FakeEpubBook()
        store = FakeStateStore()
        ui = mod.ReaderUI(mock, book, store)
        ui.has_colors = False
        try:
            ui.draw()
        except Exception:
            pass
        problems = mock.overflow_x + mock.overflow_y
        print("\n" + "=" * 72)
        print(f"RENDER {w} cols  ({'clean' if not problems else 'OVERFLOW'})")
        print("=" * 72)
        for y, line in enumerate(mock.lines()):
            if line.strip():
                print(f"{y:2d}|{line}|")

    # --- Test FilePicker ---
    print("\n" + "=" * 72)
    print("TESTING FilePicker.draw()")
    print("=" * 72)
    fp_failures = 0
    fp_checks = 0
    for height in (10, 15, 24, 30):
        for width in range(20, 161):
            mock = MockStdscr(height, width)
            picker = mod.FilePicker(mock, "/tmp")
            try:
                picker.draw()
            except Exception as exc:
                fp_failures += 1
                if width <= 50:
                    print(f"\nEXCEPT Picker [{width}x{height}]: {type(exc).__name__}: {exc}")
                continue
            fp_checks += 1
            if mock.has_overflow():
                fp_failures += 1
                if width <= 50:
                    print(f"\nFAIL Picker [{width}x{height}]:")
                    for (y, x, ch) in mock.overflow_x[:3]:
                        print(f"   X-OVERFLOW row {y} col {x}")
                    for (y, x, t) in mock.overflow_y[:3]:
                        print(f"   Y-OVERFLOW row {y}")

    print(f"Picker: {fp_checks} checks, {fp_failures} failures")

    total_failures = failures + fp_failures
    print("\n" + "=" * 72)
    print("ALL TESTS PASSED" if total_failures == 0 else f"{total_failures} TOTAL FAILURES")
    print("=" * 72)
    return 0 if total_failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
