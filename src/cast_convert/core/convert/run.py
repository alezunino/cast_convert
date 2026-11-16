from __future__ import annotations

import logging
from asyncio import BoundedSemaphore, TaskGroup, to_thread
from collections.abc import Iterable
from enum import StrEnum, auto
from functools import cache
from pathlib import Path
from shlex import quote
from shutil import which
from subprocess import CalledProcessError, run
from typing import Final

import ffmpeg
from ffmpeg.nodes import FilterableStream, OutputStream

from .transcode import should_transcode, show_transcode_dismissal
from ..base import DEFAULT_REPLACE, DEFAULT_THREADS, JOIN_COMMAND, first, get_error_handler
from ..enums import Strategy
from ..exceptions import ConversionFailed, GpuPipelineError, UnknownFormat
from ..media.codecs import AudioCodec, Codecs, Container, Subtitle, VideoCodec
from ..media.formats import Formats
from ..model.device import load_device_with_name
from ..model.video import Video
from ..parse import AUDIO_ENCODERS, Alias, Aliases, Extension, SUBTITLE_ENCODERS, VIDEO_ENCODERS


log = logging.getLogger(__name__)

DOT: Final[str] = '.'

DEFAULT_EXT: Final[Extension] = Container.matroska.to_extension()
TRANSCODE_SUFFIX: Final[str] = '_transcoded'

SCALE_RESOLUTION: Final[int] = -2  # see: https://stackoverflow.com/a/29582287
VAAPI_SUFFIX: Final[str] = '_vaapi'
VAAPI_DECODE_ENTRYPOINT: Final[str] = 'VAEntrypointVLD'
VAAPI_DECODE_PROFILES: Final[dict[VideoCodec, str]] = {
  VideoCodec.avc: 'VAProfileH264',
  VideoCodec.hevc: 'VAProfileHEVC',
  VideoCodec.vp8: 'VAProfileVP8',
  VideoCodec.vp9: 'VAProfileVP9',
}
DRI_DIR: Final[Path] = Path('/dev/dri')


class FfmpegOpt(StrEnum):
  acodec = auto()
  vcodec = auto()
  scodec = auto()
  vprofile = auto()
  level = auto()
  fps = auto()
  r = auto()

  fflags = auto()
  movflags = auto()

  hwaccel = auto()
  hwaccel_device = auto()
  hwaccel_output_format = auto()
  vaapi_device = auto()
  format = auto()
  hwupload = auto()

  scale = auto()
  scale_vaapi = auto()
  threads = auto()

  vsync = auto()


class FfmpegArg(StrEnum):
  y = '-y'


class FfmpegVal(StrEnum):
  copy = auto()
  faststart = auto()
  nv12 = auto()
  vaapi = auto()

  genpts = '+genpts'
  scale_resolution = str(SCALE_RESOLUTION)

  vfr = auto()


type Option = FfmpegOpt | str
type Arg = FfmpegArg | str
type Val = FfmpegVal | str | float | int

type Args = list[Arg]
type Options = dict[Option, Val]


DEFAULT_OUTPUT_OPTS: Final[Options] = {
  FfmpegOpt.acodec: FfmpegVal.copy,
  FfmpegOpt.vcodec: FfmpegVal.copy,
  FfmpegOpt.scodec: FfmpegVal.copy,
  FfmpegOpt.movflags: FfmpegVal.faststart,
}

DEFAULT_INPUT_OPTS: Final[Options] = {
  FfmpegOpt.fflags: FfmpegVal.genpts,
}

GLOBAL_ARGS: Final[Args] = [
  FfmpegArg.y,
]

GLOBAL_OPTS: Final[Options] = {}


@cache
def get_vaapi_device() -> Path | None:
  return first(sorted(DRI_DIR.glob('renderD*')))


@cache
def get_vaapi_encoders() -> frozenset[str]:
  if not get_vaapi_device():
    return frozenset()

  try:
    result = run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True, check=True)
  except (OSError, CalledProcessError):
    return frozenset()

  encoders: set[str] = set()

  for line in result.stdout.splitlines():
    parts = line.split()

    if len(parts) > 1 and parts[1].endswith(VAAPI_SUFFIX):
      encoders.add(parts[1])

  return frozenset(encoders)


@cache
def get_vaapi_decoders() -> frozenset[str]:
  device = get_vaapi_device()

  if not device or not which('vainfo'):
    return frozenset()

  try:
    result = run(
      ['vainfo', '--display', 'drm', '--device', str(device)],
      capture_output=True,
      text=True,
      check=True,
    )
  except (OSError, CalledProcessError):
    return frozenset()

  decoders: set[str] = set()

  for line in result.stdout.splitlines():
    profile, sep, entrypoint = line.partition(':')

    if sep and entrypoint.strip() == VAAPI_DECODE_ENTRYPOINT:
      decoders.add(profile.strip())

  return frozenset(decoders)


