"""Deterministic generator of the batch-7 smoothing fixtures (7.9.03).

Noise comes from a fixed linear congruential generator (seed 20260101), values rounded to six
decimals. Re-running this script reproduces the checked-in files byte for byte.
"""
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent


class Lcg:
    def __init__(self, seed):
        self.state = seed

    def noise(self, amplitude):
        self.state = (1103515245 * self.state + 12345) % 2**31
        return (2 * self.state / 2**31 - 1) * amplitude


def fmt(value):
    return repr(round(value, 6) + 0.0)


def write_xyz(name, points):
    (OUT / name).write_text("".join(f"{fmt(x)} {fmt(y)} {fmt(z)}\n" for x, y, z in points), newline="\n")


def write_ply(name, points, normals):
    lines = ["ply", "format ascii 1.0", f"element vertex {len(points)}", "property double x", "property double y",
             "property double z", "property double nx", "property double ny", "property double nz", "end_header"]
    for (x, y, z), (nx, ny, nz) in zip(points, normals):
        lines.append(" ".join(fmt(v) for v in (x, y, z, nx, ny, nz)))
    (OUT / name).write_text("\n".join(lines) + "\n", newline="\n")


rng = Lcg(20260101)
# 8x8 grid of the plane z = 0, vertical noise amplitude 0.15.
plane = [(float(i), float(j), rng.noise(0.15)) for i in range(8) for j in range(8)]
write_xyz("noisy_plane.xyz", plane)
write_ply("noisy_plane_normals.ply", plane, [(0.0, 0.0, 1.0)] * len(plane))
# Tampered candidates for the independent smoothing validator.
displaced = [(x, y, 0.0) for x, y, _ in plane]
displaced[27] = (displaced[27][0], displaced[27][1], 10.0)
write_xyz("tampered_plane_displaced.xyz", displaced)
rough = Lcg(777)
write_xyz("tampered_plane_rougher.xyz", [(x, y, 2 * z + rough.noise(0.05)) for x, y, z in plane])
write_xyz("tampered_plane_short.xyz", plane[:-1])
zero = [(0.0, 0.0, 1.0)] * len(plane)
zero[10] = (0.0, 0.0, 0.0)
write_ply("plane_zero_normal.ply", plane, zero)

# Quadric z = 0.05 (x^2 + y^2) on an 8x8 grid centred on the origin, vertical noise amplitude 0.15.
quadric = []
for i in range(8):
    for j in range(8):
        x, y = i - 3.5, j - 3.5
        quadric.append((x, y, 0.05 * (x * x + y * y) + rng.noise(0.15)))
write_xyz("noisy_quadric.xyz", quadric)

# Roof z = 0.5 |x| (a crease along x = 0, dihedral angle 2 atan(0.5) = 53.13 degrees between the
# sides). 12x12 grid with spacing 0.5 and x offset by 0.25 so that no point lies on the crease;
# vertical noise amplitude 0.05; true unit normals (-+0.5, 0, 1) / sqrt(1.25).
roof, roof_normals = [], []
unit = 1 / math.sqrt(1.25)
for i in range(12):
    for j in range(12):
        x, y = -2.75 + 0.5 * i, -2.75 + 0.5 * j
        roof.append((x, y, 0.5 * abs(x) + rng.noise(0.05)))
        roof_normals.append((-0.5 * unit if x > 0 else 0.5 * unit, 0.0, unit))
write_xyz("noisy_roof.xyz", roof)
write_ply("noisy_roof_normals.ply", roof, roof_normals)

# 1000 Fibonacci points of the sphere of radius 5, radial noise amplitude 0.15, true radial normals.
golden = math.pi * (3 - math.sqrt(5))
sphere, sphere_normals = [], []
for index in range(1000):
    z = 1 - 2 * (index + 0.5) / 1000
    radius = math.sqrt(1 - z * z)
    direction = (radius * math.cos(golden * index), radius * math.sin(golden * index), z)
    scale = 5 + rng.noise(0.15)
    sphere.append(tuple(scale * c for c in direction))
    sphere_normals.append(direction)
write_xyz("noisy_sphere.xyz", sphere)
write_ply("noisy_sphere_normals.ply", sphere, sphere_normals)
