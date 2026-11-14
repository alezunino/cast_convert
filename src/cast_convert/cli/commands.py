from __future__ import annotations

from asyncio import run
from pathlib import Path
from typing import Final

from rich import print
from typer import Argument, Context, Exit, Option, Typer
from typer.models import ArgumentInfo, OptionInfo

from .helpers import _get_command, _inspect, inspect_directory, show_devices
from .. import CLI_ENTRY, COPYRIGHT_NOTICE, DESCRIPTION, LICENSE, PROJECT_HOME, __version__
from ..core.base import DEFAULT_JOBS, DEFAULT_LOG_LEVEL, DEFAULT_MODEL, \
  DEFAULT_THREADS, bad_file_exit, setup_logging
from ..core.enums import LogLevel, Rc, Strategy

from ..core.convert.run import convert_paths
from ..core.convert.watch import convert_videos
from ..core.model.device import get_devices_from_file


THREAD_COUNT: Final[int] = max(int(DEFAULT_THREADS / DEFAULT_JOBS), 1)


DEFAULT_NAME_OPT: Final[OptionInfo] = Option(
  DEFAULT_MODEL,
  '--name', '-n',
  help='Device model name.',
)

DEFAULT_PATHS_ARG: Final[ArgumentInfo] = Argument(
  default=...,
  help='Path(s) to video(s).',
  resolve_path=True,
  metavar='PATHS',
  show_default=False,
)

DEFAULT_REPLACE_OPT: Final[OptionInfo] = Option(
  False,
  '--replace', '-r',
  help='Replace original file with transcoded video.',
  show_default=True,
)

DEFAULT_THREADS_OPT: Final[OptionInfo] = Option(
  THREAD_COUNT,
  '--threads', '-t',
  help="Number of threads to tell FFMPEG to use per job.",
)

DEFAULT_JOBS_OPT: Final[OptionInfo] = Option(
  DEFAULT_JOBS,
  '--jobs', '-j',
  help="Number of simultaneous transcoding jobs.",
)

DEFAULT_LOG_OPT: Final[OptionInfo] = Option(
  DEFAULT_LOG_LEVEL,
  '--log-level', '-l',
  help="Set the minimum logging level.",
  show_default=True,
)

DEFAULT_STRATEGY_OPT: Final[OptionInfo] = Option(
  Strategy.quit,
  '--error', '-e',
  help="Set the error handling strategy.",
  show_default=True,
)

DEFAULT_VERSION_OPT: Final[OptionInfo] = Option(
  False,
  '--version', '-v',
  help="Show application version and quit.",
)

DEFAULT_DETAILS_OPT: Final[OptionInfo] = Option(
  False,
  '--details', '-d',
  help="Show detailed device information.",
)

DEFAULT_SUBTITLE_OPT: Final[ArgumentInfo] = Option(
  None,
  '--subtitle', '-s',
  help='Path to subtitle file to embed.',
  resolve_path=True,
  show_default=False,
)

DEFAULT_HWACCEL_OPT: Final[OptionInfo] = Option(
  True,
  '--hwaccel/--no-hwaccel',
  help='Use VAAPI hardware encoding when available. Use --no-hwaccel to force software encoding.',
  show_default=False,
)

DEFAULT_GPU_PIPELINE_OPT: Final[OptionInfo] = Option(
  False,
  '--gpu-pipeline/--no-gpu-pipeline',
  help='Decode and encode on the GPU with VAAPI. Requires VAAPI decoding for the source codec (checked with vainfo). Unsupported files fail with an error, handled by --error.',
  show_default=False,
)

LONG_DESCRIPTION: Final[str] = f"""
{DESCRIPTION}

See {PROJECT_HOME} for more information.
{COPYRIGHT_NOTICE}. License: {LICENSE}
"""

cli: Final[Typer] = Typer(
  no_args_is_help=True,
  help=LONG_DESCRIPTION,
  rich_markup_mode=None,
  name=CLI_ENTRY
)


