#!/usr/bin/env python3
"""
termepub.py - Terminal-based EPUB reader with inline CSS styling support.

Features:
- Read EPUB files in the terminal using curses
- Inline CSS styling (bold, underline, italic, colors)
- Chapter navigation, bookmarks, file picker with live search
- State persistence across sessions
- Proper word wrapping (no mid-word breaks)
- Justified text mode toggle (j key)
- Word selection mode for dictionary lookup (d key + arrow keys)

Version: 1.0.3
"""
import curses
import fcntl
import functools
import hashlib
import html
import io
import json
import os
import re
import signal
import struct
import sys
import textwrap
import termios
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

__version__ = "1.0.3"

_DEBUG = os.environ.get("TERMEPUB_DEBUG", "").lower() in ("1", "true", "yes")

# Dictionary configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DICT_DIR = os.path.join(os.path.expanduser("~"), ".config", "termepub")
WORD_LIST_PATH = os.path.join(DICT_DIR, "words.txt")
EC_DICT_INDEX_PATH = os.path.join(DICT_DIR, "ecdict_index.json")
_ecdict_index = None
_word_set: Optional[set] = None

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "termepub")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")

# Footer format string for status bar display (simplified - just position info)
FOOTER_FORMAT = "Chapter {}/{} | Page {}/{} | {}% | h=help"
FOOTER_FORMAT_SELECTION = (
    " SELECTION MODE - Arrow keys to navigate, Enter to lookup, Esc to cancel "
)

# Keyboard key codes (fallback values where curses.KEY_* is platform-dependent)
KEY_ESCAPE = 27
KEY_ENTER = 13
KEY_LF = 10
KEY_BACKSPACE_ALT = 127
KEY_BACKSPACE_CTRL = 8
KEY_PAGE_DOWN_TERMINFO = 338
KEY_PAGE_UP_TERMINFO = 339

# Curses color pair assignments
COLOR_PAIR_DEFAULT = 1       # White on black (dark) / black on white (light)
COLOR_PAIR_INVERSE = 2       # Opposite of default
COLOR_PAIR_TITLE = 3         # Yellow on default (headings)
COLOR_PAIR_INFO_POPUP = 6    # White on blue
COLOR_PAIR_ERROR_POPUP = 7   # White on red
FIRST_DYNAMIC_COLOR_PAIR = 8 # Starting pair for dynamic text colors

# Defensive limits for untrusted EPUB archives. EPUB text documents should
# normally be small; these bounds prevent compressed members exhausting RAM.
MAX_EPUB_MEMBERS = 10_000
MAX_EPUB_TEXT_MEMBER_SIZE = 25 * 1024 * 1024
MAX_EPUB_TOTAL_TEXT_SIZE = 100 * 1024 * 1024
MAX_EPUB_COMPRESSION_RATIO = 1_000

# CSS named colors mapping (common ones) - module-level to avoid per-call allocation
_NAMED_COLORS: dict = {
    'black': (0, 0, 0),
    'white': (255, 255, 255),
    'red': (255, 0, 0),
    'green': (0, 128, 0),
    'blue': (0, 0, 255),
    'yellow': (255, 255, 0),
    'cyan': (0, 255, 255),
    'magenta': (255, 0, 255),
    'purple': (128, 0, 128),
    'orange': (255, 165, 0),
    'gray': (128, 128, 128),
    'grey': (128, 128, 128),
    'silver': (192, 192, 192),
    'pink': (255, 192, 203),
    'brown': (165, 42, 42),
    'navy': (0, 0, 128),
    'teal': (0, 128, 128),
    'olive': (128, 128, 0),
    'maroon': (128, 0, 0),
    'lime': (0, 255, 0),
    'aqua': (0, 255, 255),
    'fuchsia': (255, 0, 255),
}

# 16-color ANSI palette for color matching - module-level to avoid per-call allocation
_ANSI_COLORS = [
    (0, 0, 0),       # 0: black
    (170, 0, 0),     # 1: red
    (0, 170, 0),     # 2: green
    (170, 170, 0),   # 3: yellow
    (0, 0, 170),     # 4: blue
    (170, 0, 170),   # 5: magenta
    (0, 170, 170),   # 6: cyan
    (170, 170, 170), # 7: white
    (85, 85, 85),    # 8: bright black (gray)
    (255, 85, 85),   # 9: bright red
    (85, 255, 85),   # 10: bright green
    (255, 255, 85),  # 11: bright yellow
    (85, 85, 255),   # 12: bright blue
    (255, 85, 255),  # 13: bright magenta
    (85, 255, 255),  # 14: bright cyan
    (255, 255, 255), # 15: bright white
]


@dataclass
class TocEntry:
    title: str
    href: str
    spine_index: int


@dataclass
class BookState:
    chapter_index: int = 0
    page_index: int = 0


@dataclass
class StyledSegment:
    """A text segment with associated CSS styles.

    Each segment represents a contiguous run of text with the same styling.
    Segments are created during HTML parsing and merged when adjacent segments
    have identical styles for efficiency.
    """
    text: str
    styles: dict  # {'font_weight': 'bold', 'color': '#ff0000', ...}
    is_heading: bool = False


def _log_curses_error(tag: str, line: int, col: int):
    if _DEBUG:
        import sys
        print(f"curses.error at ({line}, {col}) in {tag}", file=sys.stderr)


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def norm_href(base_path: str, href: str) -> str:
    clean = href.split("#", 1)[0]
    if not base_path:
        return os.path.normpath(clean)
    return os.path.normpath(os.path.join(os.path.dirname(base_path), clean))


# str.translate table for single-char ASCII replacements (fast path)
_ASCII_TRANSLATE_TABLE = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u00a0": " ",
    "\u00ad": "",
    "\u2191": "^",
    "\u2193": "v",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2039": "<",
    "\u203a": ">",
    "\u2500": "-",
    "\u2502": "|",
    "\u2514": "+",
    "\u251c": "+",
    "\u2524": "+",
    "\u2534": "+",
    "\u253c": "+",
    "\u2550": "=",
})


def ascii_sanitize(text: str) -> str:
    """Convert special characters to ASCII equivalents for terminal compatibility."""
    text = text.translate(_ASCII_TRANSLATE_TABLE)
    text = text.replace("\u2014", "--")
    text = text.replace("\u2026", "...")
    text = text.replace("\u2190", "<-")
    text = text.replace("\u2192", "->")
    text = text.replace("\u2015", "---")
    text = text.replace("\u2551", "||")
    text = text.replace("\u2588", "##")
    text = text.replace("\u2591", "::")
    text = text.replace("\u2592", "::")
    text = text.replace("\u2593", "##")
    text = unicodedata.normalize("NFKC", text)
    # Keep only ASCII characters and whitespace (mapped to space).
    return ''.join(
        c if ord(c) < 128 else (' ' if c.isspace() else '')
        for c in text
    )


def parse_inline_style(style_attr: str) -> dict:
    """Parse inline style attribute into a dict of CSS properties.
    
    Example: 'font-weight: bold; color: #ff0000; text-align: center'
    Returns: {'font_weight': 'bold', 'color': '#ff0000', 'text-align': 'center'}
    
    Args:
        style_attr: CSS style string from HTML style="" attribute.
    
    Returns:
        Dictionary with CSS properties as keys (with - replaced by _).
    
    Note:
        Does not validate CSS syntax - malformed values are passed through.
        Empty or invalid style strings return empty dict.
    """
    if not style_attr:
        return {}
    styles = {}
    try:
        for prop in style_attr.split(';'):
            if ':' in prop:
                key, value = prop.split(':', 1)
                key = key.strip().replace('-', '_')
                value = value.strip()
                if key and value:
                    styles[key] = value
    except Exception:
        # If parsing fails for any reason, return empty dict
        # This prevents malformed CSS from crashing the reader
        pass
    return styles


@functools.lru_cache(maxsize=256)
def hex_to_16_color(hex_color: str) -> Optional[int]:
    """Convert a hex color to the nearest 16-color ANSI palette.
    
    Maps hex colors (e.g., '#ff0000', 'rgb(255,0,0)'), named colors (e.g., 'red'),
    to curses.COLOR_* constants.
    
    Args:
        hex_color: Color in hex format (#rrggbb, #rgb, rrggbb), rgb(r,g,b),
                   or a CSS named color (e.g., 'red', 'blue', 'purple').
    
    Returns:
        ANSI color index (0-15) for the closest matching color, or None if
        the color cannot be parsed.
    
    Note:
        Uses Euclidean distance in RGB space to find the closest color.
        The 16-color palette includes standard colors plus bright variants.
    """
    hex_color = hex_color.strip().lower()

    # Check if it's a named color
    if hex_color in _NAMED_COLORS:
        r, g, b = _NAMED_COLORS[hex_color]
    # Handle rgb() format
    elif rgb_match := re.search(r'rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', hex_color):
        r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
    else:
        # Handle hex format (#rrggbb, #rgb, or rrggbb)
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join(c*2 for c in hex_color)
        if len(hex_color) == 6:
            try:
                r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            except ValueError:
                return None
        else:
            return None

    # Find closest color by Euclidean distance
    min_dist = float('inf')
    closest_idx = 0

    for idx, (ar, ag, ab) in enumerate(_ANSI_COLORS):
        dist = (r - ar) ** 2 + (g - ag) ** 2 + (b - ab) ** 2
        if dist < min_dist:
            min_dist = dist
            closest_idx = idx
    
    return closest_idx


