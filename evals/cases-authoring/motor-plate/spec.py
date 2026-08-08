from partspec import Part, openscad


def plate() -> Part:
    p = Part("motor-plate", openscad("model.scad"))
    p.envelope(max=(42.0, 42.0, 4.0))
    p.watertight()
    p.solid_count(1)
    p.genus(5)
    return p
