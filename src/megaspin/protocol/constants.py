"""Protocol constants (see docs/RS232_Protokoll_Spezifikation.md)."""
from enum import IntEnum

ENQ, ACK, NAK, EOT, STX = 0x05, 0x06, 0x15, 0x04, 0x02
CONTROL_BYTES = {ENQ: "ENQ", ACK: "ACK", NAK: "NAK", EOT: "EOT"}

BAUDRATE = 9600
MAX_SLOTS = 200
MEMORY_TITLE_LEN = 25        # changer memory keeps 25 characters per title
MEMORY_MAX_TRACKS = 20       # changer memory holds titles for tracks 1..20


class FrameType(IntEnum):
    HELLO = 0x00
    CMD = 0x03
    MINMAX = 0x04
    TOC = 0x06
    USER_FILES = 0x07
    MUSIC_TYPE = 0x08
    RESULT = 0x09
    KEY = 0x0A
    SELECT = 0x0B
    MODE = 0x0C
    PROGRAM = 0x0D
    STATUS = 0x12
    PLAY_STATE = 0x13
    DISC_LOADED = 0x14
    EVENT = 0x15
    CDTEXT = 0xFD
    TEXT = 0xFE


class Req(IntEnum):
    """Request codes in byte B (P[1]) of a 0x03 frame with A = 0x00."""
    TEXT = 0x01
    MINMAX = 0x02
    TOC = 0x04
    USER_FILES = 0x08
    MUSIC_TYPE = 0x10
    PROGRAM = 0x20


class Check(IntEnum):
    """Check/mode requests in byte A (P[0]) of a 0x03 frame (answer 0x09)."""
    MODE_PLAY = 0x10
    PROGRAM = 0x20
    USER_FILE_NAMES = 0x40
    TITLES = 0x80


class TextKind(IntEnum):
    """Byte B6 of text frames."""
    DISC_TITLE = 0
    TRACK_TITLE = 1
    USER_FILE_NAME = 7


KEYS: dict[str, tuple[int, int]] = {
    "play_pause": (0xA0, 0xCB),
    "stop": (0xA0, 0xC9),
    "repeat": (0xA0, 0xCC),
    "random": (0xA1, 0xD4),
    "prev": (0xA0, 0xCE),
    "next": (0xA0, 0xCF),
    "rew": (0xA0, 0x06),
    "ff": (0xA0, 0x07),
}
KEY_RELEASE = (0xFF, 0xFF)
HOLD_KEYS = {"ff", "rew"}          # press/release semantics
STEP_KEYS = {"next", "prev"}       # tap = press + release in two sessions

PLAY_STATES = {
    0x40: "stopped", 0x50: "stopping", 0x60: "searching", 0x70: "playing",
    0x80: "paused", 0x90: "ff", 0xA0: "rew",
}

# 0x12 P[7] -> (mode, random)
MODES = {
    0: ("track", "off"), 1: ("track", "one"), 2: ("track", "all"),
    3: ("program", "off"), 4: ("best_sel", "off"),
    5: ("music_type", "off"), 6: ("music_type", "all"),
    7: ("user_file", "off"), 8: ("user_file", "all"),
}

# UI index -> name; changer code = 0 if index == 0 else index + 1  (PROT §11.2)
MUSIC_TYPE_NAMES = [
    "Not Defined", "Adult Contemporary", "Alternative Rock", "Children's Music", "Classical",
    "Contemporary Christian", "Country", "Dance", "Easy Listening", "Erotic", "Folk", "Gospel",
    "Hip Hop", "Jazz", "Latin", "Musical", "New Age", "Opera", "Operetta", "Pop Music", "RAP",
    "Reggae", "Rock Music", "Rhythm & Blues", "Sound Effects", "Sound Track", "Spoken Word",
    "World Music",
]


def music_type_code(index: int) -> int:
    return 0 if index <= 0 else index + 1


def music_type_index(code: int) -> int:
    return 0 if code <= 1 else code - 1


def music_type_name(code: int) -> str:
    i = music_type_index(code)
    return MUSIC_TYPE_NAMES[i] if 0 <= i < len(MUSIC_TYPE_NAMES) else f"Code {code}"
