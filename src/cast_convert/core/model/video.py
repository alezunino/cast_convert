from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self, cast

from pymediainfo import MediaInfo

from ..base import (
  AT, LEVEL_SEP,
)
from ..types import DEFAULT_VIDEO_FPS, DEFAULT_VIDEO_LEVEL, Fps, Level, Resolution, VariableFps
from ..protocols import IsCompatible
from ..fmt import normalize
from ..media.codecs import AudioCodec, Container, Subtitle, VideoCodec
from ..media.formats import Formats, VideoFormat, is_compatible
from ..media.profiles import AudioProfile, VideoProfile
from ..parse import Yaml


log = logging.getLogger(__name__)


@dataclass
class Video(IsCompatible):
  name: str
  path: Path

  formats: Formats
  data: MediaInfo

  @classmethod
  def from_path(cls, path: Path | str) -> Self:
    path = Path(path)
    # parse_speed=1.0 reads less of the file while preserving every field we
    # use below (full=False does not: it drops file_extension and annotates
    # width/height with " pixels", breaking Resolution/Width conversion).
    data: MediaInfo = MediaInfo.parse(path, parse_speed=1.0)

    [general] = data.general_tracks
    title = general.file_name or general.complete_name

    container = Container.from_info(
      general.codec_id or
      general.format or
      general.file_extension
    )

    if exts := general.fileextension_invalid:
      log.error('%s has an invalid file extension, not in: %s', path, exts)

    if exts and container is Container.unknown:
      container = Container.invalid

    subtitle = Subtitle.from_info(general.text_codecs)

    video_profile = get_video_profile(data)
    audio_profile = get_audio_profile(data)

    formats = Formats(
      container=container,
      video_profile=video_profile,
      audio_profile=audio_profile,
      subtitle=subtitle,
    )

    return cls(
      name=title,
      path=path.absolute(),
      formats=formats,
      data=data,
    )

  def is_compatible(self, other: VideoFormat) -> bool:
    return is_compatible(self.formats, other)


def get_audio_profile(data: MediaInfo) -> AudioProfile | None:
  if not data.audio_tracks:
    return None

  audio, *_ = data.audio_tracks

  name: str = audio.codec_id_hint or audio.format
  codec = AudioCodec.from_info(name)

  return AudioProfile(codec)


def get_video_profile(data: MediaInfo) -> VideoProfile | None:
  if not data.video_tracks:
    return None

  [video] = data.video_tracks
  fmts = video.format, video.codec_id, video.codec_id_hint
  codec: VideoCodec = cast(VideoCodec, VideoCodec.unknown)

  for fmt in fmts:
    if (codec := VideoCodec.from_info(fmt)) is not VideoCodec.unknown:
      break

  resolution = Resolution.new(video.width, video.height)
  level = profile_to_level(video.format_profile)

  fps = Fps(video.original_frame_rate or video.frame_rate or DEFAULT_VIDEO_FPS)

  if not fps and (mode := video.frame_rate_mode):
    log.warning("Assuming variable frame rate: fps=%s, mode=%s", fps, mode)
    fps = VariableFps

  return VideoProfile(
    codec=codec,
    resolution=resolution,
    fps=fps,
    level=level,
  )


def profile_to_level(profile: str | None) -> Level:
  if not (level := profile):
    return DEFAULT_VIDEO_LEVEL

  match level.split(AT):
    case (name, level) | (name, level, _) if LEVEL_SEP in level:
      level = level.strip(LEVEL_SEP)

    case (name, level) | (name, level, _):
      level = level

    case [level] if level.isnumeric():
      return Level(level)

    case rest:
      log.warning("Unknown profile format: %s, using default.", rest)
      return DEFAULT_VIDEO_LEVEL

  log.debug("[Encoder profile] '%s' -> (name=%s, level=%s)", profile, name, level)

  if not (level := normalize(level, str.isnumeric)):
    log.warning("Cannot determine level from level=%s, non-numeric. Using default.", level)
    return DEFAULT_VIDEO_LEVEL

  match [*level]:
    case [val]:
      return Level(f'{val}.0')

    case big, *small:
      small = ''.join(small)
      return Level(f'{big}.{small}')

  log.warning("Cannot determine level from level=%s, using default.", level)
  return DEFAULT_VIDEO_LEVEL


def get_video_profiles(profiles: Yaml) -> Iterable[VideoProfile]:
  profile: Yaml
  attrs: Yaml

  for profile in profiles:
    [name, attrs], *_ = profile.items()
    codec = VideoCodec.from_info(name)

    if (resolution := attrs.get('resolution')) is not None:
      resolution = Resolution.from_str(resolution)

    if (fps := attrs.get('fps')) is not None:
      fps = Fps(fps)

    if (level := attrs.get('level')) is not None:
      level = Level(level)

    yield VideoProfile(
      codec=codec,
      resolution=resolution,
      fps=fps,
      level=level,
    )
