"""Generate the deterministic batch-9 fixtures (7.8.01 SDF segmentation, 7.11.04 periodic / on-sphere triangulations).

Usage: python tests/fixtures/master/batch9/generate_fixtures.py
"""

from __future__ import annotations

import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
GRID = 65536.0


def write(name: str, text: str) -> None:
    (HERE / name).write_text(text, encoding="utf-8", newline="\n")


def voxel_off(voxels: set[tuple[int, int, int]]) -> str:
    """Boundary of a face-connected voxel union, outward triangles, merged integer vertices."""
    index: dict[tuple[int, int, int], int] = {}
    vertices: list[tuple[int, int, int]] = []
    faces: list[tuple[int, int, int]] = []

    def vid(p):
        if p not in index:
            index[p] = len(vertices)
            vertices.append(p)
        return index[p]

    for (x, y, z) in sorted(voxels):
        for axis in range(3):
            for side in (0, 1):
                n = [x, y, z]
                n[axis] += 1 if side else -1
                if tuple(n) in voxels:
                    continue
                u, w = (axis + 1) % 3, (axis + 2) % 3
                base = [x, y, z]
                base[axis] += side
                corners = []
                for du, dw in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    c = list(base)
                    c[u] += du
                    c[w] += dw
                    corners.append(tuple(c))
                # (u, w, axis) is right-handed: counter-clockwise in (u, w) faces +axis.
                if not side:
                    corners.reverse()
                a, b, c, d = (vid(p) for p in corners)
                faces.append((a, b, c))
                faces.append((a, c, d))
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines += [f"{p[0]} {p[1]} {p[2]}" for p in vertices]
    lines += [f"3 {a} {b} {c}" for a, b, c in faces]
    return "\n".join(lines) + "\n"


class Lcg:
    def __init__(self, seed: int) -> None:
        self.state = seed

    def next(self) -> float:
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        return (self.state >> 11) / float(1 << 53)


def jittered(n: int, dimension: int, seed: int) -> list[list[float]]:
    rng = Lcg(seed)
    points = []
    cells = [[]]
    for _ in range(dimension):
        cells = [c + [i] for c in cells for i in range(n)]
    for cell in cells:
        points.append([round(((i + 0.2 + 0.6 * rng.next()) / n) * GRID) / GRID for i in cell])
    return points


def fibonacci_sphere(count: int, radius: float) -> list[tuple[float, float, float]]:
    golden = math.pi * (3.0 - math.sqrt(5.0))
    result = []
    for i in range(count):
        z = 1.0 - 2.0 * (i + 0.5) / count
        r = math.sqrt(1.0 - z * z)
        result.append((radius * r * math.cos(golden * i), radius * r * math.sin(golden * i), radius * z))
    return result


def main() -> None:
    body = {(x, y, z) for x in range(4) for y in range(4) for z in range(4)}
    arm = {(x, 1, 1) for x in range(4, 10)}
    write("body_arm.off", voxel_off(body | arm))

    write("periodic_points_2.json", json.dumps({"points": jittered(6, 2, 7)}, separators=(",", ":")) + "\n")
    write("periodic_sparse_2.json", json.dumps({"points": [[0.25, 0.25], [0.5, 0.75], [0.75, 0.375]]},
                                               separators=(",", ":")) + "\n")
    write("periodic_outside_2.json", json.dumps({"points": jittered(6, 2, 7)[:-1] + [[1.0, 0.5]]},
                                                separators=(",", ":")) + "\n")
    write("periodic_points_3.xyz", "".join(f"{p[0]!r} {p[1]!r} {p[2]!r}\n" for p in jittered(5, 3, 11)))
    write("periodic_sparse_3.xyz", "0.25 0.25 0.25\n0.75 0.5 0.5\n0.5 0.75 0.25\n0.5 0.5 0.75\n")
    sphere = fibonacci_sphere(120, 10.0)
    write("sphere_points.xyz", "".join(f"{x!r} {y!r} {z!r}\n" for x, y, z in sphere))
    write("sphere_off_surface.xyz", "".join(f"{x!r} {y!r} {z!r}\n" for x, y, z in sphere[:-1]) +
          f"{sphere[-1][0] * 1.1!r} {sphere[-1][1] * 1.1!r} {sphere[-1][2] * 1.1!r}\n")
    write("sphere_hemisphere.xyz", "".join(f"{x!r} {y!r} {z!r}\n" for x, y, z in sphere if z > 0.5))


if __name__ == "__main__":
    main()
