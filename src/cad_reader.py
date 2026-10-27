from __future__ import annotations

import io
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from .models import CADDocument, CylindricalFeature


MAX_CAD_BYTES = 100 * 1024 * 1024
MAX_TRIANGLES = 250_000


class CADReadError(ValueError):
    pass


def _normalise(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-12:
        raise ValueError("A zero-length direction is not valid.")
    return tuple(value / length for value in vector)  # type: ignore[return-value]


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _shape_count(shape: object, shape_type: object) -> int:
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, shape_type)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def _read_iges(cad_bytes: bytes) -> tuple[object, str]:
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.IGESControl import IGESControl_Reader

    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".igs", delete=False) as temporary:
            temporary.write(cad_bytes)
            temporary_path = temporary.name
        reader = IGESControl_Reader()
        if reader.ReadFile(temporary_path) != IFSelect_RetDone:
            raise CADReadError("The IGES file could not be read by the CAD geometry engine.")
        transferred = reader.TransferRoots()
        if transferred <= 0:
            raise CADReadError("The IGES file did not contain transferable geometry.")
        shape = reader.OneShape()
        if shape.IsNull():
            raise CADReadError("The IGES file produced an empty model.")
        source_unit = "unknown"
        try:
            source_unit = reader.IGESModel().GlobalSection().UnitName().ToCString().strip() or "unknown"
        except Exception:
            pass
        return shape, source_unit
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _heal_iges_shape(shape: object) -> tuple[object, tuple[str, ...]]:
    """Sew IGES faces and promote a closed shell to a measurable solid when possible."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if _shape_count(shape, TopAbs_SOLID):
        return shape, ()
    sewing = BRepBuilderAPI_Sewing(1e-4)
    sewing.Add(shape)
    sewing.Perform()
    sewed = sewing.SewedShape()
    shell_count = _shape_count(sewed, TopAbs_SHELL)
    if shell_count == 1:
        explorer = TopExp_Explorer(sewed, TopAbs_SHELL)
        shell = TopoDS.Shell(explorer.Current())
        if shell.Closed():
            solid = BRepBuilderAPI_MakeSolid(shell).Solid()
            if not solid.IsNull():
                return solid, ("IGES faces were sewn into one closed solid before measurement.",)
    return sewed if not sewed.IsNull() else shape, ()


def _mesh_shape(
    shape: object, deflection: float
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[int, int, int], ...]]:
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    mesher = BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)
    mesher.Perform()
    if not mesher.IsDone():
        raise CADReadError("The CAD model could not be triangulated for preview.")

    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None and triangulation.NbTriangles() > 0:
            transform = location.Transformation()
            offset = len(vertices)
            for node_index in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(node_index).Transformed(transform)
                vertices.append((point.X(), point.Y(), point.Z()))
            reverse = face.Orientation() == TopAbs_REVERSED
            for triangle_index in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(triangle_index).Get()
                if reverse:
                    b, c = c, b
                triangles.append((offset + a - 1, offset + b - 1, offset + c - 1))
                if len(triangles) > MAX_TRIANGLES:
                    raise CADReadError(
                        f"The model exceeds the {MAX_TRIANGLES:,}-triangle preview limit."
                    )
        explorer.Next()
    if not vertices or not triangles:
        raise CADReadError("The model contains no renderable faces.")
    return tuple(vertices), tuple(triangles)


def _cylindrical_features(shape: object) -> tuple[CylindricalFeature, ...]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    grouped: dict[tuple[float, float, float, float], list[float]] = defaultdict(list)
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        surface = BRepAdaptor_Surface(face, True)
        if surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            radius = cylinder.Radius()
            direction = cylinder.Axis().Direction()
            axis = _normalise((direction.X(), direction.Y(), direction.Z()))
            # Axis sign is irrelevant for grouping the same cylindrical direction.
            if next((value for value in axis if abs(value) > 1e-7), 1.0) < 0:
                axis = tuple(-value for value in axis)  # type: ignore[assignment]
            length = abs(surface.LastVParameter() - surface.FirstVParameter())
            key = (round(radius * 2, 4), *(round(value, 4) for value in axis))
            grouped[key].append(length)
        explorer.Next()

    features = [
        CylindricalFeature(
            diameter_mm=key[0],
            length_mm=round(max(lengths), 4),
            axis=(key[1], key[2], key[3]),
            candidate_count=len(lengths),
            detection_method="cylindrical_surface",
        )
        for key, lengths in grouped.items()
    ]
    if features:
        return tuple(sorted(features, key=lambda item: (item.diameter_mm, item.axis)))

    # Some IGES exporters replace analytic cylinders with spline surfaces while
    # retaining circular boundary edges. Use those edges as explicitly labelled
    # candidates, pairing the top and bottom circles by their projected centre.
    circles: dict[tuple[float, float, float, float], set[tuple[float, float, float]]] = defaultdict(set)
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge(explorer.Current())
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() == GeomAbs_Circle:
            circle = curve.Circle()
            direction = circle.Axis().Direction()
            axis = _normalise((direction.X(), direction.Y(), direction.Z()))
            if next((value for value in axis if abs(value) > 1e-7), 1.0) < 0:
                axis = tuple(-value for value in axis)  # type: ignore[assignment]
            center = circle.Location()
            center_tuple = (center.X(), center.Y(), center.Z())
            along = _dot(center_tuple, axis)
            planar_center = tuple(
                round(center_tuple[index] - along * axis[index], 3) for index in range(3)
            )
            key = (round(circle.Radius() * 2, 4), *(round(value, 4) for value in axis))
            circles[key].add(planar_center)
        explorer.Next()
    for key, planar_centers in circles.items():
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        xmin, ymin, zmin = box.GetXMin(), box.GetYMin(), box.GetZMin()
        xmax, ymax, zmax = box.GetXMax(), box.GetYMax(), box.GetZMax()
        corners = (
            (x, y, z)
            for x in (xmin, xmax)
            for y in (ymin, ymax)
            for z in (zmin, zmax)
        )
        projections = [_dot(corner, (key[1], key[2], key[3])) for corner in corners]
        features.append(
            CylindricalFeature(
                diameter_mm=key[0],
                length_mm=round(max(projections) - min(projections), 4),
                axis=(key[1], key[2], key[3]),
                candidate_count=len(planar_centers),
                detection_method="circular_edges",
            )
        )
    return tuple(sorted(features, key=lambda item: (item.diameter_mm, item.axis)))


VIEW_DIRECTIONS: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("Front", (0.0, -1.0, 0.0)),
    ("Back", (0.0, 1.0, 0.0)),
    ("Left", (-1.0, 0.0, 0.0)),
    ("Right", (1.0, 0.0, 0.0)),
    ("Top", (0.0, 0.0, 1.0)),
    ("Bottom", (0.0, 0.0, -1.0)),
    ("Isometric", (1.0, -1.0, 0.8)),
)


def _render_view_vtk(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    view_name: str,
    camera_direction: tuple[float, float, float],
    size: tuple[int, int],
) -> bytes:
    import vtk
    from vtkmodules.util.numpy_support import vtk_to_numpy

    points = vtk.vtkPoints()
    for point in vertices:
        points.InsertNextPoint(*point)
    cells = vtk.vtkCellArray()
    for triangle in triangles:
        cell = vtk.vtkTriangle()
        for index, vertex_index in enumerate(triangle):
            cell.GetPointIds().SetId(index, vertex_index)
        cells.InsertNextCell(cell)
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetPolys(cells)

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(polydata)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOff()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.20, 0.55, 0.82)
    actor.GetProperty().SetAmbient(0.28)
    actor.GetProperty().SetDiffuse(0.72)
    actor.GetProperty().SetSpecular(0.22)
    actor.GetProperty().SetSpecularPower(20)

    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.968, 0.976, 0.988)
    renderer.AddActor(actor)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(*size)
    window.AddRenderer(renderer)

    direction = _normalise(camera_direction)
    reference_up = (0.0, 1.0, 0.0) if abs(direction[2]) > 0.9 else (0.0, 0.0, 1.0)
    center = tuple(sum(point[index] for point in vertices) / len(vertices) for index in range(3))
    spans = tuple(
        max(point[index] for point in vertices) - min(point[index] for point in vertices)
        for index in range(3)
    )
    distance = max(math.sqrt(sum(value * value for value in spans)) * 2.5, 1.0)
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(*center)
    camera.SetPosition(*(center[index] + direction[index] * distance for index in range(3)))
    camera.SetViewUp(*reference_up)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    renderer.ResetCameraClippingRange()
    window.Render()

    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetInputConnection(capture.GetOutputPort())
    writer.WriteToMemoryOn()
    writer.Write()
    raw = vtk_to_numpy(writer.GetResult()).tobytes()
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 58), fill="#f7f9fc")
    draw.rectangle((0, size[1] - 38, size[0], size[1]), fill="#f7f9fc")
    draw.text((22, 18), f"{view_name.upper()} VIEW", fill="#152536", font=ImageFont.load_default(size=20))
    draw.text(
        (22, size[1] - 28),
        "Generated from IGES geometry · not a dimensional drawing",
        fill="#526579",
        font=ImageFont.load_default(size=14),
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    window.Finalize()
    return output.getvalue()


def render_view(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    view_name: str,
    camera_direction: tuple[float, float, float],
    *,
    size: tuple[int, int] = (720, 520),
) -> bytes:
    try:
        return _render_view_vtk(vertices, triangles, view_name, camera_direction, size)
    except Exception:
        # A pure-Pillow fallback keeps Colab/headless environments usable even
        # when the VTK wheel cannot initialize an off-screen renderer.
        pass
    direction = _normalise(camera_direction)
    reference_up = (0.0, 1.0, 0.0) if abs(direction[2]) > 0.9 else (0.0, 0.0, 1.0)
    right = _normalise(_cross(reference_up, direction))
    up = _normalise(_cross(direction, right))
    center = tuple(
        (min(point[index] for point in vertices) + max(point[index] for point in vertices)) / 2
        for index in range(3)
    )
    projected = [
        (
            _dot(tuple(point[i] - center[i] for i in range(3)), right),
            _dot(tuple(point[i] - center[i] for i in range(3)), up),
            _dot(tuple(point[i] - center[i] for i in range(3)), direction),
        )
        for point in vertices
    ]
    width, height = size
    margin_x, margin_top, margin_bottom = 55, 70, 45
    min_x, max_x = min(p[0] for p in projected), max(p[0] for p in projected)
    min_y, max_y = min(p[1] for p in projected), max(p[1] for p in projected)
    span_x, span_y = max(max_x - min_x, 1e-6), max(max_y - min_y, 1e-6)
    scale = min((width - margin_x * 2) / span_x, (height - margin_top - margin_bottom) / span_y)

    def screen(point: tuple[float, float, float]) -> tuple[float, float]:
        return (
            width / 2 + point[0] * scale,
            (margin_top + height - margin_bottom) / 2 - point[1] * scale,
        )

    image = Image.new("RGB", size, "#f7f9fc")
    draw = ImageDraw.Draw(image)
    light = _normalise((0.4, -0.6, 1.0))
    edge_counts: dict[tuple[int, int], int] = defaultdict(int)
    for triangle in triangles:
        for first, second in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            edge_counts[tuple(sorted((first, second)))] += 1

    ordered: list[tuple[float, tuple[int, int, int], tuple[float, float, float]]] = []
    for triangle in triangles:
        a, b, c = (vertices[index] for index in triangle)
        raw_normal = _cross(
            tuple(b[i] - a[i] for i in range(3)),
            tuple(c[i] - a[i] for i in range(3)),
        )
        if sum(value * value for value in raw_normal) <= 1e-18:
            continue
        normal = _normalise(raw_normal)
        if _dot(normal, direction) <= 1e-8:
            continue
        ordered.append((sum(projected[index][2] for index in triangle) / 3, triangle, normal))

    visible_boundaries: set[tuple[int, int]] = set()
    for _, triangle, normal in sorted(ordered, key=lambda item: item[0]):
        brightness = 0.58 + 0.32 * max(0.0, _dot(normal, light))
        fill = tuple(int(value * brightness) for value in (80, 150, 210))
        draw.polygon([screen(projected[index]) for index in triangle], fill=fill)
        for first, second in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            edge = tuple(sorted((first, second)))
            if edge_counts[edge] == 1:
                visible_boundaries.add(edge)
    for first, second in visible_boundaries:
        draw.line((screen(projected[first]), screen(projected[second])), fill="#244b6b", width=1)

    font = ImageFont.load_default(size=20)
    small_font = ImageFont.load_default(size=14)
    draw.text((22, 18), f"{view_name.upper()} VIEW", fill="#152536", font=font)
    draw.text((22, height - 28), "Generated from IGES geometry · not a dimensional drawing", fill="#526579", font=small_font)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_standard_views(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (name, render_view(vertices, triangles, name, direction))
        for name, direction in VIEW_DIRECTIONS
    )


def extract_cad(cad_bytes: bytes, source_file: str) -> CADDocument:
    if not cad_bytes:
        raise CADReadError("The IGES file is empty.")
    if len(cad_bytes) > MAX_CAD_BYTES:
        raise CADReadError("The IGES file exceeds the 100 MB processing limit.")
    if Path(source_file).suffix.lower() not in {".igs", ".iges"}:
        raise CADReadError("Only .igs and .iges CAD files are supported in Level 3.")

    try:
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepGProp import BRepGProp
        from OCP.Bnd import Bnd_Box
        from OCP.GProp import GProp_GProps
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    except ImportError as exc:
        raise CADReadError("The OpenCascade CAD engine is not installed on this server.") from exc

    try:
        raw_shape, source_unit = _read_iges(cad_bytes)
        shape, healing_warnings = _heal_iges_shape(raw_shape)
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, box)
        xmin, ymin, zmin = box.GetXMin(), box.GetYMin(), box.GetZMin()
        xmax, ymax, zmax = box.GetXMax(), box.GetYMax(), box.GetZMax()
        bounds = (xmax - xmin, ymax - ymin, zmax - zmin)
        diagonal = math.sqrt(sum(value * value for value in bounds))
        if diagonal <= 1e-9:
            raise CADReadError("The IGES model has no measurable three-dimensional extent.")

        surface_properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, surface_properties)
        surface_area = abs(surface_properties.Mass())
        solid_count = _shape_count(shape, TopAbs_SOLID)
        volume: float | None = None
        center: tuple[float, float, float] | None = None
        warnings: list[str] = list(healing_warnings)
        largest_extent = max(bounds)
        if source_unit.casefold() in {"unknown", "", "none"}:
            warnings.append(
                "The IGES source unit could not be verified; confirm scale before using dimensions for manufacturing."
            )
        if largest_extent < 1.0:
            warnings.append(
                f"The transferred model is unusually small (largest extent {largest_extent:.6g} mm). "
                "Verify the IGES exporter and source-unit metadata before relying on dimensions."
            )
        elif largest_extent > 1_000_000.0:
            warnings.append(
                f"The transferred model is unusually large (largest extent {largest_extent:.6g} mm). "
                "Verify the IGES exporter and source-unit metadata before relying on dimensions."
            )
        if solid_count:
            volume_properties = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape, volume_properties)
            volume = abs(volume_properties.Mass())
            point = volume_properties.CentreOfMass()
            center = (point.X(), point.Y(), point.Z())
        else:
            warnings.append("The model contains no closed solid, so volume and solid center of mass are unavailable.")

        deflection = min(max(diagonal / 700.0, 0.01), 1.0)
        vertices, triangles = _mesh_shape(shape, deflection)
        views = render_standard_views(vertices, triangles)
        valid = BRepCheck_Analyzer(shape).IsValid()
        if not valid:
            warnings.append("OpenCascade reported invalid or incomplete topology; measurements require review.")
        features = _cylindrical_features(shape)
        if features:
            warnings.append(
                "Cylindrical surfaces are geometric candidates only; confirm whether each is a hole, boss, or fillet."
            )

        return CADDocument(
            source_file=source_file,
            units=f"mm after OpenCascade transfer (IGES source declares {source_unit})",
            bounding_box_mm=tuple(round(value, 4) for value in bounds),
            volume_mm3=round(volume, 4) if volume is not None else None,
            surface_area_mm2=round(surface_area, 4),
            center_of_mass_mm=tuple(round(value, 4) for value in center) if center else None,
            solid_count=solid_count,
            shell_count=_shape_count(shape, TopAbs_SHELL),
            face_count=_shape_count(shape, TopAbs_FACE),
            edge_count=_shape_count(shape, TopAbs_EDGE),
            model_valid=valid,
            cylindrical_features=features,
            warnings=tuple(warnings),
            vertices=vertices,
            triangles=triangles,
            rendered_views=views,
        )
    except CADReadError:
        raise
    except Exception as exc:
        raise CADReadError(f"The IGES model could not be analysed: {exc}") from exc


def cad_view_images(
    document: CADDocument, names: Iterable[str] = ("Front", "Top", "Isometric")
) -> tuple[tuple[str, bytes], ...]:
    requested = set(names)
    return tuple(item for item in document.rendered_views if item[0] in requested)
