import os
import tempfile
import zipfile

import pytest

import termepub


class Screen:
    def __init__(self, height=10, width=21):
        self.height = height
        self.width = width

    def getmaxyx(self):
        return self.height, self.width


class Store:
    def get_theme(self):
        return "dark"

    def get_show_header(self):
        return True

    def get_justify_text(self):
        return False

    def get_state(self, _path):
        return termepub.BookState()

    def set_state(self, *_args):
        pass

    def save(self):
        pass


class Book:
    def __init__(self, text="one two three four five six seven", *, use_css=True):
        self.path = "/tmp/test.epub"
        self.title = "Test"
        self.use_css = use_css
        self.chapters = [text]
        self.chapter_segments = [[termepub.StyledSegment(text, {})]]
        self.toc = [termepub.TocEntry("Chapter", "chapter.xhtml", 0)]
        self.closed = False

    def close(self):
        self.closed = True


def make_ui(text="one two three four five six seven", *, height=10, width=21):
    return termepub.ReaderUI(Screen(height, width), Book(text), Store())


def segment_for_text(segments, needle):
    return next(segment for segment in segments if needle in segment.text)


def test_style_stack_keeps_parent_style_across_unstyled_child():
    parser = termepub.EpubTextExtractor()
    parser.feed('<b>A<span>B</span>C</b>')
    segment = segment_for_text(parser.get_segments(), "ABC")
    assert segment.styles["font_weight"] == "bold"


def test_style_stack_does_not_leak_from_styled_section():
    parser = termepub.EpubTextExtractor()
    parser.feed('<section style="color:red">A</section><p>B</p>')
    segment = segment_for_text(parser.get_segments(), "B")
    assert "color" not in segment.styles


def test_segment_merge_preserves_heading_metadata():
    parser = termepub.EpubTextExtractor()
    parser.feed('<h1>Hello <span>world</span></h1>')
    segment = segment_for_text(parser.get_segments(), "Hello world")
    assert segment.is_heading is True


def test_malformed_nested_heading_does_not_leak_heading_state():
    parser = termepub.EpubTextExtractor()
    parser.feed("<h1><h2>heading</h1>body</h2>")
    text_segments = [segment for segment in parser.get_segments() if segment.text.strip()]
    assert text_segments[0].is_heading is True
    assert text_segments[-1].text == "body"
    assert text_segments[-1].is_heading is False


def test_styled_pagination_is_single_source_of_truth():
    ui = make_ui("x" * 100, height=6, width=21)
    rendered_pages = len(ui._get_styled_pages(0))
    assert ui.total_pages == rendered_pages
    assert ui._get_pages_count(0) == rendered_pages


def test_styled_page_cache_key_includes_height():
    ui = make_ui("word " * 100, height=10, width=21)
    pages_at_ten = len(ui._get_styled_pages(0))
    ui.stdscr.height = 20
    pages_at_twenty = len(ui._get_styled_pages(0))
    assert pages_at_twenty < pages_at_ten


def test_search_matches_phrase_across_rendered_line_break():
    ui = make_ui()
    ui.show_info_popup = lambda *_args, **_kwargs: None
    assert ui.search("four five") is True


def test_search_matches_phrase_across_rendered_page_break():
    ui = make_ui(" ".join(f"word{index}" for index in range(100)), height=6, width=21)
    ui.show_info_popup = lambda *_args, **_kwargs: None
    pages = ui._get_plain_pages(0)
    assert len(pages) > 1
    query = f"{pages[0][-1].split()[-1]} {pages[1][0].split()[0]}"
    assert ui.search(query) is True
    assert ui.page_index == 0


def test_file_picker_jump_uses_filtered_entries():
    picker = object.__new__(termepub.FilePicker)
    picker.entries = [
        ("alpha.epub", "/alpha", False),
        ("beta.epub", "/beta", False),
        ("zeta.epub", "/zeta", False),
    ]
    picker.filtered_entries = [picker.entries[0]]
    picker.selected = 0
    picker.status = ""
    picker.jump_to_letter("z")
    assert picker.selected == 0
    assert "No entries" in picker.status


