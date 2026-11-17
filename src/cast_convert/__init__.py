from __future__ import annotations
from importlib.metadata import PackageNotFoundError, version
from typing import Final


try:
  __version__: Final[str] = version('cast_convert')
except PackageNotFoundError:
  # Package metadata unavailable (e.g. running from source without installing).
  __version__ = '0.0.0'

NAME: Final[str] = 'cast_convert'
PROJECT_HOME: Final[str] = 'https://github.com/alexdelorenzo/cast_convert'
AUTHOR_HOME: Final[str] = 'https://alexdelorenzo.dev'
AUTHOR: Final[str] = 'Alex DeLorenzo'
AUTHOR_INFO: Final[str] = f'{AUTHOR} ({AUTHOR_HOME})'
FORK_AUTHOR_HOME: Final[str] = 'https://users.exa.unicen.edu.ar/~azunino/'
FORK_AUTHOR: Final[str] = 'Alejandro Zunino'
FORK_AUTHOR_INFO: Final[str] = f'{FORK_AUTHOR} ({FORK_AUTHOR_HOME})'
COPYRIGHT_NOTICE: Final[str] = f'Copyright © 2023 {AUTHOR_INFO}, © 2026 {FORK_AUTHOR_INFO}'
LICENSE: Final[str] = 'AGPL-3.0'

DESCRIPTION: Final[str] = \
  "Identify and convert videos to formats that are Chromecast supported."

CLI_MODULE: Final[str] = f'{NAME}.cli'
CLI_ENTRY: Final[str] = 'cli'