class EpubTextExtractor(HTMLParser):
    """HTML parser that extracts text with inline CSS styling information."""
    BLOCK_TAGS = {
        "p", "div", "section", "article", "aside", "blockquote", "pre",
        "ul", "ol", "li", "dl", "dt", "dd", "table", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr"
    }
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, use_css: bool = True):
        super().__init__(convert_charrefs=True)
        self.use_css = use_css
        self.segments: List[StyledSegment] = []
        self.pre_depth = 0
        self.list_depth = 0
        self.skip_depth = 0
        self.heading_depth = 0  # Track nesting inside h1-h6 tags
        # Every non-void tag gets a frame, including tags with no styles. This
        # prevents an unstyled child from accidentally popping a styled parent.
        self.style_stack: List[Tuple[Optional[str], dict]] = [(None, {})]

    def _get_current_styles(self) -> dict:
        """Get current inherited styles by merging the style stack.
        
        Includes runtime validation to catch style stack discipline errors
        (e.g., mismatched start/end tags causing underflow).
        """
        if not self.style_stack:
            raise RuntimeError(
                "Style stack underflow: attempted to get styles with empty stack. "
                "This indicates a bug in tag handling (e.g., extra endtag without starttag)."
            )
        merged = {}
        for _tag, style_dict in self.style_stack:
            merged.update(style_dict)
        return merged

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "head"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        # Extract inline styles from this tag
        tag_styles = {}
        if self.use_css and 'style' in attrs_dict:
            tag_styles = parse_inline_style(attrs_dict['style'])

        # Add semantic styles from tag type (e.g., <b> means bold)
        if self.use_css:
            if tag in {"b", "strong"}:
                tag_styles['font_weight'] = 'bold'
            elif tag in {"i", "em"}:
                tag_styles['font_style'] = 'italic'
            elif tag == "u":
                tag_styles['text_decoration'] = 'underline'
            elif tag in {"s", "strike", "del"}:
                tag_styles['text_decoration'] = 'line-through'

        if tag not in self.VOID_TAGS:
            self.style_stack.append((tag, tag_styles))

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_depth += 1
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag == "pre":
            self.pre_depth += 1
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag in {"ul", "ol"}:
            self.list_depth += 1
            self.segments.append(StyledSegment("\n", self._get_current_styles().copy()))
        elif tag == "li":
            indent = "  " * max(0, self.list_depth - 1)
            self.segments.append(StyledSegment(indent + "- ", self._get_current_styles().copy()))
        elif tag == "blockquote":
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag == "img":
            alt = (attrs_dict.get("alt") or "").strip()
            if alt:
                self.segments.append(StyledSegment(f"[Image: {alt}]", self._get_current_styles().copy()))
        elif tag == "br":
            self.segments.append(StyledSegment("\n", self._get_current_styles().copy()))
        elif tag in {"p", "div", "section", "article"}:
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag in self.BLOCK_TAGS:
            self.segments.append(StyledSegment("\n", self._get_current_styles().copy()))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.skip_depth > 0:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return

        # Pop this tag's frame. For malformed nesting, discard unmatched child
        # frames until the requested tag is reached, preserving the root frame.
        matching_index = None
        for index in range(len(self.style_stack) - 1, 0, -1):
            if self.style_stack[index][0] == tag:
                matching_index = index
                break
        removed_tags = []
        if matching_index is not None:
            removed_tags = [frame_tag for frame_tag, _styles in self.style_stack[matching_index:]]
            del self.style_stack[matching_index:]

        # Keep structural depth counters aligned with every frame discarded,
        # including malformed HTML such as an outer tag closing first.
        self.pre_depth = max(0, self.pre_depth - removed_tags.count("pre"))
        self.list_depth = max(
            0,
            self.list_depth - sum(name in {"ul", "ol"} for name in removed_tags),
        )
        self.heading_depth = max(
            0,
            self.heading_depth - sum(
                name in {"h1", "h2", "h3", "h4", "h5", "h6"}
                for name in removed_tags
            ),
        )

        if tag == "pre":
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag in {"ul", "ol"}:
            self.segments.append(StyledSegment("\n", self._get_current_styles().copy()))
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag == "blockquote":
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag in {"p", "div", "section", "article"}:
            self.segments.append(StyledSegment("\n\n", self._get_current_styles().copy()))
        elif tag in self.BLOCK_TAGS:
            self.segments.append(StyledSegment("\n", self._get_current_styles().copy()))

    def handle_data(self, data):
        if not data or self.skip_depth:
            return

        # Clean the text based on context
        if self.pre_depth:
            clean_text = ascii_sanitize(data)
        else:
            clean_text = re.sub(r"\s+", " ", data)
            clean_text = ascii_sanitize(clean_text)

        if not clean_text.strip():
            return

        # Create segment with current inherited styles
        segment = StyledSegment(clean_text, self._get_current_styles().copy(), is_heading=bool(self.heading_depth))
        self.segments.append(segment)

    def _merge_adjacent_segments(self, segments: List[StyledSegment]) -> List[StyledSegment]:
        """Merge adjacent segments with identical styles for efficiency.
        
        Does NOT merge across paragraph breaks (whitespace-only segments).
        This preserves paragraph structure while reducing the number of
        segments we need to process during rendering.
        
        Args:
            segments: List of styled segments to merge.
        
        Returns:
            List of segments with identical adjacent segments combined.
        """
        if not segments:
            return segments

        merged = [segments[0]]
        for seg in segments[1:]:
            last = merged[-1]
            # Don't merge across paragraph breaks (whitespace-only segments)
            if last.text.strip() == '' or seg.text.strip() == '':
                merged.append(seg)
            elif last.styles == seg.styles and last.is_heading == seg.is_heading:
                # Merge: concatenate text, keep same styles
                merged[-1] = StyledSegment(
                    last.text + seg.text,
                    last.styles,
                    is_heading=last.is_heading,
                )
            else:
                merged.append(seg)
        return merged

    def get_segments(self) -> List[StyledSegment]:
        """Return styled text segments, merged where possible.
        
        Preserves paragraph breaks (segments that are only whitespace).
        """
        # Filter out truly empty segments (zero length), but keep whitespace-only ones
        # as they serve as paragraph breaks
        non_empty = [s for s in self.segments if s.text]
        return self._merge_adjacent_segments(non_empty)

    def get_text(self) -> str:
        """Return plain text (for backward compatibility with search, etc.)."""
        segments = self.get_segments()
        return ''.join(seg.text for seg in segments)


class EpubBook:
    def __init__(self, path: str, use_css: bool = True):
        self.path = os.path.abspath(path)
        self.use_css = use_css
        self.zf = zipfile.ZipFile(path)
        if len(self.zf.infolist()) > MAX_EPUB_MEMBERS:
            raise ValueError(f"EPUB contains too many files (limit {MAX_EPUB_MEMBERS})")
        self._text_bytes_read = 0
        self._counted_members = set()
        self.title = os.path.basename(path)
        self.author = "Unknown"
        self.rootfile = self._find_rootfile()
        self.manifest: Dict[str, Dict[str, str]] = {}
        self.spine: List[str] = []
        self.spine_hrefs: List[str] = []
        self.chapter_titles: List[str] = []
        self.chapters: List[str] = []
        self.chapter_segments: List[List[StyledSegment]] = []  # Styled segments per chapter
        self.toc: List[TocEntry] = []
        self._parse_package()
        self._load_toc()       # Load TOC FIRST
        self._load_chapters()  # Then load chapters (can use TOC titles)
        self._fill_missing_toc_entries()
        if not self.chapters:
            raise ValueError("EPUB contains no readable spine chapters")

    def close(self):
        """Close the underlying ZipFile to release the file handle."""
        zf = getattr(self, 'zf', None)
        if zf is not None:
            try:
                zf.close()
            except Exception:
                pass
            object.__setattr__(self, 'zf', None)

    def __del__(self):
        """Ensure ZipFile is closed when the book is garbage collected."""
        try:
            self.close()
        except Exception:
            pass

    def _read_member(self, member: str) -> bytes:
        """Read a bounded text member, rejecting suspicious archive entries."""
        try:
            info = self.zf.getinfo(member)
        except KeyError:
            raise
        if info.is_dir():
            raise ValueError(f"EPUB member is a directory: {member}")
        if info.file_size > MAX_EPUB_TEXT_MEMBER_SIZE:
            raise ValueError(f"EPUB text member is too large: {member}")
        if info.compress_size == 0:
            ratio = float("inf") if info.file_size else 1
        else:
            ratio = info.file_size / info.compress_size
        if info.file_size > 1024 * 1024 and ratio > MAX_EPUB_COMPRESSION_RATIO:
            raise ValueError(f"Suspicious EPUB compression ratio: {member}")

        with self.zf.open(info) as source:
            data = source.read(MAX_EPUB_TEXT_MEMBER_SIZE + 1)
        if len(data) > MAX_EPUB_TEXT_MEMBER_SIZE:
            raise ValueError(f"EPUB text member is too large: {member}")

        if member not in self._counted_members:
            projected_total = self._text_bytes_read + len(data)
            if projected_total > MAX_EPUB_TOTAL_TEXT_SIZE:
                raise ValueError("EPUB contains too much decompressed text")
            self._text_bytes_read = projected_total
            self._counted_members.add(member)
        return data

    def _read_xml(self, member: str) -> ET.Element:
        data = self._read_member(member)
        return ET.fromstring(data)

    def _find_rootfile(self) -> str:
        root = ET.fromstring(self._read_member("META-INF/container.xml"))
        for elem in root.iter():
            if strip_ns(elem.tag) == "rootfile":
                full_path = elem.attrib.get("full-path")
                if full_path:
                    return full_path
        raise ValueError("Could not locate OPF rootfile")

    def _parse_package(self):
        root = self._read_xml(self.rootfile)
        metadata = manifest = spine = None
        for child in root:
            name = strip_ns(child.tag)
            if name == "metadata":
                metadata = child
            elif name == "manifest":
                manifest = child
            elif name == "spine":
                spine = child

        if metadata is not None:
            for elem in metadata.iter():
                name = strip_ns(elem.tag)
                if name == "title" and elem.text:
                    self.title = ascii_sanitize(elem.text.strip())
                elif name == "creator" and elem.text:
                    self.author = ascii_sanitize(elem.text.strip())

        if manifest is None or spine is None:
            raise ValueError("Malformed EPUB package")

        for item in manifest:
            if strip_ns(item.tag) != "item":
                continue
            item_id = item.attrib.get("id")
            if not item_id:
                continue
            self.manifest[item_id] = {
                "href": norm_href(self.rootfile, item.attrib.get("href", "")),
                "media_type": item.attrib.get("media-type", ""),
                "properties": item.attrib.get("properties", ""),
            }

        for itemref in spine:
            if strip_ns(itemref.tag) != "itemref":
                continue
            idref = itemref.attrib.get("idref")
            if idref and idref in self.manifest:
                self.spine.append(idref)
                self.spine_hrefs.append(self.manifest[idref]["href"])

    def _load_chapters(self):
        for idx, idref in enumerate(self.spine):
            href = self.manifest[idref]["href"]
            try:
                raw = self._read_member(href).decode("utf-8", errors="replace")
            except KeyError:
                self.chapters.append("[Missing chapter content]\n")
                self.chapter_segments.append([])
                self.chapter_titles.append("Chapter %d" % (idx + 1))
                continue
            
            # Use the new styled segment extractor
            extractor = EpubTextExtractor(use_css=self.use_css)
            extractor.feed(raw)
            
            # Get styled segments
            segments = extractor.get_segments()
            
            # Convert to plain text for backward compatibility
            text = ''.join(seg.text for seg in segments)
            
            # Get title from TOC if available, otherwise use generic chapter number
            toc_title = None
            for toc_entry in self.toc:
                if toc_entry.spine_index == idx:
                    toc_title = toc_entry.title
                    break
            
            # If no TOC entry for this spine index, use the href to find a matching TOC entry
            if not toc_title:
                for toc_entry in self.toc:
                    # Compare hrefs (normalize both)
                    toc_href = norm_href(self.rootfile, toc_entry.href)
                    if os.path.normpath(toc_href) == os.path.normpath(href):
                        toc_title = toc_entry.title
                        break
            
            if toc_title:
                title = toc_title
            else:
                title = "Chapter %d" % (idx + 1)
            
            # Remove duplicate chapter heading from body (if it appears at the start)
            # This handles cases where the TOC title is repeated in the chapter content
            if toc_title:
                title_stripped = toc_title.strip()
                text_stripped = text.strip()
                # If text starts with the title (possibly with extra newlines), remove it
                pattern = r'^' + re.escape(title_stripped) + r'\s*\n*\s*' + re.escape(title_stripped) + r'\s*\n+'
                text = re.sub(pattern, title_stripped + '\n\n', text, flags=re.I)
            
            # Normalize paragraph breaks - reduce multiple blank lines to just one
            text = re.sub(r'\n{3,}', '\n\n', text)
            
            if not text:
                text = "[This chapter contains no readable text.]"
            
            self.chapters.append(text + "\n")
            self.chapter_segments.append(segments)
            self.chapter_titles.append(title)

    def _load_toc(self):
        nav_item = None
        ncx_item = None
        for item in self.manifest.values():
            props = item.get("properties", "")
            mt = item.get("media_type", "")
            if "nav" in props.split():
                nav_item = item
                break
            if mt == "application/x-dtbncx+xml":
                ncx_item = item
        if nav_item:
            self.toc = self._parse_nav_toc(nav_item["href"])
        elif ncx_item:
            self.toc = self._parse_ncx_toc(ncx_item["href"])
        else:
            self.toc = []

    def _parse_nav_toc(self, href: str) -> List[TocEntry]:
        try:
            raw = self._read_member(href).decode("utf-8", errors="replace")
        except KeyError:
            return []
        links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, flags=re.I | re.S)
        entries = []
        seen = set()
        for target, label in links:
            title = re.sub(r"<[^>]+>", "", label)
            title = re.sub(r"\s+", " ", html.unescape(title)).strip()
            title = ascii_sanitize(title)
            if not title:
                continue
            chapter_href = norm_href(href, target)
            spine_index = self._spine_index_for_href(chapter_href)
            if spine_index is None:
                continue
            key = (title, spine_index)
            if key in seen:
                continue
            seen.add(key)
            entries.append(TocEntry(title, chapter_href, spine_index))
        return entries

    def _parse_ncx_toc(self, href: str) -> List[TocEntry]:
        try:
            root = self._read_xml(href)
        except Exception:
            return []
        entries = []
        seen = set()
        for elem in root.iter():
            if strip_ns(elem.tag) != "navPoint":
                continue
            label = ""
            src = ""
            for sub in elem.iter():
                name = strip_ns(sub.tag)
                if name == "text" and sub.text and not label:
                    label = ascii_sanitize(sub.text.strip())
                elif name == "content" and not src:
                    src = sub.attrib.get("src", "")
            if not label or not src:
                continue
            chapter_href = norm_href(href, src)
            spine_index = self._spine_index_for_href(chapter_href)
            if spine_index is None:
                continue
            key = (label, spine_index)
            if key in seen:
                continue
            seen.add(key)
            entries.append(TocEntry(label, chapter_href, spine_index))
        return entries

    def _spine_index_for_href(self, href: str) -> Optional[int]:
        clean = href.split("#", 1)[0]
        for idx, spine_href in enumerate(self.spine_hrefs):
            if os.path.normpath(spine_href) == os.path.normpath(clean):
                return idx
        return None

    def _fill_missing_toc_entries(self):
        if not self.toc:
            self.toc = [
                TocEntry(title=self.chapter_titles[i], href=self.spine_hrefs[i], spine_index=i)
                for i in range(len(self.spine_hrefs))
            ]