def test_file_picker_filter_never_leaves_negative_selection():
    picker = object.__new__(termepub.FilePicker)
    picker.entries = [("alpha.epub", "/alpha", False)]
    picker.filtered_entries = []
    picker.filter_text = "missing"
    picker.selected = -1
    picker.apply_filter()
    assert picker.selected == 0
    picker.filter_text = ""
    picker.apply_filter()
    assert picker.selected == 0


def test_state_store_rejects_wrong_json_shapes():
    store = object.__new__(termepub.StateStore)
    store.data = []
    assert store.get_state("/tmp/test") == termepub.BookState()
    assert store.get_theme() == "dark"
    assert store.get_last_book_path() is None

    store.data = {"_global": []}
    assert store.get_theme() == "dark"
    assert store.get_last_book_path() is None


def test_state_load_drops_non_object_entries(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"_global": [], "bad-book": 7, "valid-book": {"page_index": 2}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(termepub, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(termepub, "STATE_FILE", str(state_path))
    store = termepub.StateStore()
    assert store.data == {"valid-book": {"page_index": 2}}


def test_switching_books_preserves_no_css(monkeypatch):
    ui = make_ui()
    ui.book.use_css = False
    ui._save_position = lambda: None
    ui.show_info_popup = lambda *_args, **_kwargs: None

    monkeypatch.setattr(termepub.FilePicker, "run", lambda _self: "/tmp/new.epub")
    captured = {}

    class ReplacementBook(Book):
        def __init__(self, path, use_css=True):
            super().__init__(use_css=use_css)
            self.path = path
            captured["use_css"] = use_css

    monkeypatch.setattr(termepub, "EpubBook", ReplacementBook)
    ui.open_file_picker()
    assert captured["use_css"] is False


def test_empty_spine_is_rejected_before_reader_starts():
    container = '''<?xml version="1.0"?>
    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
    </container>'''
    package = '''<?xml version="1.0"?>
    <package xmlns="http://www.idpf.org/2007/opf">
      <metadata/><manifest/><spine/>
    </package>'''

    fd, path = tempfile.mkstemp(suffix=".epub")
    os.close(fd)
    try:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/container.xml", container)
            archive.writestr("OEBPS/content.opf", package)
        with pytest.raises(ValueError, match="spine|chapter"):
            termepub.EpubBook(path)
    finally:
        os.unlink(path)


def test_dictionary_candidate_limit_caps_examined_words(monkeypatch):
    class CountingWords:
        def __init__(self):
            self.examined = 0

        def __bool__(self):
            return True

        def __contains__(self, _word):
            return False

        def __iter__(self):
            for index in range(20_000):
                self.examined += 1
                yield f"word{index:05d}"

    words = CountingWords()
    monkeypatch.setattr(termepub, "load_ecdict_index", lambda: None)
    monkeypatch.setattr(termepub, "load_word_set", lambda: words)
    termepub.lookup_word("zzzzzzzzz")
    assert words.examined <= 5_001


class InteractiveScreen(Screen):
    def __init__(self, keys, height=10, width=40):
        super().__init__(height, width)
        self.keys = iter(keys)
        self.nodelay_calls = []
        self.current_writes = []
        self.frames = []

    def nodelay(self, enabled):
        self.nodelay_calls.append(enabled)

    def getch(self):
        return next(self.keys)

    def erase(self):
        self.current_writes = []

    def refresh(self):
        self.frames.append(list(self.current_writes))

    def addnstr(self, _y, _x, text, *_args):
        self.current_writes.append(text)

    def bkgd(self, *_args):
        pass


def test_toc_temporarily_uses_blocking_input():
    screen = InteractiveScreen([ord("q")])
    ui = termepub.ReaderUI(screen, Book(), Store())
    ui._draw_toc = lambda *_args: None
    ui.open_toc()
    assert screen.nodelay_calls == [False, True]


def test_popup_scrolls_instead_of_truncating():
    screen = InteractiveScreen([termepub.curses.KEY_DOWN, ord("q")], height=8, width=30)
    ui = termepub.ReaderUI(screen, Book(), Store())
    ui.setup_colors = lambda: None
    ui.has_colors = False
    ui.show_info_popup("Info", "line1\nline2\nline3\nline4\nline5")
    assert len(screen.frames) == 2
    assert screen.frames[0] != screen.frames[1]
    assert screen.nodelay_calls[-2:] == [False, True]


def test_main_loop_does_not_redraw_while_idle(monkeypatch):
    class IdleScreen(Screen):
        def __init__(self):
            super().__init__(30, 80)
            self.keys = iter([-1, -1, ord("q")])

        def keypad(self, _enabled):
            pass

        def nodelay(self, _enabled):
            pass

        def getch(self):
            return next(self.keys)

    screen = IdleScreen()
    ui = termepub.ReaderUI(screen, Book(), Store())
    ui.setup_colors = lambda: None
    ui.apply_theme = lambda: None
    ui.show_info_popup = lambda *_args, **_kwargs: None
    ui._true_terminal_size = lambda: screen.getmaxyx()

    draw_calls = []
    sleep_calls = []
    ui.draw = lambda: draw_calls.append(True)
    monkeypatch.setattr(termepub.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(termepub.curses, "curs_set", lambda *_args: None)
    monkeypatch.setattr(termepub.time, "sleep", sleep_calls.append)

    ui.run()

    assert len(draw_calls) == 1
    assert sleep_calls == [0.1, 0.1]


def test_epub_text_member_size_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(termepub, "MAX_EPUB_TEXT_MEMBER_SIZE", 32)
    fd, path = tempfile.mkstemp(suffix=".epub")
    os.close(fd)
    try:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/container.xml", "x" * 33)
        with pytest.raises(ValueError, match="too large"):
            termepub.EpubBook(path)
    finally:
        os.unlink(path)


def test_epub_total_decompressed_text_limit_is_enforced(monkeypatch, tmp_path):
    path = tmp_path / "aggregate.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.xhtml", "a" * 30)
        archive.writestr("b.xhtml", "b" * 30)

    monkeypatch.setattr(termepub, "MAX_EPUB_TEXT_MEMBER_SIZE", 100)
    monkeypatch.setattr(termepub, "MAX_EPUB_TOTAL_TEXT_SIZE", 50)
    book = object.__new__(termepub.EpubBook)
    book.zf = zipfile.ZipFile(path)
    book._text_bytes_read = 0
    book._counted_members = set()
    try:
        assert len(book._read_member("a.xhtml")) == 30
        assert len(book._read_member("a.xhtml")) == 30
        assert book._text_bytes_read == 30
        with pytest.raises(ValueError, match="too much decompressed text"):
            book._read_member("b.xhtml")
    finally:
        book.close()


def test_epub_archive_member_count_limit_is_enforced(monkeypatch, tmp_path):
    path = tmp_path / "many-members.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one", "1")
        archive.writestr("two", "2")
    monkeypatch.setattr(termepub, "MAX_EPUB_MEMBERS", 1)
    with pytest.raises(ValueError, match="too many files"):
        termepub.EpubBook(path)


def test_epub_suspicious_compression_ratio_is_rejected(monkeypatch, tmp_path):
    path = tmp_path / "compressed.epub"
    payload = b"x" * (1024 * 1024 + 1)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.xhtml", payload)

    monkeypatch.setattr(termepub, "MAX_EPUB_COMPRESSION_RATIO", 10)
    book = object.__new__(termepub.EpubBook)
    book.zf = zipfile.ZipFile(path)
    book._text_bytes_read = 0
    book._counted_members = set()
    try:
        with pytest.raises(ValueError, match="compression ratio"):
            book._read_member("bomb.xhtml")
    finally:
        book.close()
