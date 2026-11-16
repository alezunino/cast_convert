import logging
from asyncio import BoundedSemaphore, TaskGroup, gather, sleep, to_thread
from collections.abc import AsyncIterable
from pathlib import Path

import psutil
from aiopath import AsyncPath
from watchfiles import Change, awatch

from .run import convert_from_name_path
from ..base import DEFAULT_JOBS, DEFAULT_MODEL, DEFAULT_REPLACE, DEFAULT_THREADS, \
  FILESIZE_CHECK_WAIT, NO_SIZE, get_error_handler
from ..enums import Strategy
from ..exceptions import ConversionFailed, GpuPipelineError, UnknownFormat
from ..model.video import Video
from ..types import Paths


log = logging.getLogger(__name__)


def is_open_in_proc(file: Path | str) -> bool:
  """Return whether any process currently has ``file`` open.

  This scans /proc, so it must be run off the event loop (see
  ``wait_until_closed``).  Comparing paths directly instead of building a
  set of ``Path`` objects for every open file descriptor keeps the scan
  cheap, and only the relevant psutil errors are handled at debug level.
  """
  target = Path(file)

  for proc in psutil.process_iter():
    try:
      if any(Path(f.path) == target for f in proc.open_files()):
        return True

    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError) as e:
      log.debug("Can't read open files for %s: %s", proc.pid, e)

  return False


async def wait_until_closed(
  file: Path | str,
  wait: float = FILESIZE_CHECK_WAIT,
) -> Path:
  file = Path(file)

  # is_open_in_proc() scans every process; run it in a worker thread so it
  # never blocks other concurrent conversions on the event loop.
  while await to_thread(is_open_in_proc, file):
    await sleep(wait)

  return file


async def wait_for_stable_size(
  file: str | Path,
  wait: float = FILESIZE_CHECK_WAIT,
  previous: int = NO_SIZE,
) -> int:
  path: AsyncPath = AsyncPath(file)

  while True:
    try:
      result = await path.stat()
      size: int = result.st_size

      if size == previous:
        return size

      previous = size
      await sleep(wait)

    except Exception as e:
      log.exception(e)
      previous = NO_SIZE


async def is_video(path: Path) -> bool:
  try:
    video = await to_thread(Video.from_path, path)

  except Exception as e:
    log.exception(e)
    log.error(f'Not a video: {path}')
    return False

  if video.formats.video_profile:
    return True

  log.error(f'Not a video: {path}')
  return False


def get_new_path(file: str, change: Change, seen: Paths) -> Path | None:
  path = Path(file)

  if path in seen:
    return None

  seen.add(path)

  match change:
    case Change.added | Change.modified:
      return path


async def gen_new_files(
  *paths: Path,
  seen: Paths | None = None
) -> AsyncIterable[Path]:
  if seen is None:
    seen = Paths()

  async for changes in awatch(*paths):
    for change, file in changes:
      if path := get_new_path(file, change, seen):
        yield path


async def convert(
  device: str,
  path: Path,
  sem: BoundedSemaphore,
  replace: bool = DEFAULT_REPLACE,
  threads: int = DEFAULT_THREADS,
  subtitle: Path | None = None,
  hardware: bool = True,
  gpu_pipeline: bool = False,
) -> Video | None:
  path = path.absolute()

  async with sem:
    await gather(wait_for_stable_size(path), wait_until_closed(path))

    if not await is_video(path):
      return None

    try:
      return await to_thread(
        convert_from_name_path, device, path, replace, threads, subtitle, hardware, gpu_pipeline,
      )
    except ConversionFailed:
      return None


async def convert_videos(
  *paths: Path,
  device: str = DEFAULT_MODEL,
  seen: Paths | None = None,
  jobs: int = DEFAULT_JOBS,
  replace: bool = DEFAULT_REPLACE,
  threads: int = DEFAULT_THREADS,
  error: Strategy = Strategy.quit,
  subtitle: Path | None = None,
  hardware: bool = True,
  gpu_pipeline: bool = False,
):
  if seen is None:
    seen = Paths()

  sem = BoundedSemaphore(jobs)
  handled_converter = get_error_handler(convert, UnknownFormat, GpuPipelineError, strategy=error)

  async with TaskGroup() as tg:
    async for path in gen_new_files(*paths, seen=seen):
      coro = handled_converter(device, path, sem, replace, threads, subtitle, hardware, gpu_pipeline)
      tg.create_task(coro)
