import sys; sys.path.insert(0, "tools")
from schlib import Schematic
s = Schematic("t", "t", paper="A4")
parts = []
for i, (rot, mir) in enumerate([(0,None),(90,None),(180,None),(270,None),(0,"y"),(90,"x"),(90,"y"),(270,"x"),(180,"y")]):
    u = s.part("carrier:DS3231SN", f"U{i+1}", "DS3231SN", (40 + i*45, 60), rot=rot, mirror=mir)
    for pin in ["SCL","SDA","~{RST}","32KHZ","~{INT}/SQW","VCC","VBAT","13"]:
        pt = u.pin(pin); d = u.pin_dir(pin)
        s.label(pt, f"N{i}_{pin.replace('~','').replace('{','').replace('}','').replace('/','')}", d)
    s.label(u.pin("[5,6,7,8]") if False else u.pin("5"), f"N{i}_G1", u.pin_dir("5"))
    s.label(u.pin("9"), f"N{i}_G2", u.pin_dir("9"))
r = s.part("Device:R_Small_US", "R1", "10k", (40, 120), rot=90)
s.power(r.pin("1"), "GND"); s.power(r.pin("2"), "+5V")
s.write("test/t.kicad_sch")
print("ok")
