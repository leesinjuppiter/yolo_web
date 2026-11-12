"""Geometry shared by annotation validation, conversion, and drawing."""

from collections.abc import Mapping
from math import cos, radians, sin


def obb_corners(box: Mapping[str, float]) -> list[tuple[float, float]]:
    angle = radians(box['angle'] % 360)
    c, s = cos(angle), sin(angle)
    w, h = box['width'] / 2, box['height'] / 2
    return [(box['cx'] + x * c - y * s, box['cy'] + x * s + y * c)
            for x, y in [(-w, -h), (w, -h), (w, h), (-w, h)]]
