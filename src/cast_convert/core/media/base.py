from __future__ import annotations

import logging
from enum import StrEnum, auto
from typing import Self, Type

from ..protocols import get_name
from ..types import WithName
from ..fmt import normalize
from ..parse import ALIAS_FMTS


log = logging.getLogger(__name__)


class NormalizedFormat(WithName):
  unknown: Self | str

  def __bool__(self) -> bool:
    return self != self.unknown

  def __repr__(self) -> str:
    return f"{get_name(self)}({self})"

  @classmethod
  def _missing_(cls: Type[Self], value: str) -> Self:
    name = get_name(cls)
    log.info("[%s] Missing: %s", name, value)

    if alias := getattr(cls, value, None):
      log.info("[%s] Using %s as an alias for %s", name, alias, value)
      return alias

    if alias := ALIAS_FMTS.get(value):
      log.info("[%s] Using %s as an alias for %s", name, alias, value)
      return cls(alias)

    log.info("[%s] Not found, using `unknown` instead of %s", name, value)
    return cls.unknown

  @classmethod
  def from_info(cls: Type[Self], info: str | None) -> Self:
    name = get_name(cls)

    if not info:
      log.info("[%s] no info supplied: %s", name, info)
      return cls.unknown

    if not isinstance(info, str):
      raise TypeError(f"[{name}] Can't normalize: {info}")

    normalized = normalize(info)
    log.debug('%s(%s) normalized as %s(%s)', name, info, name, normalized)

    return cls(normalized)


class OnTranscodeErr(NormalizedFormat, StrEnum):
  cycle_video_encoders: OnTranscodeErr = auto()
  cycle_audio_encoders: OnTranscodeErr = auto()
