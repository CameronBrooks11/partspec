from build123d import Box, Cylinder, Mode, Part as BdPart

def plate(plate_x=40.0, plate_y=30.0, plate_z=6.0, bore_d=8.0):
    p = Box(plate_x, plate_y, plate_z)
    p -= Cylinder(radius=bore_d / 2, height=plate_z * 2)
    return p
