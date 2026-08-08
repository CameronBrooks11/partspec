from partspec import Part, openscad


def plate() -> Part:
    p = Part("plate-bore", openscad("model.scad"))
    p.envelope(max=(40.0, 30.0, 4.0))
    p.watertight()
    p.solid_count(1)
    p.genus(1)
    return p
