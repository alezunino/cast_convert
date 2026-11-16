from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

from cast_convert.core.convert.run import get_new_path
from cast_convert.core.convert.transcode import transcode_to
from cast_convert.core.media.codecs import (
  AudioCodec,
  Container,
  VideoCodec,
  container_supports_codec,
)
from cast_convert.core.media.formats import Formats
from cast_convert.core.media.profiles import AudioProfile, VideoProfile
from cast_convert.core.model.device import load_device_with_name
from cast_convert.core.model.video import Video
from cast_convert.core.types import Fps, Level, Resolution


DEVICE = load_device_with_name('Chromecast 1st Gen')


def make_video(
  name: str,
  container: Container,
  video_codec: VideoCodec,
  audio_codec: AudioCodec,
  suffix: str,
) -> Video:
  return Video(
    name=name,
    path=Path('/tmp') / f'{name}{suffix}',
    formats=Formats(
      container=container,
      video_profile=VideoProfile(
        codec=video_codec,
        resolution=Resolution.new(1280, 720),
        fps=Fps('30'),
        level=Level('1'),
      ),
      audio_profile=AudioProfile(audio_codec),
      subtitle=None,
    ),
    data=cast(Any, None),
  )


class ContainerCodecCompatTest(unittest.TestCase):
  def test_container_support_lookup(self):
    self.assertFalse(container_supports_codec(Container.webm, VideoCodec.avc))
    self.assertTrue(container_supports_codec(Container.matroska, VideoCodec.avc))
    self.assertTrue(container_supports_codec(Container.webm, VideoCodec.vp9))
    # Codecs with no declared restriction don't force a container change.
    self.assertTrue(container_supports_codec(Container.webm, VideoCodec.unknown))

  def test_video_codec_change_switches_webm_to_matroska(self):
    video = make_video('vp9', Container.webm, VideoCodec.vp9, AudioCodec.opus, '.webm')
    formats = transcode_to(DEVICE, video)

    self.assertIsNotNone(formats)
    self.assertIs(formats.container, Container.matroska)
    self.assertEqual(get_new_path(video, formats), Path('/tmp/vp9_transcoded.mkv'))

  def test_audio_codec_change_switches_webm_to_matroska(self):
    video = make_video('dts', Container.webm, VideoCodec.vp8, AudioCodec.dts, '.webm')
    formats = transcode_to(DEVICE, video)

    self.assertIsNotNone(formats)
    self.assertIs(formats.container, Container.matroska)
    self.assertIs(formats.audio_profile.codec, AudioCodec.mp3)

  def test_compatible_container_is_left_unchanged(self):
    video = make_video('hevc', Container.mp4, VideoCodec.hevc, AudioCodec.aac, '.mp4')
    formats = transcode_to(DEVICE, video)

    self.assertIsNotNone(formats)
    self.assertIsNone(formats.container)
    self.assertEqual(get_new_path(video, formats), Path('/tmp/hevc_transcoded.mp4'))


if __name__ == '__main__':
  unittest.main()