class StateStore:
    def __init__(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        self.data = self._load()

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(STATE_FILE):
            return {}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            # Every persisted entry, including _global, has an object schema.
            # Drop only malformed entries so one corrupt book does not erase
            # otherwise valid state.
            return {
                key: entry
                for key, entry in data.items()
                if isinstance(key, str) and isinstance(entry, dict)
            }
        except Exception:
            return {}

    def save(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
        os.replace(tmp, STATE_FILE)

    def _root(self) -> dict:
        if not isinstance(self.data, dict):
            self.data = {}
        return self.data

    def _dict_entry(self, key: str) -> dict:
        root = self._root()
        entry = root.get(key)
        if not isinstance(entry, dict):
            entry = {}
            root[key] = entry
        return entry

    @staticmethod
    def book_key(path: str) -> str:
        return hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()

    def get_state(self, path: str) -> BookState:
        data = self.data if isinstance(self.data, dict) else {}
        entry = data.get(self.book_key(path), {})
        if not isinstance(entry, dict):
            entry = {}
        try:
            chapter_index = max(0, int(entry.get("chapter_index", 0)))
            page_index = max(0, int(entry.get("page_index", 0)))
        except (TypeError, ValueError):
            chapter_index = page_index = 0
        return BookState(
            chapter_index=chapter_index,
            page_index=page_index,
        )

    def set_state(self, path: str, state: BookState):
        abs_path = os.path.abspath(path)
        key = self.book_key(abs_path)
        entry = self._dict_entry(key)
        entry["path"] = abs_path
        entry["chapter_index"] = int(state.chapter_index)
        entry["page_index"] = int(state.page_index)
        global_entry = self._dict_entry("_global")
        global_entry["last_book_path"] = abs_path

    def set_bookmark(self, path: str, chapter_index: int, page_index: int):
        abs_path = os.path.abspath(path)
        key = self.book_key(abs_path)
        entry = self._dict_entry(key)
        entry["path"] = abs_path
        entry["bookmark"] = {
            "chapter_index": int(chapter_index),
            "page_index": int(page_index),
        }
        global_entry = self._dict_entry("_global")
        global_entry["last_book_path"] = abs_path

    def get_bookmark(self, path: str) -> Optional[BookState]:
        data = self.data if isinstance(self.data, dict) else {}
        entry = data.get(self.book_key(path), {})
        if not isinstance(entry, dict):
            return None
        bm = entry.get("bookmark")
        if not isinstance(bm, dict):
            return None
        try:
            return BookState(
                chapter_index=max(0, int(bm.get("chapter_index", 0))),
                page_index=max(0, int(bm.get("page_index", 0))),
            )
        except (TypeError, ValueError):
            return None

    def get_theme(self) -> str:
        data = self.data if isinstance(self.data, dict) else {}
        global_entry = data.get("_global", {})
        if not isinstance(global_entry, dict):
            global_entry = {}
        theme = global_entry.get("theme", "dark")
        return theme if theme in {"dark", "light"} else "dark"

    def set_theme(self, theme: str):
        if theme not in {"dark", "light"}:
            return
        global_entry = self._dict_entry("_global")
        global_entry["theme"] = theme

    def get_show_header(self) -> bool:
        data = self.data if isinstance(self.data, dict) else {}
        global_entry = data.get("_global", {})
        return bool(global_entry.get("show_header", True)) if isinstance(global_entry, dict) else True

    def set_show_header(self, show_header: bool):
        global_entry = self._dict_entry("_global")
        global_entry["show_header"] = bool(show_header)

    def get_justify_text(self) -> bool:
        data = self.data if isinstance(self.data, dict) else {}
        global_entry = data.get("_global", {})
        return bool(global_entry.get("justify_text", False)) if isinstance(global_entry, dict) else False

    def set_justify_text(self, justify_text: bool):
        global_entry = self._dict_entry("_global")
        global_entry["justify_text"] = bool(justify_text)

    def get_last_book_path(self) -> Optional[str]:
        data = self.data if isinstance(self.data, dict) else {}
        global_entry = data.get("_global", {})
        path = global_entry.get("last_book_path") if isinstance(global_entry, dict) else None
        if isinstance(path, str) and path:
            return path
        return None



def _try_install_bundle(name: str) -> Optional[str]:
    """Try to copy a bundled data file from next to the script into DICT_DIR."""
    bundled = os.path.join(SCRIPT_DIR, name)
    if not os.path.isfile(bundled):
        return None
    target = os.path.join(DICT_DIR, name)
    if os.path.isfile(target):
        return target
    try:
        os.makedirs(DICT_DIR, exist_ok=True)
        import shutil
        shutil.copy2(bundled, target)
        return target
    except Exception:
        return None


def load_ecdict_index():
    """Load ECDICT dictionary index from JSON file."""
    global _ecdict_index
    if _ecdict_index is not None:
        return _ecdict_index

    target = EC_DICT_INDEX_PATH
    if not os.path.isfile(target):
        target = _try_install_bundle("ecdict_index.json")
    if not target:
        return None

    try:
        with open(target, 'r') as f:
            _ecdict_index = json.load(f)
        return _ecdict_index
    except Exception:
        return None


def load_word_set():
    """Load word list into a set for O(1) lookups. Cached after first load."""
    global _word_set
    if _word_set is not None:
        return _word_set

    target = WORD_LIST_PATH
    if not os.path.isfile(target):
        target = _try_install_bundle("words.txt")

    if not target:
        _word_set = set()  # Sentinel: file doesn't exist, don't retry
        return _word_set

    try:
        with open(target, 'r') as f:
            _word_set = {line.strip().lower() for line in f if line.strip()}
    except Exception:
        _word_set = set()

    return _word_set


def lookup_word(word: str) -> str:
    """
    Lookup a word in the dictionary.
    Returns a formatted message with definition or suggestions.
    """
    word_lower = word.lower().strip()
    
    # Try ECDICT for modern definitions
    ecdict = load_ecdict_index()
    if ecdict and word_lower in ecdict:
        entry = ecdict[word_lower]
        headword = entry.get("headword", word)
        definition = entry.get("def", "")
        return f"**{headword}**\n\n{definition}"
    
    # Try without punctuation
    clean_word = re.sub(r'[^\w]', '', word_lower)
    if ecdict and clean_word in ecdict:
        entry = ecdict[clean_word]
        definition = entry.get("def", "")
        return f"**{clean_word}**\n\n{definition}"
    
    # Fallback to word set for suggestions
    word_set = load_word_set()
    if not word_set:
        return f"✗ '{word}' not found\n(Dictionary not available)"

    # Check if word exists in the set (O(1))
    if word_lower in word_set:
        return f"✓ '{word}' found\n(No definition available)"

    # Find similar words using length-filtered subset, capped to avoid UI freeze
    target_len = len(word_lower)
    similar = []
    max_candidates = 5000  # Cap examined length-compatible words
    examined_candidates = 0

    for line_word in word_set:
        len_diff = abs(len(line_word) - target_len)
        if len_diff > 1:
            continue
        examined_candidates += 1
        if examined_candidates > max_candidates:
            break

        if len_diff == 0:
            diffs = sum(c1 != c2 for c1, c2 in zip(word_lower, line_word))
            if 1 <= diffs <= 2:
                similar.append((diffs, line_word))
        else:
            shorter, longer = (word_lower, line_word) if len(word_lower) < len(line_word) else (line_word, word_lower)
            for i in range(len(longer)):
                if longer[:i] + longer[i+1:] == shorter:
                    similar.append((1, line_word))
                    break

    similar.sort()
    top_similar = [w for _, w in similar[:5]]
    
    if top_similar:
        return f"✗ '{word}' not found\nDid you mean: {', '.join(top_similar)}?"
    else:
        return f"✗ '{word}' not found in dictionary"


class FilePicker:
    def __init__(self, stdscr, start_path: Optional[str] = None):
        self.stdscr = stdscr
        self.current_dir = os.path.abspath(start_path or os.getcwd())
        if os.path.isfile(self.current_dir):
            self.current_dir = os.path.dirname(self.current_dir)
        self.selected = 0
        self.entries: List[Tuple[str, str, bool]] = []
        self.status = ""
        self.filter_text = ""
        self.filtered_entries: List[Tuple[str, str, bool]] = []
        self.in_search_mode = False
        self.refresh_entries()

    def _normalize_title(self, title: str) -> str:
        """Normalize title for jumping: remove leading articles, strip extension."""
        # Remove .epub extension
        base = os.path.splitext(title)[0]
        # Remove leading articles (case-insensitive)
        articles = ["the ", "a ", "an "]
        for article in articles:
            if base.lower().startswith(article):
                base = base[len(article):].strip()
                break
        return base.strip()

    def jump_to_letter(self, letter: str):
        """Jump to the first entry starting with the given letter (case-insensitive)."""
        letter = letter.lower()
        normalized_entries = [(self._normalize_title(label), label, full, is_dir)
                              for label, full, is_dir in self.filtered_entries]
        
        # Find first entry starting with the letter
        for idx, (normalized, label, full, is_dir) in enumerate(normalized_entries):
            if normalized and normalized[0].lower() == letter:
                self.selected = idx
                self.status = f"Jumped to: {label}"
                break
        else:
            self.status = f"No entries starting with '{letter.upper()}'"

    def refresh_entries(self):
        entries: List[Tuple[str, str, bool]] = []
        parent = os.path.dirname(self.current_dir)
        if parent and parent != self.current_dir:
            entries.append(("..", parent, True))
        try:
            names = os.listdir(self.current_dir)
        except OSError as exc:
            self.status = f"Cannot open directory: {exc}"
            names = []
        dirs = []
        files = []
        for name in names:
            full = os.path.join(self.current_dir, name)
            if os.path.isdir(full):
                dirs.append((name + "/", full, True))
            elif name.lower().endswith(".epub"):
                files.append((name, full, False))
        dirs.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())
        entries.extend(dirs)
        entries.extend(files)
        self.entries = entries
        if self.selected >= len(self.entries):
            self.selected = max(0, len(self.entries) - 1)
        self.apply_filter()

    def apply_filter(self):
        """Apply the current filter text to the entries list."""
        if not self.filter_text:
            self.filtered_entries = self.entries
            self.selected = max(0, min(self.selected, len(self.filtered_entries) - 1)) if self.filtered_entries else 0
            return
        
        filter_lower = self.filter_text.lower()
        self.filtered_entries = [
            entry for entry in self.entries
            if filter_lower in entry[0].lower()
        ]
        
        # Keep selection valid relative to the displayed list.
        self.selected = max(0, min(self.selected, len(self.filtered_entries) - 1)) if self.filtered_entries else 0

    def run(self) -> Optional[str]:
        waiting_for_letter = False
        waiting_letter_buffer = ""
        search_input = ""
        self.stdscr.nodelay(False)
        try:
            while True:
                self.draw()

                # Handle waiting for letter mode
                if waiting_for_letter:
                    ch = self.stdscr.getch()
                    if ch == KEY_ESCAPE:  # Esc - cancel
                        waiting_for_letter = False
                        self.status = "Jump cancelled"
                    elif ch in (KEY_ENTER, KEY_LF):  # Enter - use buffered letter
                        if waiting_letter_buffer:
                            self.jump_to_letter(waiting_letter_buffer)
                        waiting_for_letter = False
                        waiting_letter_buffer = ""
                    elif ch in (KEY_BACKSPACE_ALT, curses.KEY_BACKSPACE, KEY_BACKSPACE_CTRL):  # Backspace - clear buffer
                        waiting_letter_buffer = ""
                        self.status = "Jump: "
                    elif 32 <= ch <= 126:  # Printable character
                        waiting_letter_buffer = chr(ch)
                        self.status = f"Jump to: {waiting_letter_buffer.upper()}"
                    continue

                # Handle search mode
                if self.in_search_mode:
                    ch = self.stdscr.getch()
                    if ch == KEY_ESCAPE:  # Esc - cancel search
                        self.in_search_mode = False
                        search_input = ""
                        self.filter_text = ""
                        self.apply_filter()
                        self.status = "Search cancelled"
                    elif ch in (KEY_ENTER, KEY_LF):  # Enter - exit search mode
                        self.in_search_mode = False
                        search_input = ""
                        self.status = f"Filter: {self.filter_text}" if self.filter_text else ""
                    elif ch in (KEY_BACKSPACE_ALT, curses.KEY_BACKSPACE, KEY_BACKSPACE_CTRL):  # Backspace
                        search_input = search_input[:-1]
                        self.filter_text = search_input
                        self.apply_filter()
                    elif 32 <= ch <= 126:  # Printable character
                        search_input += chr(ch)
                        self.filter_text = search_input
                        self.selected = 0  # Reset selection when filtering
                        self.apply_filter()
                    continue

                ch = self.stdscr.getch()
                if ch in (KEY_ESCAPE, ord("q"), ord("Q")):
                    return None

                # Jump-to-letter mode: 'j' followed by letter
                if ch == ord("j") and not waiting_for_letter:
                    waiting_for_letter = True
                    waiting_letter_buffer = ""
                    self.status = "Jump to: "
                    continue

                # Search mode: 's' to start typing filter
                if ch == ord("s") and not self.in_search_mode:
                    self.in_search_mode = True
                    search_input = ""
                    self.filter_text = ""
                    self.selected = 0
                    self.status = "Search: "
                    continue

                if ch in (curses.KEY_UP, ord("k")):
                    if self.selected > 0:
                        self.selected -= 1
                elif ch in (curses.KEY_DOWN, ord("j")):
                    if self.selected + 1 < len(self.filtered_entries):
                        self.selected += 1
                elif ch in (curses.KEY_NPAGE, KEY_PAGE_DOWN_TERMINFO):
                    if self.filtered_entries:
                        self.selected = min(len(self.filtered_entries) - 1, self.selected + max(1, self.body_height()))
                elif ch in (curses.KEY_PPAGE, KEY_PAGE_UP_TERMINFO):
                    if self.filtered_entries:
                        self.selected = max(0, self.selected - max(1, self.body_height()))
                elif ch == curses.KEY_LEFT:
                    parent = os.path.dirname(self.current_dir)
                    if parent and parent != self.current_dir:
                        self.current_dir = parent
                        self.selected = 0
                        self.refresh_entries()
                elif ch in (KEY_ENTER, KEY_LF, curses.KEY_ENTER, curses.KEY_RIGHT):
                    if not self.filtered_entries:
                        continue
                    _label, full, is_dir = self.filtered_entries[self.selected]
                    if is_dir:
                        self.current_dir = full
                        self.selected = 0
                        self.refresh_entries()
                    else:
                        return full
        finally:
            self.stdscr.nodelay(True)

    def body_height(self) -> int:
        h, _ = self.stdscr.getmaxyx()
        return max(1, h - 3)

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        
        # Top line: title + search/filter bar
        search_bar = ""
        if self.in_search_mode:
            search_bar = "Search: " + self.filter_text + "_"
        elif self.filter_text:
            search_bar = "Filter: " + self.filter_text
        
        jump_hint = "j:jump" if not self.status and not search_bar else ""
        title = f"Open EPUB - Enter/Right: open, Left: up, s:search, j:jump, q/Esc: cancel {jump_hint}"
        
        try:
            self.stdscr.addnstr(0, 0, title.ljust(max(0, w - 1)), w - 1, curses.A_REVERSE)
        except curses.error:
            pass  # Terminal too narrow - skip title display
        
        # Second line: search/filter bar or current directory
        try:
            if search_bar:
                self.stdscr.addnstr(1, 0, search_bar[:w-1], w - 1)
            else:
                self.stdscr.addnstr(1, 0, self.current_dir, w - 1)
        except curses.error:
            pass  # Terminal too narrow - skip path display

        body_top = 2
        body_h = max(1, h - 4 if search_bar else h - 3)
        start = max(0, self.selected - body_h // 2)
        end = min(len(self.filtered_entries), start + body_h)
        start = max(0, end - body_h)

        row = body_top
        for idx in range(start, end):
            actual_idx = start + idx - start
            label, _full, _is_dir = self.filtered_entries[actual_idx]
            attr = curses.A_REVERSE if idx == self.selected else curses.A_NORMAL
            try:
                self.stdscr.addnstr(row, 0, label, w - 1, attr)
            except curses.error:
                pass  # Terminal too narrow for this entry - skip it
            row += 1

        footer = self.status or "Directories and .epub files"
        try:
            self.stdscr.addnstr(h - 1, 0, footer.ljust(max(0, w - 1)), w - 1, curses.A_REVERSE)
        except curses.error:
            pass  # Terminal too narrow - skip footer
        self.stdscr.refresh()
        self.status = ""


class ReaderUI:
    def __init__(self, stdscr, book: EpubBook, store: StateStore):
        self.stdscr = stdscr
        self.store = store
        self.book = book
        self.chapter_index = 0
        self.page_index = 0
        self.status_message = ""
        self.total_pages: int = 0
        self.pages_attrs_cache: Dict[Tuple, List[List[List[Tuple[str, int]]]]] = {}  # Cache pages with attrs by chapter
        self.running = True
        self._pending_resize = False
        self.theme = self.store.get_theme()
        self.show_header = self.store.get_show_header()
        self.justify_text = self.store.get_justify_text()
        self.has_colors = False
        self.header_attr = curses.A_REVERSE
        self.footer_attr = curses.A_REVERSE
        self.selected_attr = curses.A_REVERSE
        self.heading_attr = curses.A_REVERSE  # Can be changed to A_BOLD, A_ITALIC, etc.
        # Color pair cache for dynamic text colors: color_idx -> pair_number
        self.color_pair_cache: Dict[int, int] = {}
        self.next_color_pair: int = FIRST_DYNAMIC_COLOR_PAIR
        # Word selection mode for dictionary lookup
        self.in_selection_mode = False
        self.selected_line = 0            # Line number of selected word (0-based from page body)
        self.selected_word_start = 0      # Character start position within line
        self.selected_word_end = 0        # Character end position within line
        self.all_word_positions: List[Tuple[int, int, int]] = []  # List of (line, start, end) for all words
        self._selection_index: int = 0   # Cached index into all_word_positions
        self.load_book(book, use_saved_position=True)

    @staticmethod
    def _true_terminal_size():
        """Real window size as (rows, cols) straight from the kernel."""
        for stream in (sys.stdout, sys.stdin, sys.stderr):
            try:
                packed = fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
                rows, cols = struct.unpack('HHHH', packed)[:2]
                if rows > 0 and cols > 0:
                    return rows, cols
            except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
                continue
        try:
            size = os.get_terminal_size()
            return size.lines, size.columns
        except OSError:
            return None

    def _handle_resize(self):
        """Update curses geometry for new terminal size, clear caches."""
        size = self._true_terminal_size()
        if size and self.stdscr.getmaxyx() != size:
            try:
                curses.resizeterm(size[0], size[1])
            except (curses.error, AttributeError):
                pass
        try:
            self.stdscr.clear()
        except curses.error:
            pass
        self.pages_attrs_cache.clear()
        self.total_pages = self._compute_total_pages()
        self._pending_resize = False

    def load_book(self, book: EpubBook, use_saved_position: bool = True):
        self.book = book
        if use_saved_position:
            state = self.store.get_state(book.path)
            self.chapter_index = max(0, min(state.chapter_index, len(book.chapters) - 1))
            self.page_index = max(0, state.page_index)
        else:
            self.chapter_index = 0
            self.page_index = 0
        self.pages_attrs_cache.clear()
        self.total_pages = self._compute_total_pages()
        self.store.set_state(self.book.path, BookState(self.chapter_index, self.page_index))
        self.store.save()

    def _compute_total_pages(self) -> int:
        """Compute total pages using the same styled pages used for rendering."""
        return sum(self._get_pages_count(index) for index in range(len(self.book.chapters)))

    def _get_pages_count(self, chapter_index: int) -> int:
        """Get rendered page count for a chapter from the styled-page cache."""
        return max(1, len(self._get_styled_pages(chapter_index)))

    def setup_colors(self):
        if self.has_colors:
            # Colors already initialized; just re-apply theme and clear cache
            self.apply_theme()
            self.pages_attrs_cache.clear()
            return
        self.has_colors = False
        self.header_attr = curses.A_REVERSE
        self.footer_attr = curses.A_REVERSE
        self.selected_attr = curses.A_REVERSE
        self.heading_attr = curses.A_REVERSE
        if not curses.has_colors():
            return
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(COLOR_PAIR_DEFAULT, curses.COLOR_WHITE, curses.COLOR_BLACK)
            curses.init_pair(COLOR_PAIR_INVERSE, curses.COLOR_BLACK, curses.COLOR_WHITE)
            curses.init_pair(COLOR_PAIR_TITLE, curses.COLOR_YELLOW, -1)
            curses.init_pair(COLOR_PAIR_INFO_POPUP, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(COLOR_PAIR_ERROR_POPUP, curses.COLOR_WHITE, curses.COLOR_RED)
            self.has_colors = True
        except curses.error:
            self.has_colors = False
        self.apply_theme()
        self.pages_attrs_cache.clear()

    def apply_theme(self):
        if not self.has_colors:
            self.header_attr = curses.A_REVERSE
            self.footer_attr = curses.A_REVERSE
            self.selected_attr = curses.A_REVERSE
            self.heading_attr = curses.A_REVERSE | curses.A_BOLD
            return
        attr = curses.color_pair(COLOR_PAIR_INVERSE) if self.theme == "light" else curses.color_pair(COLOR_PAIR_DEFAULT)
        self.header_attr = attr
        self.footer_attr = attr
        self.selected_attr = attr
        # Yellow bold for headings (pair 3 is yellow, defined in setup_colors)
        self.heading_attr = curses.color_pair(COLOR_PAIR_TITLE) | curses.A_BOLD

    def styles_to_curses_attr(self, css_styles: dict) -> int:
        """Convert CSS styles dict to curses attribute flags.
        
        Handles the following CSS properties:
        - font_weight: 'bold' or numeric values (700, 800, 900) → curses.A_BOLD
        - text_decoration: 'underline' → curses.A_UNDERLINE
        - text_decoration: 'line-through' → not rendered (terminal limitation)
        - color: hex/rgb colors mapped to 16-color ANSI palette with dynamic pair allocation
        
        Args:
            css_styles: Dictionary of CSS property-value pairs.
                       Keys are underscores (e.g., 'font_weight' not 'font-weight').
        
        Returns:
            curses attribute flags (e.g., curses.A_BOLD | curses.A_UNDERLINE)
        """
        attr = curses.A_NORMAL

        # Font weight: bold
        if css_styles.get('font_weight') in ('bold', '700', '800', '900'):
            attr |= curses.A_BOLD

        # Text decoration: underline (line-through not well supported in terminals)
        if css_styles.get('text_decoration') == 'underline':
            attr |= curses.A_UNDERLINE

        # Font style: italic (not well supported, skip for now)
        # Some terminals support curses.A_ITALIC but it's non-standard

        # Color rendering: dynamic color pair allocation
        if 'color' in css_styles and self.has_colors:
            color_idx = hex_to_16_color(css_styles['color'])
            if color_idx is not None:
                # Use theme's background color (black for dark mode, white for light mode)
                bg_color = curses.COLOR_WHITE if self.theme == "light" else curses.COLOR_BLACK
                
                # Allocate a new color pair if we haven't seen this color before
                if color_idx not in self.color_pair_cache:
                    try:
                        curses.init_pair(self.next_color_pair, color_idx, bg_color)
                        self.color_pair_cache[color_idx] = self.next_color_pair
                        self.next_color_pair += 1
                        # Safety: limit to 256 pairs (most terminals support this)
                        if self.next_color_pair > 255:
                             self.next_color_pair = FIRST_DYNAMIC_COLOR_PAIR
                    except curses.error:
                        # Terminal doesn't support this many color pairs, skip coloring
                        pass

                # Apply the color pair to the attribute
                pair_num = self.color_pair_cache.get(color_idx)
                if pair_num is not None:
                    attr |= curses.color_pair(pair_num)

        return attr

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        # Clear color cache so colors are re-rendered with correct background
        self.color_pair_cache.clear()
        self.next_color_pair = FIRST_DYNAMIC_COLOR_PAIR
        self.store.set_theme(self.theme)
        self.store.save()
        self.pages_attrs_cache.clear()
        self.apply_theme()
        self.show_info_popup("Theme", f"Theme: {self.theme}")

    def toggle_header(self):
        self.show_header = not self.show_header
        self.store.set_show_header(self.show_header)
        self.total_pages = self._compute_total_pages()  # Recompute when header changes
        self.store.save()
        self.show_info_popup("Header", f"Header: {'on' if self.show_header else 'off'}")

    def toggle_heading_style(self):
        """Toggle between yellow-bold and reverse for headings."""
        yellow_bold = curses.color_pair(COLOR_PAIR_TITLE) | curses.A_BOLD if self.has_colors else curses.A_BOLD
        reverse = curses.A_REVERSE
        if self.heading_attr == reverse:
            self.heading_attr = yellow_bold
            style = "yellow+bold"
        else:
            self.heading_attr = reverse
            style = "reverse"
        self.pages_attrs_cache.clear()
        self.show_info_popup("Heading", f"Heading style: {style}")

    def toggle_justify(self):
        """Toggle justified text mode."""
        self.justify_text = not self.justify_text
        self.store.set_justify_text(self.justify_text)
        self.store.save()
        self.pages_attrs_cache.clear()
        mode = "justified" if self.justify_text else "left-aligned"
        self.show_info_popup("Text", f"Text alignment: {mode}")

    def dictionary_lookup(self):
        """Enter word selection mode for dictionary lookup.
        
        First press 'd': Enter selection mode, highlight first word
        Arrow keys: Move selection between words
        Enter: Lookup selected word
        Escape: Cancel selection
        """
        if self.in_selection_mode:
            # Enter key pressed - lookup the selected word
            if self.selected_word_start < self.selected_word_end:
                # Get the selected word from the styled pages (same source as extraction!)
                styled_pages = self._get_styled_pages(self.chapter_index)
                word = ""
                if styled_pages and self.page_index < len(styled_pages):
                    page = styled_pages[self.page_index]
                    if self.selected_line < len(page):
                        line_fragments = page[self.selected_line]
                        # Join all fragments to get the full line text
                        line_text = ''.join(fragment_text for fragment_text, _ in line_fragments)
                        # Extract the selected word
                        word = line_text[self.selected_word_start:self.selected_word_end].strip()
                
                if word:
                    # Exit selection mode
                    self.in_selection_mode = False
                    # Lookup the word
                    result = lookup_word(word)
                    # Show result in a popup
                    self.show_info_popup("Dictionary", result)
                    # Redraw to remove highlight
                    self.draw()
                else:
                    self.show_info_popup("Dictionary", "No word selected")
                    self.in_selection_mode = False
                    self.draw()
            else:
                self.in_selection_mode = False
                self.draw()
        else:
            # First 'd' - enter selection mode
            self._enter_selection_mode()

    def _enter_selection_mode(self):
        """Enter word selection mode and highlight first word on page."""
        self.in_selection_mode = True
        # Extract word positions from current page
        self._extract_word_positions()
        if self.all_word_positions:
            # Select first word
            line, start, end = self.all_word_positions[0]
            self.selected_line = line
            self.selected_word_start = start
            self.selected_word_end = end
            self._selection_index = 0
            self.draw()
        else:
            # No words on page
            self.in_selection_mode = False
            self.show_info_popup("Dictionary", "No words on this page")

    def dictionary_prompt(self):
        """Prompt for a word and show dictionary info (direct lookup without selection)."""
        # Get word from user prompt
        self.stdscr.keypad(False)
        curses.echo()
        curses.curs_set(1)
        self.stdscr.nodelay(False)

        try:
            # Show prompt
            h, w = self.stdscr.getmaxyx()
            prompt = "Word to lookup: "
            try:
                self.stdscr.addnstr(h - 2, 0, " " * (w - 1), w - 1)
                self.stdscr.addnstr(h - 2, 0, prompt, w - 1)
            except curses.error:
                pass
            self.stdscr.refresh()

            # Read input
            word = ""
            while True:
                ch = self.stdscr.getch()
                if ch == KEY_ESCAPE:  # Escape
                    word = None
                    break
                elif ch in (KEY_ENTER, KEY_LF):  # Enter
                    break
                elif ch in (KEY_BACKSPACE_ALT, KEY_BACKSPACE_CTRL):  # Backspace
                    if word:
                        word = word[:-1]
                        h, w = self.stdscr.getmaxyx()
                        try:
                            self.stdscr.addnstr(h - 2, 0, " " * (w - 1), w - 1)
                            self.stdscr.addnstr(h - 2, 0, prompt + word, w - 1)
                        except curses.error:
                            pass
                        self.stdscr.refresh()
                elif 32 <= ch <= 126:  # Printable
                    word += chr(ch)
                    h, w = self.stdscr.getmaxyx()
                    try:
                        self.stdscr.addnstr(h - 2, 0, " " * (w - 1), w - 1)
                        self.stdscr.addnstr(h - 2, 0, prompt + word, w - 1)
                    except curses.error:
                        pass
                    self.stdscr.refresh()
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.stdscr.keypad(True)
            self.stdscr.nodelay(True)
        
        if word is None:
            return  # Cancelled
        
        if not word.strip():
            self.show_info_popup("Dictionary", "No word entered")
            return
        
        # Lookup the word
        result = lookup_word(word.strip())
        
        # Show result in a popup
        self.show_info_popup("Dictionary", result)

    def _extract_word_positions(self):
        """Extract word positions (line_num, start_char, end_char) from current page.
        
        Stores tuples of (line_number, char_start, char_end) for each word.
        line_number is relative to the page (0-based from top of page body).
        char_start and char_end are positions within that line.
        
        IMPORTANT: Uses the same styled pages as rendering to ensure positions match!
        """
        self.all_word_positions = []
        
        # Get the styled pages (same as what draw() uses)
        styled_pages = self._get_styled_pages(self.chapter_index)
        if not styled_pages:
            return
            
        # Get the current page
        if self.page_index >= len(styled_pages):
            return
        page = styled_pages[self.page_index]
        
        # Extract word positions from each line
        for line_num, line_fragments in enumerate(page):
            # Join all fragments to get the plain line text
            line_text = ''.join(fragment_text for fragment_text, _ in line_fragments)
            
            word_start = None
            for i, ch in enumerate(line_text):
                # Word characters: alphanumeric only
                if ch.isalnum():
                    if word_start is None:
                        word_start = i
                else:
                    if word_start is not None:
                        # Word ended - store as (line_num, start, end)
                        self.all_word_positions.append((line_num, word_start, i))
                        word_start = None
            # Handle word at end of line
            if word_start is not None:
                self.all_word_positions.append((line_num, word_start, len(line_text)))

    def _navigate_selection(self, direction: str):
        """Navigate word selection with arrow keys.
        
        Left/Right: Move to previous/next word
        Up/Down: Move to word on previous/next line (or closest if different line length)
        """
        if not self.in_selection_mode or not self.all_word_positions:
            return

        current_idx = self._selection_index
        # The cached index can be stale if the page changed while in selection
        # mode (e.g., resize repaged the content). Reset to first word if out of range.
        if not (0 <= current_idx < len(self.all_word_positions)):
            current_idx = 0
            self._selection_index = 0

        current_line, current_start, current_end = self.all_word_positions[current_idx]
        
        # Navigate based on direction
        if direction == "left" and current_idx > 0:
            idx = current_idx - 1
            line, start, end = self.all_word_positions[idx]
            self.selected_line = line
            self.selected_word_start = start
            self.selected_word_end = end
            self._selection_index = idx
        elif direction == "right" and current_idx < len(self.all_word_positions) - 1:
            idx = current_idx + 1
            line, start, end = self.all_word_positions[idx]
            self.selected_line = line
            self.selected_word_start = start
            self.selected_word_end = end
            self._selection_index = idx
        elif direction == "up":
            target_line = current_line - 1
            for i in range(current_idx - 1, -1, -1):
                line, start, end = self.all_word_positions[i]
                if line <= target_line:
                    self.selected_line = line
                    self.selected_word_start = start
                    self.selected_word_end = end
                    self._selection_index = i
                    break
        elif direction == "down":
            target_line = current_line + 1
            for i in range(current_idx + 1, len(self.all_word_positions)):
                line, start, end = self.all_word_positions[i]
                if line >= target_line:
                    self.selected_line = line
                    self.selected_word_start = start
                    self.selected_word_end = end
                    self._selection_index = i
                    break
        
        self.draw()

    def get_overall_progress(self) -> Tuple[int, int]:
        """Return (current_page, total_pages) for the entire book."""
        # Count pages in all chapters before current one
        h, w = self.stdscr.getmaxyx()
        reserved = 2 if self.show_header else 1
        body_h = max(3, h - reserved)
        
        pages_before = 0
        for i in range(self.chapter_index):
            chapter_pages = self._get_pages_count(i)
            pages_before += chapter_pages
        
        # Pages in current chapter
        current_page = pages_before + self.page_index + 1
        
        return (current_page, self.total_pages)

    def show_info_popup(self, title: str, message: str, is_error: bool = False):
        """Show a blocking, scrollable information or error popup."""
        if not self.has_colors:
            self.setup_colors()
        if self.has_colors:
            background = curses.color_pair(
                COLOR_PAIR_INVERSE if self.theme == "light" else COLOR_PAIR_DEFAULT
            )
            self.stdscr.bkgd(" ", background)

        h, w = self.stdscr.getmaxyx()
        if w < 6 or h < 5:
            try:
                self.stdscr.erase()
                self.stdscr.addnstr(h // 2, 0, "Too small", max(0, w - 1))
                self.stdscr.refresh()
                self.stdscr.nodelay(False)
                self.stdscr.getch()
            except curses.error:
                pass
            finally:
                self.stdscr.nodelay(True)
            return

        max_msg_width = max(1, min(w - 6, 80))
        lines = []
        for paragraph in message.split("\n"):
            if not paragraph.strip():
                lines.append("")
                continue
            lines.extend(textwrap.wrap(
                paragraph, width=max_msg_width, replace_whitespace=True,
                drop_whitespace=True, break_long_words=True,
                break_on_hyphens=False,
            ) or [""])

        longest_line = max([len(title)] + [len(line) for line in lines])
        popup_width = min(w, max(6, min(max_msg_width + 4, longest_line + 4)))
        max_popup_height = max(5, min(h, int(h * 0.85)))
        popup_height = min(max_popup_height, max(5, len(lines) + 4))
        visible_count = max(1, popup_height - 4)
        max_offset = max(0, len(lines) - visible_count)
        offset = 0
        start_y = max(0, (h - popup_height) // 2)
        start_x = max(0, (w - popup_width) // 2)
        popup_attr = (
            curses.color_pair(COLOR_PAIR_ERROR_POPUP if is_error else COLOR_PAIR_INFO_POPUP)
            if self.has_colors else curses.A_REVERSE
        )
        title_attr = (
            curses.color_pair(COLOR_PAIR_TITLE) | curses.A_BOLD
            if self.has_colors else curses.A_BOLD
        )

        self.stdscr.nodelay(False)
        try:
            while True:
                self.stdscr.erase()
                visible_lines = lines[offset:offset + visible_count]
                try:
                    border = "+" + "-" * (popup_width - 2) + "+"
                    self.stdscr.addnstr(start_y, start_x, border, popup_width, popup_attr)
                    for row in range(1, popup_height - 1):
                        blank = "|" + " " * (popup_width - 2) + "|"
                        self.stdscr.addnstr(start_y + row, start_x, blank, popup_width, popup_attr)
                    self.stdscr.addnstr(start_y + popup_height - 1, start_x, border, popup_width, popup_attr)

                    title_line = f" {title} "[:popup_width - 2]
                    title_x = start_x + max(1, (popup_width - len(title_line)) // 2)
                    self.stdscr.addnstr(start_y + 1, title_x, title_line, popup_width - 2, title_attr)

                    msg_width = popup_width - 4
                    for row, line in enumerate(visible_lines):
                        self.stdscr.addnstr(start_y + 2 + row, start_x + 2, line, msg_width, popup_attr)

                    if max_offset:
                        footer = f"Up/Down {offset + 1}-{min(len(lines), offset + visible_count)}/{len(lines)}"
                    else:
                        footer = "Press any key..."
                    footer = footer[:popup_width - 2].center(popup_width - 2)
                    self.stdscr.addnstr(
                        start_y + popup_height - 2, start_x + 1,
                        footer, popup_width - 2, popup_attr,
                    )
                except curses.error:
                    pass
                self.stdscr.refresh()

                ch = self.stdscr.getch()
                if max_offset and ch == curses.KEY_DOWN:
                    offset = min(max_offset, offset + 1)
                elif max_offset and ch == curses.KEY_UP:
                    offset = max(0, offset - 1)
                elif max_offset and ch in (curses.KEY_NPAGE, KEY_PAGE_DOWN_TERMINFO):
                    offset = min(max_offset, offset + visible_count)
                elif max_offset and ch in (curses.KEY_PPAGE, KEY_PAGE_UP_TERMINFO):
                    offset = max(0, offset - visible_count)
                else:
                    break
        finally:
            self.stdscr.nodelay(True)
            self.status_message = ""

    def show_help(self):
        """Display a help dialog - split into small pages that fit small screens."""
        help_page1 = """Page 1/3

READER:
  Left/Right  Prev/Next page
  Up/Down     Prev/Next chapter
  t           Table of Contents
  /           Search
  b           Bookmark
  o           Open file
  q           Quit

Press any key..."""
        
        help_page2 = """Page 2/3

MODES:
  m           Toggle theme
  H           Toggle header
  j           Toggle justify
  d           Dict (select)
  ?           Dict (type)
  h           Help

Press any key..."""
        
        help_page3 = """Page 3/3

TIPS:
  --bookmark  Resume position
  --no-css    Faster rendering

SELECTION (d):
  Arrows      Move
  Enter       Lookup
  Esc         Cancel

Press any key..."""
        
        # Show each page
        self.show_info_popup("Help", help_page1)
        self.show_info_popup("Help", help_page2)
        self.show_info_popup("Help", help_page3)
    
    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.nodelay(True)
        self.setup_colors()
        self._ensure_page_in_range()

        # Signal handlers only set flags; all curses calls happen in the main
        # loop, avoiding re-entrant terminal operations.
        def _on_sigwinch(signum, frame, ui=self):
            ui._pending_resize = True

        try:
            signal.signal(signal.SIGWINCH, _on_sigwinch)
        except (OSError, ValueError):
            pass

        self.show_info_popup("Loaded", f"Loaded: {self.book.title}")
        needs_draw = True
        while self.running:
            if self._pending_resize:
                self._handle_resize()
                needs_draw = True
            if needs_draw:
                self._ensure_page_in_range()
                self.draw()
                needs_draw = False
            try:
                ch = self.stdscr.getch()
            except curses.error:
                ch = -1
            if ch == -1:
                time.sleep(0.1)
                continue
            if ch == curses.KEY_RESIZE:
                self._pending_resize = True
                continue
            self.handle_key(ch)
            needs_draw = True
        self._save_position()

    def _save_position(self):
        self.store.set_state(self.book.path, BookState(self.chapter_index, self.page_index))
        self.store.save()

    def _ensure_page_in_range(self):
        pages = self._get_styled_pages(self.chapter_index)
        if not pages:
            self.page_index = 0
            return
        if self.page_index < 0:
            self.page_index = 0
        elif self.page_index >= len(pages):
            self.page_index = len(pages) - 1

    def _wrap_text(self, text: str, width: int) -> List[str]:
        out: List[str] = []
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            para = para.strip("\n")
            if not para.strip():
                out.append("")
                continue
            lines = para.splitlines()
            if len(lines) > 1 and any(line.startswith(("    ", "\t")) for line in lines):
                for line in lines:
                    wrapped = textwrap.wrap(
                        line,
                        width=max(10, width),
                        replace_whitespace=False,
                        drop_whitespace=False,
                        break_long_words=False,
                        break_on_hyphens=False,
                    ) or [line]
                    out.extend(wrapped)
            else:
                joined = " ".join(part.strip() for part in lines if part.strip())
                wrapped = textwrap.wrap(
                    joined,
                    width=max(10, width),
                    replace_whitespace=True,
                    drop_whitespace=True,
                    break_long_words=False,
                    break_on_hyphens=False,
                ) or [""]
                out.extend(wrapped)
            out.append("")
        if out and out[-1] == "":
            out.pop()
        return out

    def _justify_line(self, words: List[Tuple[str, int]], target_width: int) -> List[Tuple[str, int]]:
        """Justify a line by distributing extra space between words.
        
        Args:
            words: List of (word_text, attr) tuples
            target_width: Target line width
            
        Returns:
            List of (fragment_text, attr) tuples with extra spaces distributed
        """
        if not words:
            return []
        
        # Calculate current width (sum of all word lengths)
        total_word_width = sum(len(w) for w, _ in words)
        
        # Count number of gaps between words (excluding space fragments)
        actual_words = [(w, a) for w, a in words if w != " "]
        num_gaps = len(actual_words) - 1
        
        if num_gaps <= 0:
            # Single word or empty - can't justify, return as-is
            return words
        
        # Calculate extra space to distribute
        extra_space = target_width - total_word_width
        
        # Distribute extra space evenly across gaps
        space_per_gap = extra_space // num_gaps
        extra_spaces = extra_space % num_gaps  # Remaining spaces to distribute left-to-right
        
        # Build justified line
        justified: List[Tuple[str, int]] = []
        for i, (word, attr) in enumerate(actual_words):
            justified.append((word, attr))
            if i < num_gaps:
                # Add space after word (except last)
                spaces = " " * (1 + space_per_gap + (1 if i < extra_spaces else 0))
                justified.append((spaces, attr))
        
        return justified

    def _wrap_segments_with_styles(self, segments: List[StyledSegment], width: int) -> List[List[Tuple[str, int]]]:
        """Wrap styled segments while preserving style boundaries.
        
        Returns list of lines, where each line is a list of (text_fragment, curses_attr) tuples.
        This allows multiple styles per line (e.g., "Hello [bold]world[/bold]").
        
        Supports left-aligned and justified text modes.
        
        Strategy: Greedy line building with segment splitting.
        - Accumulate segment fragments until line would exceed width
        - If current segment would overflow, split it at word boundary
        - For justified mode: distribute extra space between words
        - Each fragment retains its original style attribute
        
        Args:
            segments: List of StyledSegment objects from EpubTextExtractor
            width: Maximum line width in characters
            
        Returns:
            List of lines, each line is List[Tuple[fragment_text, curses_attr]]
        """
        if not segments:
            return []
        
        lines: List[List[Tuple[str, int]]] = []
        current_line_words: List[Tuple[str, int]] = []  # List of (word, attr) tuples
        current_line_width = 0  # Width without extra spaces (just words + single spaces)
        
        def flush_line(is_last_line: bool = False):
            """Commit current line with justification if enabled, and reset for next line."""
            nonlocal current_line_words, current_line_width
            
            if not current_line_words:
                current_line_words = []
                current_line_width = 0
                return
            
            # Check if this is the last line of a paragraph (no justification for last line)
            if self.justify_text and not is_last_line:
                # Justified mode: distribute extra space between words
                justified_line = self._justify_line(current_line_words, width)
                lines.append(justified_line)
            else:
                # Left-aligned: just join words with single spaces
                lines.append(current_line_words)
            
            current_line_words = []
            current_line_width = 0
        
        def add_word(word: str, attr: int):
            """Add a word to current line, flushing if needed."""
            nonlocal current_line_words, current_line_width
            
            if not word:
                return
            
            word_len = len(word)
            space_len = 1 if current_line_words else 0  # Space before word (not before first word)
            new_width = current_line_width + space_len + word_len
            
            # Check if word fits on current line
            if new_width <= width:
                # Add space separator if not first word
                if current_line_words:
                    current_line_words.append((" ", attr))
                current_line_words.append((word, attr))
                current_line_width = new_width
            else:
                # Word doesn't fit - flush current line first
                flush_line(is_last_line=False)
                
                # Now add word to new line
                if word_len > width:
                    # Very long word - split it
                    while word:
                        chunk = word[:width]
                        word = word[width:]
                        current_line_words.append((chunk, attr))
                        current_line_width = len(chunk)
                        flush_line(is_last_line=False)
                else:
                    current_line_words.append((word, attr))
                    current_line_width = word_len
        
        # Process all segments, deduplicating near-duplicates
        # (e.g., "CHAPTER ONE" appearing twice with only blank lines between)
        last_nonblank_text = None
        last_nonblank_attr = None
        last_blank_count = 0  # Track consecutive blank lines
        
        for seg in segments:
            text = seg.text
            base_attr = self.styles_to_curses_attr(seg.styles)
            if seg.is_heading:
                # Use heading_attr directly to avoid OR-ing two color pairs
                attr = self.heading_attr
            else:
                attr = base_attr

            # Normalize text for comparison (strip whitespace)
            text_normalized = text.strip()

            # Skip duplicates of last non-blank segment (handles cases like:
            # "CHAPTER ONE" -> blank lines -> "CHAPTER ONE" again).
            if text_normalized and text_normalized == last_nonblank_text and base_attr == last_nonblank_attr:
                continue

            # Update last non-blank tracker
            if text_normalized:
                last_nonblank_text = text_normalized
                last_nonblank_attr = base_attr
                last_blank_count = 0  # Reset blank counter on non-blank
            else:
                # Handle whitespace-only segments (paragraph breaks)
                # Limit consecutive blank lines to 1 (avoid excessive spacing)
                if last_blank_count >= 1:
                    continue  # Skip additional consecutive blanks
                last_blank_count += 1
                
                # Flush any pending content, add blank line
                if current_line_words:
                    flush_line(is_last_line=True)  # Last line of paragraph - don't justify
                # Add empty line as a line with single empty fragment
                lines.append([("", curses.A_NORMAL)])
            
            if text_normalized:
                # Split text into words and add them one by one
                words = text_normalized.split()
                for i, word in enumerate(words):
                    # Add space between words (handled by add_word)
                    add_word(word, attr)
        
        # Flush any remaining content (as last line - no justification)
        flush_line(is_last_line=True)
        
        return lines

    def _get_styled_pages(self, chapter_index: int) -> List[List[List[Tuple[str, int]]]]:
        """Get pages as list of lines, where each line is list of (text, attr) fragments.
        
        Wraps text properly while preserving CSS style boundaries. Each line can have
        multiple fragments with different styles (e.g., bold mixed with normal text).
        
        Returns:
            List of pages, where each page is a list of lines,
            and each line is a list of (fragment_text, curses_attr) tuples.
        """
        h, w = self.stdscr.getmaxyx()
        cache_key = (chapter_index, h, w, self.show_header, self.justify_text, self.theme, self.heading_attr)

        if cache_key in self.pages_attrs_cache:
            return self.pages_attrs_cache[cache_key]
        
        body_h = max(3, h - (2 if self.show_header else 1))
        body_w = max(20, w - 1)
        
        segments = self.book.chapter_segments[chapter_index]

        if not segments:
            # Fallback to plain text if no styled segments available
            chapter_text = self.book.chapters[chapter_index]
            lines = self._wrap_text(chapter_text, body_w)
            # Convert to fragment format: each line is single fragment with normal attr
            styled_lines = [[(line, curses.A_NORMAL)] for line in lines]
        else:
            # NEW: Wrap segments directly, preserving style boundaries
            styled_lines = self._wrap_segments_with_styles(segments, body_w)
        
        # Split into pages
        pages = []
        for i in range(0, len(styled_lines), body_h):
            page = styled_lines[i:i + body_h]
            pages.append(page)
        
        self.pages_attrs_cache[cache_key] = pages
        return pages

    def _get_plain_pages(self, chapter_index: int) -> List[List[str]]:
        """Get pages as plain text (without styling attributes).
        
        Used by navigation methods that only need page count, not rendering.
        Converts fragment-based lines back to plain strings by joining fragments.
        """
        styled_pages = self._get_styled_pages(chapter_index)
        # Join all fragments in each line to get plain text
        plain_pages = []
        for page in styled_pages:
            plain_page = [''.join(fragment_text for fragment_text, _ in line) for line in page]
            plain_pages.append(plain_page)
        return plain_pages

    def _calculate_selection_display(self) -> Tuple[int, int, int]:
        """Calculate display position (line_num, start_col, end_col) for selected word.
        
        Returns tuple of (line number from body_start, start column, end column).
        """
        # We already have the line number and column positions
        # Just need to add body_start offset for the display line
        body_start = 1 if self.show_header else 0
        return (self.selected_line + body_start, self.selected_word_start, self.selected_word_end)

    def draw(self):
        self.stdscr.erase()
        if self.has_colors:
            self.stdscr.bkgd(" ", curses.color_pair(COLOR_PAIR_INVERSE) if self.theme == "light" else curses.color_pair(COLOR_PAIR_DEFAULT))
        h, w = self.stdscr.getmaxyx()

        # Get styled pages directly
        styled_pages = self._get_styled_pages(self.chapter_index)
        page = styled_pages[self.page_index] if styled_pages else [[("", curses.A_NORMAL)]]
        
        body_start = 1 if self.show_header else 0
        if self.show_header:
            # Just show the book title in the header
            header = self.book.title
            try:
                self.stdscr.addnstr(0, 0, header, w - 1, self.header_attr)
            except curses.error:
                pass  # Terminal too narrow - skip header
        
        # If in selection mode, get plain text to highlight selected word
        selection_highlight = None  # (line_num, start_col, end_col)
        if self.in_selection_mode:
            # Validate selection bounds before highlighting
            if (self.selected_word_start >= 0 and 
                self.selected_word_end > self.selected_word_start and
                self.selected_line >= 0):
                selection_highlight = self._calculate_selection_display()
        
        # Render each line with its fragments (each fragment can have different style)
        for idx, line_fragments in enumerate(page, start=body_start):
            if idx >= h - 1:
                break
            
            # Check if this line has a selection highlight
            line_has_selection = (selection_highlight and selection_highlight[0] == idx)
            sel_start, sel_end = None, None
            if line_has_selection:
                sel_start, sel_end = selection_highlight[1], selection_highlight[2]
            
            # If in selection mode on this line, render character-by-character for precise highlighting
            if line_has_selection and sel_start is not None:
                # Reconstruct the full line text
                full_line_text = ''.join(fragment_text for fragment_text, _ in line_fragments)
                
                # Render each character, applying reverse video to selected range
                for char_idx, char in enumerate(full_line_text):
                    if char_idx >= w - 1:
                        break
                    
                    # Check if this character is in the selection range
                    is_selected = (sel_start <= char_idx < sel_end)
                    
                    # Find the original fragment's attribute for this character
                    frag_pos = 0
                    attr = curses.A_NORMAL
                    for fragment_text, frag_attr in line_fragments:
                        if frag_pos <= char_idx < frag_pos + len(fragment_text):
                            attr = frag_attr
                            break
                        frag_pos += len(fragment_text)
                    
                    # Add reverse video if selected
                    if is_selected:
                        attr |= curses.A_REVERSE
                    
                    try:
                        self.stdscr.addch(idx, char_idx, char, attr)
                    except curses.error:
                        _log_curses_error("addch", idx, char_idx)
                        break
            else:
                # Normal rendering: use fragments as before
                x = 0
                for fragment_text, attr in line_fragments:
                    if x >= w - 1:
                        break

                    try:
                        remaining_width = w - 1 - x
                        self.stdscr.addnstr(idx, x, fragment_text, remaining_width, attr)
                        x += len(fragment_text)
                    except curses.error:
                        _log_curses_error("addnstr", idx, x)
                        break
        
        # Get overall book progress
        current_page, total_pages = self.get_overall_progress()
        progress_pct = int((current_page / total_pages) * 100) if total_pages > 0 else 0
        
        # Show selection mode footer or normal footer
        if self.in_selection_mode:
            footer = FOOTER_FORMAT_SELECTION
        else:
            # Simplified footer - just position info
            footer = FOOTER_FORMAT.format(
                self.chapter_index + 1,
                len(self.book.chapters),
                current_page,
                total_pages,
                progress_pct,
            )
        
        try:
            self.stdscr.addnstr(h - 1, 0, footer.ljust(max(0, w - 1)), w - 1, self.footer_attr)
        except curses.error:
            pass  # Terminal too narrow - skip footer
        self.stdscr.refresh()
        # Clear status message each frame to prevent persistence across draws
        self.status_message = ""

    def prompt(self, prompt_text: str) -> str:
        h, w = self.stdscr.getmaxyx()
        curses.curs_set(1)
        curses.echo()
        self.stdscr.nodelay(False)
        try:
            self.stdscr.move(h - 1, 0)
            self.stdscr.clrtoeol()
            self.stdscr.addnstr(h - 1, 0, prompt_text, w - 1, self.footer_attr)
            self.stdscr.refresh()
            raw = self.stdscr.getstr(h - 1, min(len(prompt_text), max(0, w - 1)), max(1, w - len(prompt_text) - 1))
            return raw.decode("utf-8", errors="replace")
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.stdscr.nodelay(True)

    def handle_key(self, ch: int):
        # Handle selection mode first
        if self.in_selection_mode:
            if ch in (KEY_ENTER, KEY_LF, curses.KEY_ENTER):  # Enter key
                # Look up selected word
                self.dictionary_lookup()
            elif ch == KEY_ESCAPE:  # Escape
                # Cancel selection mode
                self.in_selection_mode = False
                self.draw()
            elif ch == curses.KEY_LEFT:
                self._navigate_selection("left")
            elif ch == curses.KEY_RIGHT:
                self._navigate_selection("right")
            elif ch == curses.KEY_UP:
                self._navigate_selection("up")
            elif ch == curses.KEY_DOWN:
                self._navigate_selection("down")
            return  # Don't process other keys in selection mode
        
        if ch in (ord("q"), ord("Q")):
            self.running = False
        elif ch == curses.KEY_RIGHT:
            self.next_page()
        elif ch == curses.KEY_LEFT:
            self.prev_page()
        elif ch == curses.KEY_DOWN:
            self.next_chapter()
        elif ch == curses.KEY_UP:
            self.prev_chapter()
        elif ch in (curses.KEY_NPAGE, KEY_PAGE_DOWN_TERMINFO):
            self.next_page()
        elif ch in (curses.KEY_PPAGE, KEY_PAGE_UP_TERMINFO):
            self.prev_page()
        elif ch in (ord("t"), ord("T")):
            self.open_toc()
        elif ch == ord("/"):
            self.search_prompt()
        elif ch in (ord("b"), ord("B")):
            self.set_bookmark()
        elif ch in (ord("o"), ord("O")):
            self.open_file_picker()
        elif ch in (ord("m"), ord("M")):
            self.toggle_theme()
        elif ch == ord("h"):
            self.show_help()
        elif ch == ord("H"):
            self.toggle_header()
        elif ch in (ord("g"), ord("G")):
            self.toggle_heading_style()
        elif ch in (ord("j"), ord("J")):
            self.toggle_justify()
        elif ch in (ord("d"), ord("D")):
            self.dictionary_lookup()
        elif ch == ord("?"):
            self.dictionary_prompt()


    def next_page(self):
        pages = self._get_styled_pages(self.chapter_index)
        if self.page_index + 1 < len(pages):
            self.page_index += 1
        elif self.chapter_index + 1 < len(self.book.chapters):
            self.chapter_index += 1
            self.page_index = 0
        else:
            self.show_info_popup("Info", "End of book")

    def prev_page(self):
        if self.page_index > 0:
            self.page_index -= 1
        elif self.chapter_index > 0:
            self.chapter_index -= 1
            prev_pages = self._get_styled_pages(self.chapter_index)
            self.page_index = max(0, len(prev_pages) - 1)
        else:
            self.show_info_popup("Info", "Start of book")

    def next_chapter(self):
        if self.chapter_index + 1 < len(self.book.chapters):
            self.chapter_index += 1
            self.page_index = 0
        else:
            self.show_info_popup("Info", "Last chapter")

    def prev_chapter(self):
        if self.chapter_index > 0:
            self.chapter_index -= 1
            self.page_index = 0
        else:
            self.show_info_popup("Info", "First chapter")

    def open_toc(self):
        entries = self.book.toc
        if not entries:
            self.show_info_popup("Table of Contents", "No table of contents available")
            return
        idx = 0
        for i, entry in enumerate(entries):
            if entry.spine_index == self.chapter_index:
                idx = i
                break
        self.stdscr.nodelay(False)
        try:
            while True:
                self._draw_toc(entries, idx)
                ch = self.stdscr.getch()
                if ch == curses.KEY_RESIZE:
                    self._handle_resize()
                    idx = max(0, min(idx, len(entries) - 1))
                    continue
                if ch in (ord("q"), KEY_ESCAPE):
                    return
                if ch in (curses.KEY_DOWN, ord("j")):
                    idx = min(len(entries) - 1, idx + 1)
                elif ch in (curses.KEY_UP, ord("k")):
                    idx = max(0, idx - 1)
                elif ch in (KEY_ENTER, KEY_LF, curses.KEY_ENTER, curses.KEY_RIGHT):
                    self.chapter_index = entries[idx].spine_index
                    self.page_index = 0
                    return
                elif ch in (curses.KEY_NPAGE, KEY_PAGE_DOWN_TERMINFO):
                    idx = min(len(entries) - 1, idx + 10)
                elif ch in (curses.KEY_PPAGE, KEY_PAGE_UP_TERMINFO):
                    idx = max(0, idx - 10)
        finally:
            self.stdscr.nodelay(True)

    def _draw_toc(self, entries: List[TocEntry], selected: int):
        self.stdscr.erase()
        if self.has_colors:
            self.stdscr.bkgd(" ", curses.color_pair(COLOR_PAIR_INVERSE) if self.theme == "light" else curses.color_pair(COLOR_PAIR_DEFAULT))
        h, w = self.stdscr.getmaxyx()
        title = "Table of Contents - Enter/Right: open, q/Esc: back"
        try:
            self.stdscr.addnstr(0, 0, title.ljust(max(0, w - 1)), w - 1, self.header_attr)
        except curses.error:
            pass  # Terminal too narrow - skip TOC title
        body_h = max(1, h - 2)
        start = max(0, selected - body_h // 2)
        end = min(len(entries), start + body_h)
        start = max(0, end - body_h)
        row = 1
        for i in range(start, end):
            entry = entries[i]
            # Format: "=> CHAPTER ONE" or "   main" (no numbers, cleaner)
            if i == selected:
                # Use selected_attr if available, otherwise fallback to reverse video
                attr = self.selected_attr if self.selected_attr != curses.A_NORMAL else curses.A_REVERSE
                text = "=> " + entry.title
            else:
                attr = curses.A_NORMAL
                text = "   " + entry.title  # Pad with 3 spaces to align with "=> "
            try:
                self.stdscr.addnstr(row, 0, text, w - 1, attr)
            except curses.error:
                pass  # Terminal too narrow - skip this TOC entry
            row += 1
        
        # Show navigation hint at bottom
        hint = "↑/↓ or j/k: navigate | Enter/Right: jump | q/Esc: back"
        try:
            self.stdscr.addnstr(h - 1, 0, hint.ljust(max(0, w - 1)), w - 1, self.footer_attr)
        except curses.error:
            pass  # Terminal too narrow - skip navigation hint
        
        self.stdscr.refresh()

    def search_prompt(self):
        query = self.prompt("Search: ").strip()
        if not query:
            self.show_info_popup("Search", "Search cancelled")
            return
        if not self.search(query):
            self.show_info_popup("Search", f"Not found: {query}")

    def search(self, query: str) -> bool:
        q = " ".join(ascii_sanitize(query).lower().split())
        start_ch = self.chapter_index
        for offset in range(len(self.book.chapters)):
            ch_idx = (start_ch + offset) % len(self.book.chapters)
            # Search against the styled pages that are actually rendered,
            # so the page calculation matches what the user sees.
            styled_pages = self._get_styled_pages(ch_idx)
            # Build one normalized string per rendered page, then search the
            # joined chapter so phrases crossing line or page boundaries work.
            page_texts = [
                " ".join(
                    " ".join(''.join(
                        fragment_text for fragment_text, _ in line_fragments
                    ).split())
                    for line_fragments in page
                ).lower()
                for page in styled_pages
            ]
            chapter_text = " ".join(page_texts)
            match_pos = chapter_text.find(q)
            if match_pos != -1:
                cursor = 0
                page_idx = 0
                for index, page_text in enumerate(page_texts):
                    if match_pos <= cursor + len(page_text):
                        page_idx = index
                        break
                    cursor += len(page_text) + 1
                self.chapter_index = ch_idx
                self.page_index = page_idx
                self.show_info_popup("Search", "Found in chapter %d" % (ch_idx + 1))
                return True
        return False

    def set_bookmark(self):
        self.store.set_bookmark(self.book.path, self.chapter_index, self.page_index)
        self.store.set_state(self.book.path, BookState(self.chapter_index, self.page_index))
        self.store.save()
        self.show_info_popup("Bookmark", "Bookmark saved")

    def open_file_picker(self):
        start_dir = os.path.dirname(self.book.path) if self.book.path else os.getcwd()
        picker = FilePicker(self.stdscr, start_dir)
        selected = picker.run()
        if not selected:
            self.show_info_popup("Load", "Load cancelled")
            return
        self._save_position()
        try:
            new_book = EpubBook(selected, use_css=self.book.use_css)
        except Exception as exc:
            self.show_info_popup("Error", f"Failed to open: {exc}", is_error=True)
            return
        # Only close the active book after the replacement has loaded fully.
        self.book.close()
        self.load_book(new_book, use_saved_position=True)


def usage() -> str:
    return (
        "Usage: termepub.py [book.epub] [--bookmark] [--no-css]\n\n"
        "Controls:\n"
        "  Left / Right  previous/next page\n"
        "  Up / Down     previous/next chapter\n"
        "  t             table of contents\n"
        "  /             search\n"
        "  b             save bookmark\n"
        "  o             open book (file picker)\n"
        "  s             in picker: start live search/filter (type to filter)\n"
        "  j             in picker: jump; in reader: toggle justify\n"
        "  m             toggle dark/light mode\n"
        "  h             help\n"
        "  H             toggle top title bar\n"
        "  g             toggle heading style (bold/reverse)\n"
        "  d             select a word for dictionary lookup\n"
        "  ?             type a word for dictionary lookup\n"
        "  q             quit\n"
        "\n"
        "Options:\n"
        "  --bookmark    open book at saved bookmark position\n"
        "  --no-css      disable inline CSS styling (faster on slow devices)\n"
        "  --version     show version number and exit\n"
        "\n"
        "CSS Support:\n"
        "  Inline CSS styling is now rendered (bold, underline, colors).\n"
        "  Uses --no-css to disable on slow devices.\n"
    )


def main(argv: List[str]) -> int:
    # Set TERM if not set or invalid (for running directly on Gemini)
    if not os.environ.get('TERM') or os.environ.get('TERM') == 'dumb':
        os.environ['TERM'] = 'xterm'
    
    if len(argv) >= 2 and argv[1] == "--version":
        print(f"termepub-reader {__version__}")
        return 0
    if len(argv) >= 2 and argv[1] in {"-h", "--help"}:
        sys.stdout.write(usage())
        return 0

    epub_path = None
    open_bookmark = False
    use_css = True
    if len(argv) >= 2:
        epub_path = argv[1]
        open_bookmark = "--bookmark" in argv[2:]
        use_css = "--no-css" not in argv[2:]

    store = StateStore()

    def runner(stdscr):
        if epub_path:
            if not os.path.exists(epub_path):
                raise FileNotFoundError(f"File not found: {epub_path}")
            initial_book = EpubBook(epub_path, use_css=use_css)
        else:
            last_book_path = store.get_last_book_path()
            if last_book_path and os.path.exists(last_book_path):
                initial_book = EpubBook(last_book_path, use_css=use_css)
            else:
                picker = FilePicker(stdscr, os.getcwd())
                selected = picker.run()
                if not selected:
                    return
                initial_book = EpubBook(selected, use_css=use_css)

        if open_bookmark:
            bm = store.get_bookmark(initial_book.path)
            if bm:
                store.set_state(initial_book.path, bm)
                store.save()

        ui = ReaderUI(stdscr, initial_book, store)
        ui.run()

    try:
        curses.wrapper(runner)
        return 0
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except zipfile.BadZipFile:
        sys.stderr.write(f"Not a valid EPUB/ZIP file: {epub_path or 'selected file'}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"Failed to open EPUB: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
