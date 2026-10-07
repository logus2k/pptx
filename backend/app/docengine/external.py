"""A deck as LibreOffice may read it: no part of it reaches outside the file. A relationship with TargetMode="External"
(a linked picture, video, OLE object or font: a URL or a file:// path) makes LibreOffice fetch it while converting, so
an uploaded deck could make the server request any address on its networks and draw what answers into the preview,
or draw another project's files from the disk (security review H1: reproduced, a linked picture fetched with GET
while rendering). Every external relationship but a hyperlink is removed from the copy LibreOffice converts;
hyperlinks are followed only by a person, never by the converter. The deck the person keeps is not changed."""

from __future__ import annotations

import io
import zipfile

from lxml import etree

R = "{http://schemas.openxmlformats.org/package/2006/relationships}"
HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def stripped(pptx: bytes) -> tuple[bytes, int]:
    """The package without external relationships other than hyperlinks, and how many were removed."""
    removed = 0
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(pptx)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith(".rels"):
                root = etree.fromstring(data, _PARSER)
                for rel in list(root.iter(f"{R}Relationship")):
                    if rel.get("TargetMode") == "External" and rel.get("Type") != HYPERLINK:
                        root.remove(rel)
                        removed += 1
                if removed:
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            dst.writestr(info, data)
    return (out.getvalue(), removed) if removed else (pptx, 0)
