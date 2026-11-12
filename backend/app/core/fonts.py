"""Use installed fonts for both prediction and annotation images."""

from functools import lru_cache
import os
from pathlib import Path


@lru_cache
def drawing_font() -> str:
    candidates = [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    if os.name == 'nt':
        candidates.insert(0, Path(os.environ['WINDIR']) / 'Fonts/msyh.ttc')
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    from matplotlib.font_manager import findfont
    return findfont('DejaVu Sans')


def configure_plot_fonts() -> None:
    from ultralytics.data import utils
    from ultralytics.utils import plotting

    font = drawing_font()
    utils.check_font = lambda _name: font
    plotting.check_font = lambda _name: font
