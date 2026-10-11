# Glossary

- artifact: An immutable, typed, unit-tagged blob in the server store (imported file or worker output), identified by artifact_id and sha256.
- operation: One registered capability (id like mesh.simplify.edge_collapse). Roles: transform (makes geometry), analysis (makes a report), validator (checks another operation's result).
- plan: Immutable typed DAG of steps built by cgal_plan, with mandatory validators inserted. Executing a plan creates a job.
- job: One execution of a plan; state queued/running/succeeded/rejected/failed/cancelled; persistent.
- validator: An independent check (separate code, often exact rational arithmetic, not trusting the producer) that must pass before outputs are published. You cannot skip or replace it.
- VALIDATED: Operation status: implemented, executes in the native worker, and passed replay on bundled fixtures with its mandatory validator. It is evidence on those fixtures, not a proof for all inputs.
- CATALOGED: Package status: documentation and source are indexed but no executable adapter exists. Cannot be run.
- EXCLUDED: Package status: no standalone headless geometric operation exists (generic infrastructure, GUI-only, I/O only, no public headers).
- TypedLength: Length parameter written {"value": 0.5, "unit": "mm"}; mm, cm or m, converted to the input unit by the planner and recorded in the plan.
- TypedAngle: Angle parameter written {"value": 30, "unit": "deg"} or rad.
- step reference: Wiring one step's output into another step's input: {"step": "<step id>", "slot": "<output slot>"}.
- kernel: CGAL number-type choice. EPICK = exact predicates, inexact constructions (fast default); EPECK = exact predicates and constructions. Cards state the effective kernel; it is never switched silently.
- fail-closed: On doubt the server refuses or fails with a code instead of guessing a route, repairing silently, or publishing unverified output.
- recorded disambiguation: When a goal fits several operations the refusal carries details.options and a question instead of a guess; answer by choosing one operation_id.
- recipe: A verified multi-step workflow from the workflow set, rendered with fixtures, DAG and expected outcome (topic 'recipes').
- fixture: A small bundled test input file under tests/fixtures/master; recipes and example calls use them. Use your own file of the same artifact type for real work.

## Artifact types
- GeometryAnalysisReport: report produced by an operation (JSON, unitless); read it, do not import by hand
- GeometryQueryReport: report produced by an operation (JSON, unitless); read it, do not import by hand
- ImplicitSurfaceDomain: implicit surface domain description (JSON)
- InterpolationData2: 2D scattered data for interpolation (JSON)
- KernelQuerySet: kernel predicate / primitive query set (JSON)
- KernelReport: report produced by an operation (JSON, unitless); read it, do not import by hand
- OptimizationReport: report produced by an operation (JSON, unitless); read it, do not import by hand
- PointSet1: 1D points (JSON)
- PointSet2: 2D points (JSON)
- PointSet3: 3D points (XYZ)
- PointSet3Normals: 3D points with normals (PLY)
- Polygon2: simple 2D polygon (JSON)
- Polygon2AnalysisReport: report produced by an operation (JSON, unitless); read it, do not import by hand
- PolygonSoup3: unconnected 3D polygons/triangles (OFF), may be dirty or flipped
- PolygonWithHoles2: 2D polygon with holes (JSON)
- QuadraticProgram: linear/quadratic program (JSON)
- RayBatch3: batch of 3D rays (JSON)
- SegmentGraph2: 2D segments / arrangement input (JSON)
- SpatialQueryReport: report produced by an operation (JSON, unitless); read it, do not import by hand
- TetrahedralMesh: tetrahedral mesh (JSON)
- TriangleSurfaceMesh: triangle surface mesh (OFF/OBJ/PLY/STL)
- Triangulation2: 2D triangulation (JSON)
- Triangulation3: 3D triangulation (JSON)
- ValidationReport: report produced by an operation (JSON, unitless); read it, do not import by hand

## Units and coordinates
- every geometry artifact carries a unit (mm, cm or m); reports are unitless ('none'). Units are never guessed or converted silently between artifacts; mixing units in one operation fails with unit_mismatch.
- parameters written as TypedLength are converted to the input artifact's unit by the planner; the conversion is recorded in the plan.
- coordinates are right-handed Cartesian, stored as IEEE-754 binary64; face orientation is counter-clockwise seen from outside (outward normal); angles are degrees unless a card says otherwise.
