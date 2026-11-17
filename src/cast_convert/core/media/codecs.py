from __future__ import annotations

import logging
from enum import Enum, StrEnum, auto
from functools import cache
from typing import Self

from .base import NormalizedFormat
from ..base import SUBTITLE_SEP
from ..parse import CODEC_CONTAINER_COMPAT, EXTENSIONS, Extension


log = logging.getLogger(__name__)


def alias[E: Enum | str](val: E) -> E:
  """Denotes an Enum's alias"""
  return val


class Container(NormalizedFormat, StrEnum):
  """File Container"""
  avi = auto()
  matroska = auto()
  mkv = alias(matroska)
  mp2t = auto()
  mp3 = auto()
  mp4 = auto()
  mp41 = alias(mp4)
  mp42 = alias(mp4)
  mpegts = auto()
  isom = alias(mp4)
  iso4 = alias(isom)
  mpeg4 = alias(mp4)
  ogg = auto()
  wav = auto()
  webm = auto()
  invalid = auto()
  unknown = auto()

  def to_extension(self) -> Extension | None:
    if ext := EXTENSIONS.get(self):
      return ext

    log.warning("Can't find %s in EXTENSIONS=%s", self.name, EXTENSIONS)
    return None


class Codec(NormalizedFormat, StrEnum):
  pass


class VideoCodec(Codec):
  """Video Codec"""
  avc = auto()
  div3 = auto()
  divx = alias(div3)
  h264 = alias(avc)
  hdr = auto()
  hevc = auto()
  h265 = alias(hevc)
  mp4 = alias(avc)
  mpeg4 = auto()
  mpeg4visual = alias(divx)
  vp8 = auto()
  vp9 = auto()
  vp09 = alias(vp9)
  xvid = auto()
  unknown = auto()


class AudioCodec(Codec):
  """Audio Codec"""
  aac = auto()
  ac3 = auto()
  eac3 = auto()
  eacs = auto()
  dts = auto()
  flac = auto()
  heaac = auto()
  lcaac = auto()
  mpegaudio = auto()
  mp2 = alias(mpegaudio)
  mp3 = auto()
  mp4a = auto()
  mp4a6b = alias(mp4a)
  opus = auto()
  vorbis = auto()
  wav = auto()
  webm = auto()
  wma = auto()
  unknown = auto()


class Subtitle(NormalizedFormat, StrEnum):
  ass = auto()
  eia608 = auto()
  eia708 = auto()
  srt = auto()
  utf8 = alias(srt)
  ssa = auto()
  ttml = auto()
  timedtext = alias(ttml)
  unknown = auto()
  webvtt = auto()
  vtt = alias(webvtt)
  dwebvtt = alias(webvtt)

  @classmethod
  def from_info(cls: type[Self], info: str | None) -> Self | None:
    if not info:
      return None

    elif SUBTITLE_SEP in info:
      info, *_ = info.split(SUBTITLE_SEP)

    info = info.strip()
    return super().from_info(info)


type Codecs = AudioCodec | VideoCodec

Containers = list[Container]
Subtitles = list[Subtitle]


@cache
def containers_for_codec(codec: Codecs | Subtitle) -> frozenset[Container]:
  """Containers declared as compatible with ``codec`` (cached)."""
  return frozenset(
    Container.from_info(name)
    for name in CODEC_CONTAINER_COMPAT.get(str(codec), ())
  )


def container_supports_codec(
  container: Container | None,
  codec: Codecs | Subtitle | None,
) -> bool:
  """Whether ``container`` can carry ``codec``.

  Codecs with no declared restriction are treated as compatible, so unknown
  or not-yet-mapped codecs never trigger a spurious container change.
  """
  if not container or container in (Container.unknown, Container.invalid):
    return True

  if not codec:
    return True

  containers = containers_for_codec(codec)

  return not containers or container in containers