def supports_vaapi_decode(codec: VideoCodec) -> bool:
  prefix = VAAPI_DECODE_PROFILES.get(codec)

  return prefix is not None and any(p.startswith(prefix) for p in get_vaapi_decoders())


def get_encoder(codec: Codecs | Subtitle, hardware: bool = False) -> Alias:
  encoders: Aliases

  match codec:
    case AudioCodec():
      encoders = AUDIO_ENCODERS[codec]

    case VideoCodec():
      encoders = VIDEO_ENCODERS[codec]

    case Subtitle():
      encoders = SUBTITLE_ENCODERS[codec]

    case obj:
      raise TypeError(f"{obj} not a codec")

  if hardware and (vaapi := first(e for e in encoders if e in get_vaapi_encoders())):
    return vaapi

  return first(e for e in encoders if not e.endswith(VAAPI_SUFFIX))


def transcode_video(
  video: Video,
  formats: Formats,
  replace: bool = DEFAULT_REPLACE,
  threads: int = DEFAULT_THREADS,
  subtitle: Path | None = None,
  hardware: bool = True,
  gpu_pipeline: bool = False,
) -> Video:
  stream, converted = get_stream(video, formats, threads, replace, subtitle, hardware, gpu_pipeline)
  cmd = get_ffmpeg_cmd(stream, video.path)

  log.info('Running command: %s', cmd)

  try:
    stream.run()  # type: ignore

  except ffmpeg.Error:
    if not hardware or gpu_pipeline or VAAPI_SUFFIX not in cmd:
      raise

    log.warning('VAAPI encoding failed, retrying with software encoding')
    return transcode_video(video, formats, replace, threads, subtitle, hardware=False)

  original: Path = video.path

  if replace and converted:
    if original != (new_name := original.with_suffix(converted.suffix)):
      original.unlink(missing_ok=True)

    converted = converted.rename(new_name)

  return Video.from_path(converted)


def get_ffmpeg_cmd(
  stream: OutputStream,
  path: Path,
) -> str:
  parent: Path = path.parent

  args: Iterable[str] = (
    quote(arg) if Path(arg).parent == parent else arg
    for arg in stream.compile()  # type: ignore
  )

  return JOIN_COMMAND.join(args)


def check_gpu_pipeline(video: Video, vaapi: bool):
  if not vaapi:
    raise GpuPipelineError('--gpu-pipeline requires VAAPI encoding (check --hwaccel and VAAPI support)')

  source = video.formats.video_profile

  if not source or not supports_vaapi_decode(source.codec):
    raise GpuPipelineError(f'VAAPI cannot decode {video.path.name} on this system')


def get_stream(
  video: Video,
  formats: Formats,
  threads: int = DEFAULT_THREADS,
  replace: bool = DEFAULT_REPLACE,
  subtitle: Path | None = None,
  hardware: bool = True,
  gpu_pipeline: bool = False,
) -> tuple[OutputStream, Path]:
  input_opts = get_input_opts(formats)
  output_opts = get_output_opts(video, formats, threads, hardware)
  new_path = get_new_path(video, formats, replace)

  vaapi = str(output_opts.get(FfmpegOpt.vcodec, '')).endswith(VAAPI_SUFFIX)

  if vaapi and (device := get_vaapi_device()):
    input_opts[FfmpegOpt.vaapi_device] = str(device)

  gpu = gpu_pipeline and output_opts[FfmpegOpt.vcodec] is not FfmpegVal.copy

  if gpu:
    check_gpu_pipeline(video, vaapi)

    input_opts |= {
      FfmpegOpt.hwaccel: FfmpegVal.vaapi,
      FfmpegOpt.hwaccel_device: str(get_vaapi_device()),
      FfmpegOpt.hwaccel_output_format: FfmpegVal.vaapi,
    }

  source = ffmpeg.input(
    str(video.path),
    **input_opts,
  )
  stream = source
  extra = ()

  if filters := get_video_filters(source, formats, upload=vaapi and not gpu, gpu=gpu):
    if output_opts.get(FfmpegOpt.vcodec) is FfmpegVal.copy:
      output_opts.pop(FfmpegOpt.vcodec)

    stream = filters
    extra = (source['a?'], source['s?'])

  stream = stream.output(
    *extra,
    str(new_path),
    **output_opts,
  )

  stream = stream.global_args(
    *GLOBAL_ARGS,
    **GLOBAL_OPTS,
  )

  return stream, new_path


