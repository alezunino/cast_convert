from __future__ import annotations

from enum import IntEnum, StrEnum, auto
from typing import Self


class LogLevel(StrEnum):
  debug = auto()
  info = auto()
  warn = auto()
  error = auto()
  critical = auto()
  fatal = auto()


class Strategy(StrEnum):
  quit = auto()
  skip = auto()
  force = auto()


class Rc(IntEnum):
  """Return codes"""
  ok: Self = 0
  err = auto()

  no_command = 2
  # Exit codes stay stable after removing unused members (3, 6 and 7).
  no_matching_device = 4
  must_convert = 5
