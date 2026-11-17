from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cast_convert.core.convert.progress import (
  OSC_CLEAR,
  OSC_INDETERMINATE,
  ProgressReporter,
  get_duration_ms,
  osc_progress,
  parse_out_time,
  percent_done,
)
from cast_convert.core.convert.run import transcode_video
from cast_convert.core.model.video import Video


class FakeProcess:
  def __init__(self, lines: list[bytes], code: int = 0) -> None:
    self.stdout = iter(lines)
    self.stderr = iter([b''])
    self.code = code

  def wait(self) -> int:
    return self.code

  def poll(self) -> int:
    return self.code

  def kill(self) -> None:
    pass


class FakeStream:
  def __init__(self, process: FakeProcess) -> None:
    self.process = process

  def global_args(self, *args: str) -> FakeStream:
    return self

  def run_async(self, **kwargs: object) -> FakeProcess:
    return self.process


class ProgressHelpersTest(unittest.TestCase):
  def test_parse_out_time(self):
    self.assertEqual(parse_out_time('00:00:02.000000'), 2.0)
    self.assertEqual(parse_out_time('01:02:03.500000'), 3723.5)
    self.assertIsNone(parse_out_time('N/A'))
    self.assertIsNone(parse_out_time(''))

  def test_osc_progress(self):
    self.assertEqual(osc_progress(42), '\x1b]9;4;1;42\x07')
    self.assertEqual(osc_progress(-1), '\x1b]9;4;1;0\x07')
    self.assertEqual(osc_progress(101), '\x1b]9;4;1;100\x07')

  def test_percent_done_caps_at_99_until_done(self):
    self.assertEqual(percent_done(1, 2000), 50)
    self.assertEqual(percent_done(10, 2000), 99)

  def test_get_duration_ms(self):
    video = SimpleNamespace(
      path=Path('/tmp/video.mp4'),
      data=SimpleNamespace(
        general_tracks=[SimpleNamespace(duration='2000')],
        video_tracks=[],
      ),
    )

    self.assertEqual(get_duration_ms(video), 2000.0)

  def test_get_duration_ms_no_duration(self):
    video = SimpleNamespace(
      path=Path('/tmp/video.mp4'),
      data=SimpleNamespace(
        general_tracks=[SimpleNamespace(duration=None)],
        video_tracks=[],
      ),
    )

    self.assertIsNone(get_duration_ms(video))


class ProgressReporterTest(unittest.TestCase):
  def setUp(self) -> None:
    self.reporter = ProgressReporter()
    self.osc_writes: list[str] = []
    self.reporter._write_osc = lambda seq: self.osc_writes.append(seq)

  def test_handle_line_updates_percentage(self):
    task = self.reporter._progress.add_task('video.mp4', total=100)

    self.reporter._handle_line(b'out_time=00:00:01.000000\n', task, 2000)
    self.assertEqual(self.reporter._percents[task], 50)

    self.reporter._handle_line(b'progress=end\n', task, 2000)
    self.assertEqual(self.reporter._percents[task], 100)

  def test_aggregate_osc_is_average_of_active_tasks(self):
    first = self.reporter._progress.add_task('one', total=100)
    second = self.reporter._progress.add_task('two', total=100)

    self.reporter._set_percent(first, 40)
    self.reporter._set_percent(second, 60)

    self.assertEqual(self.osc_writes[-1], osc_progress(50))

  def test_run_cleans_up_task_and_clears_osc(self):
    process = FakeProcess([b'out_time=00:00:01.000000\n', b'progress=end\n'])

    self.reporter.run(FakeStream(process), 'video.mp4', 2000)

    self.assertFalse(self.reporter._percents)
    self.assertEqual(self.osc_writes[-1], OSC_CLEAR)

  def test_unknown_duration_uses_indeterminate_state(self):
    process = FakeProcess([b'progress=end\n'])

    self.reporter.run(FakeStream(process), 'video.mp4', None)

    self.assertEqual(self.osc_writes[0], OSC_INDETERMINATE)
    self.assertEqual(self.osc_writes[-1], OSC_CLEAR)

  def test_run_failure_raises_ffmpeg_error(self):
    import ffmpeg

    process = FakeProcess([b'progress=end\n'], code=1)

    with self.assertRaises(ffmpeg.Error):
      self.reporter.run(FakeStream(process), 'video.mp4', 2000)


class VerboseSelectionTest(unittest.TestCase):
  def test_no_reporter_uses_plain_ffmpeg_run(self):
    stream = MagicMock()
    converted = Path('/tmp/video_transcoded.mp4')

    with (
      patch('cast_convert.core.convert.run.get_stream', return_value=(stream, converted)),
      patch('cast_convert.core.convert.run.get_ffmpeg_cmd', return_value='ffmpeg -i in out'),
      patch.object(Video, 'from_path', return_value=MagicMock()),
    ):
      transcode_video(MagicMock(path=Path('/tmp/video.mp4')), MagicMock())

    stream.run.assert_called_once_with()


if __name__ == '__main__':
  unittest.main()
