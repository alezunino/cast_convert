from __future__ import annotations

import logging
import os
import re
import sys
import threading
from collections import deque
from collections.abc import Iterable
from typing import Final

import ffmpeg
from ffmpeg.nodes import OutputStream
from rich.progress import (
  BarColumn,
  Progress,
  TaskID,
  TaskProgressColumn,
  TextColumn,
  TimeElapsedColumn,
)

from ..model.video import Video


log = logging.getLogger(__name__)

OSC_PREFIX: Final[str] = '\x1b]9;4;'
OSC_END: Final[str] = '\x07'

OSC_CLEAR: Final[str] = f'{OSC_PREFIX}0{OSC_END}'
OSC_INDETERMINATE: Final[str] = f'{OSC_PREFIX}3{OSC_END}'

# Keep FFmpeg's stats off stderr, report machine-readable progress on stdout.
PROGRESS_ARGS: Final[tuple[str, ...]] = (
  '-nostats', '-loglevel', 'error', '-progress', 'pipe:1',
)

TIME_PATTERN: Final[re.Pattern[str]] = re.compile(
  r'^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$'
)

# Only the tail of each stream is needed for an error message; a watch process
# can run for hours, so don't accumulate every progress report in memory.
ERROR_TAIL: Final[int] = 100


def osc_progress(percent: int) -> str:
  """Build an OSC 9;4 sequence that sets the terminal progress bar."""
  return f'{OSC_PREFIX}1;{max(0, min(100, percent))}{OSC_END}'


def parse_out_time(value: str) -> float | None:
  """Convert FFmpeg's ``HH:MM:SS.ffffff`` progress value to seconds."""
  if not (match := TIME_PATTERN.match(value.strip())):
    return None

  hours, minutes, seconds = match.groups()
  return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def get_duration_ms(video: Video) -> float | None:
  """Get a video's duration from MediaInfo, in milliseconds."""
  for track in (*video.data.general_tracks, *video.data.video_tracks):
    if duration := getattr(track, 'duration', None):
      try:
        return float(duration)
      except (TypeError, ValueError):
        log.debug('Invalid duration for %s: %s', video.path, duration)

  return None


def percent_done(elapsed_s: float, duration_ms: float) -> int:
  """Map elapsed time to 0-99, reserving 100% for a completed encode."""
  return max(0, min(99, int(elapsed_s * 1000 / duration_ms * 100)))


class ProgressReporter:
  """Show per-file progress bars and drive the terminal's OSC 9;4 bar."""

  def __init__(self) -> None:
    self._progress = Progress(
      TextColumn('{task.description}'),
      BarColumn(),
      TaskProgressColumn(),
      TimeElapsedColumn(),
      transient=True,
    )
    self._lock = threading.Lock()
    self._percents: dict[TaskID, int] = {}
    self._indeterminate: set[TaskID] = set()
    self._last_osc: str | None = None

  def __enter__(self) -> ProgressReporter:
    self._progress.start()
    return self

  def __exit__(self, *exc: object) -> None:
    self._progress.stop()
    with self._lock:
      self._write_osc(OSC_CLEAR)
      self._last_osc = None

  def run(
    self,
    stream: OutputStream,
    description: str,
    duration_ms: float | None = None,
  ) -> None:
    """Run ``stream`` while reporting its progress, then clean up the task."""
    task = self._progress.add_task(
      description,
      total=100 if duration_ms else None,
    )

    with self._lock:
      if not duration_ms:
        self._indeterminate.add(task)
      self._publish()

    try:
      self._run_stream(stream, task, duration_ms)

    finally:
      with self._lock:
        self._percents.pop(task, None)
        self._indeterminate.discard(task)
        self._progress.remove_task(task)
        self._publish()

  def _run_stream(
    self,
    stream: OutputStream,
    task: TaskID,
    duration_ms: float | None,
  ) -> None:
    process = stream.global_args(*PROGRESS_ARGS).run_async(
      pipe_stdout=True,
      pipe_stderr=True,
    )
    out: deque[bytes] = deque(maxlen=ERROR_TAIL)
    err: deque[bytes] = deque(maxlen=ERROR_TAIL)
    stderr_thread = threading.Thread(
      target=_drain, args=(process.stderr, err), daemon=True,
    )
    stderr_thread.start()

    try:
      for line in process.stdout:
        out.append(line)
        self._handle_line(line, task, duration_ms)

      stderr_thread.join()
      if code := process.wait():
        raise ffmpeg.Error('ffmpeg', b''.join(out), b''.join(err))

    finally:
      if process.poll() is None:
        process.kill()
      process.wait()

  def _handle_line(
    self,
    line: bytes,
    task: TaskID,
    duration_ms: float | None,
  ) -> None:
    key, sep, value = line.decode(errors='replace').strip().partition('=')
    if not sep:
      return

    if key == 'out_time' and duration_ms:
      if (elapsed := parse_out_time(value)) is not None:
        self._set_percent(task, percent_done(elapsed, duration_ms))

    elif key == 'progress' and value == 'end':
      self._set_percent(task, 100)

  def _set_percent(self, task: TaskID, percent: int) -> None:
    with self._lock:
      self._percents[task] = percent
      self._progress.update(task, completed=percent)
      self._publish()

  def _publish(self) -> None:
    """Update the terminal bar with the average across active encodes."""
    if self._indeterminate:
      osc = OSC_INDETERMINATE
    elif self._percents:
      average = sum(self._percents.values()) // len(self._percents)
      osc = osc_progress(average)
    else:
      osc = OSC_CLEAR

    if osc != self._last_osc:
      self._write_osc(osc)
      self._last_osc = osc

  def _write_osc(self, sequence: str) -> None:
    try:
      fd = sys.stdout.fileno()
      # Rich's Live replaces sys.stdout with a proxy whose isatty() is False,
      # so ask the file descriptor itself whether it's a terminal.
      if not os.isatty(fd):
        return

      # One atomic write keeps the sequence intact beside Rich's redraws.
      os.write(fd, sequence.encode('ascii'))

    except (AttributeError, OSError, ValueError) as e:
      log.debug('Cannot write terminal progress: %s', e)


def _drain(source: Iterable[bytes], sink: deque[bytes]) -> None:
  for line in source:
    sink.append(line)
