"""Geometry backends: measure an artifact.

Two, not three (D3). The OCCT backend serves build123d *and* CadQuery via a
`.wrapped` adopt shim; the mesh backend serves OpenSCAD. They share the
`GeometryBackend` protocol, not code.
"""
