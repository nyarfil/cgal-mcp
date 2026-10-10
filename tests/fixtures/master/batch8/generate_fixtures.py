"""Deterministic generator of the batch-8 fixtures (7.8.02 convex decomposition, 7.8.03 skeletonization,
7.8.05 parameterization). Run: python tests/fixtures/master/batch8/generate_fixtures.py

l_prism.off      closed L-shaped prism (three unit cubes), volume 3, concave
t_prism.off      closed T-shaped prism, volume 5 (stem 1x2 plus bar 3x1, height 1), concave
tube.off         closed capped cylinder, radius 1, length 6 along x (genus 0)
torus.off        closed torus, major radius 3, minor radius 1 (genus 1)
disc_bump.off    open 9x9 height-field disc with jittered interior vertices (one boundary loop)
"""

from __future__ import annotations

import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def fmt(value: float) -> str:
    return repr(float(value)) if value != int(value) else str(int(value))


def volume(vertices, faces) -> float:
    total = 0.0
    for a, b, c in faces:
        pa, pb, pc = vertices[a], vertices[b], vertices[c]
        total += (pa[0] * (pb[1] * pc[2] - pb[2] * pc[1]) + pa[1] * (pb[2] * pc[0] - pb[0] * pc[2])
                  + pa[2] * (pb[0] * pc[1] - pb[1] * pc[0]))
    return total / 6.0


def write(name: str, vertices, faces, outward: bool = True) -> None:
    if outward and volume(vertices, faces) < 0:
        faces = [(a, c, b) for a, b, c in faces]
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines += [" ".join(fmt(c) for c in v) for v in vertices]
    lines += [f"3 {a} {b} {c}" for a, b, c in faces]
    (HERE / name).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def prism(polygon, triangles, height=1.0):
    n = len(polygon)
    vertices = [(x, y, 0.0) for x, y in polygon] + [(x, y, height) for x, y in polygon]
    faces = []
    for a, b, c in triangles:  # polygon triangles are counter-clockwise
        faces.append((n + a, n + b, n + c))
        faces.append((a, c, b))
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j))
        faces.append((i, n + j, n + i))
    return vertices, faces


def build_l():
    polygon = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    write("l_prism.off", *prism(polygon, [(0, 1, 2), (0, 2, 3), (0, 3, 5), (3, 4, 5)]))


def build_t():
    polygon = [(1, 0), (2, 0), (2, 2), (3, 2), (3, 3), (0, 3), (0, 2), (1, 2)]
    write("t_prism.off", *prism(polygon, [(0, 1, 2), (0, 2, 7), (7, 2, 4), (7, 4, 5), (7, 5, 6), (2, 3, 4)]))


def build_tube(segments=16, rings=10, radius=1.0, length=6.0):
    vertices = []
    for i in range(rings + 1):
        x = length * i / rings
        for j in range(segments):
            t = 2 * math.pi * j / segments
            vertices.append((x, radius * math.cos(t), radius * math.sin(t)))
    faces = []
    for i in range(rings):
        for j in range(segments):
            a, b = i * segments + j, i * segments + (j + 1) % segments
            c, d = (i + 1) * segments + (j + 1) % segments, (i + 1) * segments + j
            faces += [(a, b, c), (a, c, d)]
    first = len(vertices)
    vertices.append((0.0, 0.0, 0.0))
    vertices.append((length, 0.0, 0.0))
    for j in range(segments):
        k = (j + 1) % segments
        faces.append((first, k, j))
        faces.append((first + 1, rings * segments + j, rings * segments + k))
    # Fix the orientation of each part independently by the global signed volume.
    write("tube.off", vertices, faces)


def build_torus(major_segments=24, minor_segments=12, big=3.0, small=1.0):
    vertices = []
    for i in range(major_segments):
        u = 2 * math.pi * i / major_segments
        for j in range(minor_segments):
            v = 2 * math.pi * j / minor_segments
            r = big + small * math.cos(v)
            vertices.append((r * math.cos(u), r * math.sin(u), small * math.sin(v)))
    faces = []
    for i in range(major_segments):
        for j in range(minor_segments):
            a = i * minor_segments + j
            b = ((i + 1) % major_segments) * minor_segments + j
            c = ((i + 1) % major_segments) * minor_segments + (j + 1) % minor_segments
            d = i * minor_segments + (j + 1) % minor_segments
            faces += [(a, b, c), (a, c, d)]
    write("torus.off", vertices, faces)


def build_disc(n=9):
    vertices = []
    for j in range(n):
        for i in range(n):
            x, y = -1 + 2 * i / (n - 1), -1 + 2 * j / (n - 1)
            if 0 < i < n - 1 and 0 < j < n - 1:
                x += 0.05 * math.sin(7 * i + 3 * j)
                y += 0.05 * math.cos(5 * i + 11 * j)
            vertices.append((x, y, 0.4 * (x * x - y * y) + 0.15 * x * y))
    faces = []
    for j in range(n - 1):
        for i in range(n - 1):
            a, b, c, d = j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i
            faces += [(a, b, c), (a, c, d)] if (i + j) % 2 == 0 else [(a, b, d), (b, c, d)]
    write("disc_bump.off", vertices, faces, outward=False)


if __name__ == "__main__":
    build_l()
    build_t()
    build_tube()
    build_torus()
    build_disc()