@cli.command(
  no_args_is_help=True,
)
@bad_file_exit
def command(
  name: str = DEFAULT_NAME_OPT,
  paths: list[Path] = DEFAULT_PATHS_ARG,
  replace: bool = DEFAULT_REPLACE_OPT,
  threads: int = DEFAULT_THREADS_OPT,
  error: Strategy = DEFAULT_STRATEGY_OPT,
  subtitle: Path | None = DEFAULT_SUBTITLE_OPT,
  hwaccel: bool = DEFAULT_HWACCEL_OPT,
  gpu_pipeline: bool = DEFAULT_GPU_PIPELINE_OPT,
):
  """
  Get the FFmpeg transcoding command for each video.
  """
  rc: int = Rc.ok

  for path in paths:
    if _get_command(name, path, replace, threads, error, subtitle, hwaccel, gpu_pipeline):
      rc = Rc.must_convert

  raise Exit(rc)


@cli.command(
  no_args_is_help=True,
)
@bad_file_exit
def convert(
  name: str = DEFAULT_NAME_OPT,
  paths: list[Path] = DEFAULT_PATHS_ARG,
  replace: bool = DEFAULT_REPLACE_OPT,
  jobs: int = DEFAULT_JOBS_OPT,
  threads: int = DEFAULT_THREADS_OPT,
  error: Strategy = DEFAULT_STRATEGY_OPT,
  subtitle: Path | None = DEFAULT_SUBTITLE_OPT,
  hwaccel: bool = DEFAULT_HWACCEL_OPT,
  gpu_pipeline: bool = DEFAULT_GPU_PIPELINE_OPT,
):
  """
  Convert videos so that they're compatible with the specified device.
  """
  coro = convert_paths(
    name,
    replace,
    threads,
    jobs,
    *paths,
    strategy=error,
    subtitle=subtitle,
    hardware=hwaccel,
    gpu_pipeline=gpu_pipeline,
  )
  run(coro)


@cli.command(
  no_args_is_help=True,
)
@bad_file_exit
def inspect(
  name: str = DEFAULT_NAME_OPT,
  paths: list[Path] = DEFAULT_PATHS_ARG,
  error: Strategy = DEFAULT_STRATEGY_OPT,
):
  """
  Inspect videos to see which attributes would be transcoded.
  """
  rc: int = Rc.ok

  for path in paths:
    if path.is_dir():
      rc = inspect_directory(name, path, error) or rc

    elif _inspect(name, path, error):
      rc = Rc.must_convert

  raise Exit(rc)


@cli.command()
def devices(
  details: bool = DEFAULT_DETAILS_OPT,
):
  """
  List all supported devices.
  """
  _devices = get_devices_from_file()

  print('You can use these device names with the --name flag:')
  show_devices(_devices, details)


@cli.command(
  no_args_is_help=True,
)
@bad_file_exit
def watch(
  name: str = DEFAULT_NAME_OPT,
  paths: list[Path] = DEFAULT_PATHS_ARG,
  jobs: int = DEFAULT_JOBS_OPT,
  replace: bool = DEFAULT_REPLACE_OPT,
  threads: int = DEFAULT_THREADS_OPT,
  error: Strategy = DEFAULT_STRATEGY_OPT,
  subtitle: Path | None = DEFAULT_SUBTITLE_OPT,
  hwaccel: bool = DEFAULT_HWACCEL_OPT,
  gpu_pipeline: bool = DEFAULT_GPU_PIPELINE_OPT,
):
  """
  Watch directories for new or modified videos and convert them.
  """
  coro = convert_videos(
    *paths,
    device=name,
    jobs=jobs,
    replace=replace,
    threads=threads,
    error=error,
    subtitle=subtitle,
    hardware=hwaccel,
    gpu_pipeline=gpu_pipeline,
  )
  run(coro)


@cli.callback(
  invoke_without_command=True,
  no_args_is_help=True,
)
def main(
  ctx: Context,
  log_level: LogLevel = DEFAULT_LOG_OPT,
  version: bool = DEFAULT_VERSION_OPT,
):
  setup_logging(log_level)

  if version:
    print(f'v{__version__}')
    raise Exit(Rc.ok)

  if not ctx.invoked_subcommand:
    print('You need to supply a command.')
    raise Exit(Rc.no_command)
