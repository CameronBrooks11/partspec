from partspec import Part, openscad


def box() -> Part:
    p = Part("sealed-box", openscad("model.scad"))
    p.envelope(max=(60.0, 40.0, 25.0))
    p.watertight()
    p.solid_count(1)
    p.genus(0)
    p.cavities(1)
    return p
