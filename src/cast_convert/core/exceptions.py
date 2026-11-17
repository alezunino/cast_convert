from __future__ import annotations


class CastConvertException(Exception):
  pass


class FormatError(CastConvertException, ValueError):
  pass


class CannotCompare(CastConvertException, TypeError):
  pass


class UnknownFormat(FormatError):
  pass


class GpuPipelineError(CastConvertException):
  pass


class ConversionFailed(CastConvertException):
  pass