def get_new_path(
  video: Video,
  formats: Formats,
  replace: bool = DEFAULT_REPLACE,
  suffix: str = TRANSCODE_SUFFIX,
) -> Path:
  container, video_profile, audio, subtitle = formats
  # codec, *_ = video_profile

  ext: Extension = video.path.suffix

  if container and not (ext := container.to_extension()):
    ext = DEFAULT_EXT

  if not ext.startswith(DOT):
    ext = DOT + ext

  new_path: Path = (
    video.path
    .with_stem(f'{video.path.stem}{suffix}')
    .with_suffix(ext)
  )

  return new_path


def get_output_opts(
  video: Video,
  formats: Formats,
  threads: int = DEFAULT_THREADS,
  hardware: bool = False,
) -> Options:
  opts: Options = DEFAULT_OUTPUT_OPTS.copy()

  if (profile := formats.audio_profile) and (codec := profile.codec):
    opts[FfmpegOpt.acodec] = get_encoder(codec)

  if (profile := formats.video_profile) and (codec := profile.codec):
    opts[FfmpegOpt.vcodec] = get_encoder(codec, hardware)

  if subtitle := formats.subtitle:
    opts[FfmpegOpt.scodec] = get_encoder(subtitle)

  if str(opts.get(FfmpegOpt.vcodec, '')).endswith(VAAPI_SUFFIX):
    # VAAPI encodes on the GPU and ignores -threads; leaving it out keeps
    # the command clean and avoids misleading thread limits.
    opts.pop(FfmpegOpt.threads, None)
  else:
    opts[FfmpegOpt.threads] = threads

  if not profile:
    return opts

  *_, fps, level = profile

  if fps:
    opts[FfmpegOpt.vsync] = FfmpegVal.vfr
    opts[FfmpegOpt.r] = fps

  if level:
    opts[FfmpegOpt.level] = level

    if FfmpegOpt.vcodec not in opts:
      codec = video.formats.video_profile.codec
      opts[FfmpegOpt.vcodec] = get_encoder(codec, hardware)

  return opts


def get_input_opts(formats: Formats) -> Options:
  opts: Options = DEFAULT_INPUT_OPTS.copy()

  if not formats.video_profile:
    return opts

  video_codec, resolution, fps, level = formats.video_profile

  return opts


def get_video_filters(
  stream: FilterableStream,
  formats: Formats,
  upload: bool = False,
  gpu: bool = False,
) -> FilterableStream | None:
  filters: FilterableStream | None = None

  profile = formats.video_profile
  resolution = profile.resolution if profile else None

  if gpu:
    scale_args: dict[str, str | int] = {'format': FfmpegVal.nv12}

    if resolution:
      _, height = resolution
      scale_args = {'w': f'trunc(iw*{height}/ih/2)*2', 'h': height, **scale_args}

    filters = ffmpeg.filter(stream, FfmpegOpt.scale_vaapi, **scale_args)

  elif resolution:
    width, height = resolution

    filters = ffmpeg.filter(
      stream,
      FfmpegOpt.scale,
      FfmpegVal.scale_resolution,
      height,  # resolution
    )

  if upload:
    source = filters if filters is not None else stream
    filters = ffmpeg.filter(source, FfmpegOpt.format, FfmpegVal.nv12)
    filters = ffmpeg.filter(filters, FfmpegOpt.hwupload)

  return filters


def convert_from_name_path(
  name: str,
  path: Path,
  replace: bool = DEFAULT_REPLACE,
  threads: int = DEFAULT_THREADS,
  subtitle: Path | None = None,
  hardware: bool = True,
  gpu_pipeline: bool = False,
  video: Video | None = None,
) -> Video | None:
  # Reuse an already-parsed Video when supplied (watch mode parses the file
  # once to check whether it's a video, then hands it off for conversion).
  video = video or Video.from_path(path)
  device = load_device_with_name(name)

  if not should_transcode(device, video, subtitle):
    show_transcode_dismissal(video, device)
    return None

  if not (formats := device.transcode_to(video)):
    return None

  try:
    return transcode_video(video, formats, replace, threads, subtitle, hardware, gpu_pipeline)

  except GpuPipelineError:
    raise

  except Exception as e:
    log.exception(e)
    log.error('Error while converting %s to %s', video, formats)

    raise ConversionFailed(f'Error while converting {video}') from e


async def convert_paths(
  name: str,
  replace: bool,
  threads: int,
  jobs: int,
  *paths: Path,
  strategy: Strategy = Strategy.quit,
  subtitle: Path | None = None,
  hardware: bool = True,
  gpu_pipeline: bool = False,
):
  sem = BoundedSemaphore(jobs)
  handled_converter = get_error_handler(
    convert_from_name_path,
    UnknownFormat,
    GpuPipelineError,
    ConversionFailed,
    strategy=strategy,
  )

  async def convert(path: Path):
    async with sem:
      await to_thread(handled_converter, name, path, replace, threads, subtitle, hardware, gpu_pipeline)

  async with TaskGroup() as tg:
    for path in paths:
      tg.create_task(convert(path))
