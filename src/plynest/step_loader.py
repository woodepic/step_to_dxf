"""Read a STEP assembly into named, world-positioned solids.

Uses the XCAF (STEPCAFControl) reader rather than the plain STEPControl reader
so that product names and the assembly hierarchy survive the import -- those
names are what ends up engraved on each part.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape, TopoDS_Solid
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool

# OCC normalises STEP length units to millimetres on import regardless of the
# unit declared in the file, so everything downstream is mm.
MODEL_UNITS = "mm"


class StepLoadError(RuntimeError):
    pass


@dataclass
class LoadedSolid:
    """One leaf solid, already transformed into world coordinates."""

    path: tuple[str, ...]
    """Assembly path from the root down to the part, e.g. ("Cabinet <1>", "Floor")."""

    shape: TopoDS_Solid
    index: int
    """Stable 0-based ordinal, used to disambiguate identically named parts."""

    @property
    def name(self) -> str:
        return self.path[-1] if self.path else f"part_{self.index}"

    @property
    def path_str(self) -> str:
        return "/".join(self.path)


def _label_name(label: TDF_Label) -> str | None:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        text = attr.Get().ToExtString()
        return text.strip() or None
    return None


def _dedupe_path(path: tuple[str, ...]) -> tuple[str, ...]:
    """Collapse the 'instance name == referenced product name' duplication.

    STEP assemblies from Onshape/SolidWorks name both the occurrence and the
    product it points at, which yields paths like ``Cabinet/Floor/Floor``.
    """
    out: list[str] = []
    for part in path:
        if out and out[-1] == part:
            continue
        out.append(part)
    return tuple(out)


def load_step(path: str | Path) -> list[LoadedSolid]:
    """Load ``path`` and return every leaf solid with its assembly path."""
    path = Path(path)
    if not path.exists():
        raise StepLoadError(f"STEP file not found: {path}")

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("plynest"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)

    status = reader.ReadFile(str(path))
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise StepLoadError(f"OpenCASCADE could not read {path.name} (status={status})")
    if not reader.Transfer(doc):
        raise StepLoadError(f"No transferable shapes found in {path.name}")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    solids: list[LoadedSolid] = []

    def visit(label: TDF_Label, loc: TopLoc_Location, path_so_far: tuple[str, ...]) -> None:
        name = _label_name(label) or "Unnamed"
        if shape_tool.IsAssembly_s(label):
            components = TDF_LabelSequence()
            shape_tool.GetComponents_s(label, components)
            for i in range(1, components.Length() + 1):
                comp = components.Value(i)
                comp_loc = loc.Multiplied(shape_tool.GetLocation_s(comp))
                referred = TDF_Label()
                target = comp
                if shape_tool.GetReferredShape_s(comp, referred):
                    target = referred
                    child_name = _label_name(comp) or _label_name(referred) or "Unnamed"
                else:
                    child_name = _label_name(comp) or "Unnamed"
                visit(target, comp_loc, path_so_far + (child_name,))
            return

        shape: TopoDS_Shape = shape_tool.GetShape_s(label)
        if shape.IsNull():
            return
        placed = shape.Moved(loc)
        full_path = _dedupe_path(path_so_far + (name,))
        explorer = TopExp_Explorer(placed, TopAbs_SOLID)
        found = 0
        while explorer.More():
            solid = TopoDS.Solid_s(explorer.Current())
            sub_path = full_path if found == 0 else full_path + (f"solid{found + 1}",)
            solids.append(LoadedSolid(path=sub_path, shape=solid, index=len(solids)))
            found += 1
            explorer.Next()

    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        root = roots.Value(i)
        visit(root, shape_tool.GetLocation_s(root), ())

    if not solids:
        raise StepLoadError(f"{path.name} contains no solid bodies")
    return solids


_ABBREV_STOPWORDS = {"the", "of", "and"}


def abbreviate(token: str) -> str:
    """Compress an assembly node name for the engraved label.

    ``"Assembled Cabinet <4>"`` -> ``"AC4"``; ``"Drawer Assembly <2>"`` -> ``"DA2"``.
    Single-word names are left alone so ``"Floor"`` stays readable.
    """
    token = token.strip()
    instance = ""
    m = re.search(r"<\s*(\d+)\s*>\s*$", token)
    if m:
        instance = m.group(1)
        token = token[: m.start()].strip()

    words = [w for w in re.split(r"[\s_\-]+", token) if w]
    words = [w for w in words if w.lower() not in _ABBREV_STOPWORDS] or words
    if len(words) <= 1:
        base = words[0] if words else token
    else:
        base = "".join(w[0].upper() for w in words if w[:1].isalnum())
    return f"{base}{instance}"


def label_for(solid: LoadedSolid, *, style: str = "abbrev_path", max_depth: int = 3) -> str:
    """Build the engraved label text for a part.

    ``abbrev_path`` gives ``"AC4/DA2/Floor"``: enough to place the part in the
    assembly without spending much engraving time.
    """
    path = solid.path
    if len(path) > 1 and path[0] and len(path) > max_depth:
        # Drop the outermost node (usually the document name) before trimming.
        path = path[1:]
    if style == "name":
        return solid.name
    if style == "name_index":
        return f"{solid.name} #{solid.index + 1}"
    if style == "full_path":
        return "/".join(path)
    if style == "parent_name":
        return " / ".join(path[-2:]) if len(path) >= 2 else solid.name

    # abbrev_path (default)
    trimmed = path[-max_depth:] if max_depth > 0 else path
    parts = [abbreviate(t) for t in trimmed[:-1]] + [trimmed[-1]]
    return "/".join(p for p in parts if p)
