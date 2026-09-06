import json, io, os, re

CORPUS = 'rag/corpus/wikipedia_en.jsonl'
by_title = {}
with open(CORPUS, encoding='utf-8') as f:
    for line in f:
        d = json.loads(line)
        by_title.setdefault(d['title'], []).append(d['text'])

def has_quote(title, quote):
    return any(quote in t for t in by_title.get(title, []))

R = []
def rec(title, diff, q, a, expl, quote):
    R.append(dict(title=title, difficulty=diff, question=q, answer=a, explanation=expl, quote=quote))

# 1 Mechanics
rec('Mechanics', 1,
    "In classical mechanics, which quantity is defined as distance moved?",
    "displacement",
    "The mechanics text lists the basic quantities a description of motion must define, and gives displacement as distance moved, alongside time, velocity, acceleration, mass, and force.",
    "Modern descriptions of such behavior begin with a careful definition of such quantities as displacement (distance moved), time, velocity, acceleration, mass, and force.")

# 2-3 Acceleration units
acc_units = 'The SI unit of acceleration is the metre per second squared (m s−2); or "metre per second per second", as the velocity in metres per second changes by the acceleration value, every second.'
rec('Acceleration', 1,
    "What is the SI unit of acceleration?",
    "metre per second squared",
    "The SI unit of acceleration is the metre per second squared, since velocity in metres per second changes by the acceleration value every second.",
    acc_units)
rec('Acceleration', 2,
    "In symbol form, how is the SI unit of acceleration written?",
    "m s−2",
    "The SI unit of acceleration, the metre per second squared, is written in symbols as m s−2.",
    acc_units)
# 4
rec('Acceleration', 1,
    "Acceleration has the dimensions of velocity divided by which quantity?",
    "time",
    "Acceleration's dimensions are velocity (L/T) divided by time, written L T−2, so its unit combines length and time.",
    "Acceleration has the dimensions of velocity (L/T) divided by time, i.e. L T−2.")
# 5
rec('Acceleration', 1,
    "Measuring average acceleration requires knowledge of the change in velocity and the change in what?",
    "time",
    "Average acceleration, the simplest form to measure, needs only the change in velocity and the change in time.",
    "The average acceleration is the simplest way to measure acceleration, requiring only knowledge of the change in velocity and the change in time.")

# 6-7 Angular acceleration
ang_acc = "Angular acceleration has physical dimensions of inverse time squared, with the SI unit radian per second squared (rad⋅s−2)."
rec('Angular acceleration', 1,
    "What is the SI unit of angular acceleration?",
    "radian per second squared",
    "Angular acceleration has physical dimensions of inverse time squared, and its SI unit is the radian per second squared.",
    ang_acc)
rec('Angular acceleration', 2,
    "In compact symbol form, what is the SI unit of angular acceleration?",
    "rad⋅s−2",
    "The SI unit of angular acceleration, the radian per second squared, is written rad⋅s−2.",
    ang_acc)

# 8-10 Angular velocity
rec('Angular velocity', 1,
    "Angular velocity has dimension of per unit what?",
    "time",
    "Angular velocity is stated to have the dimension of per unit time, which is why its SI unit pairs radians with seconds.",
    "Angular velocity has dimension of per unit time.")
radian_sent = "The radian is a dimensionless quantity, thus the SI units of angular velocity are dimensionally equivalent to reciprocal seconds, s−1, although rad/s is preferable to avoid confusion with rotational velocity in units of hertz (also equivalent to s−1)."
rec('Angular velocity', 2,
    "The SI units of angular velocity are dimensionally equivalent to reciprocal seconds (s−1); which written form is preferable to avoid confusion with hertz?",
    "rad/s",
    "Because the radian is dimensionless, angular velocity's units equal s−1, but rad/s is the preferred written form to avoid confusion with hertz.",
    radian_sent)
rec('Angular velocity', 1,
    "According to that same statement, what kind of quantity is the radian?",
    "dimensionless",
    "The radian is a dimensionless quantity, which is why rad/s and s−1 are dimensionally equivalent.",
    radian_sent)
# 11 geostationary
geo = "For example, a geostationary satellite completes one orbit per sidereal day above the equator (approximately 360 degrees per 24 hours) has angular velocity magnitude (angular speed) ω = 360°/24 h = 15°/h (or 2π rad/24 h ≈ 0.26 rad/h)"
rec('Angular velocity', 2,
    "A geostationary satellite completes one orbit per sidereal day, approximately 360 degrees per 24 hours; what is its angular speed in degrees per hour?",
    "15°/h",
    "Dividing 360 degrees by 24 hours gives the satellite's angular speed of 360°/24 h = 15°/h.",
    geo)

# 12 Angular frequency unit
rec('Angular frequency', 1,
    "In SI units, angular frequency is normally presented in which unit?",
    "radian per second",
    "In SI units, the normal presentation for angular frequency is the unit radian per second.",
    "In SI units, angular frequency is normally presented in the unit radian per second.")
hz_sent = "The unit hertz (Hz) is dimensionally equivalent, but by convention it is only used for frequency f, never for angular frequency ω."
rec('Angular frequency', 1,
    "The unit hertz is dimensionally equivalent to the radian per second, but by convention it is reserved for which quantity?",
    "frequency",
    "Hertz is dimensionally equivalent to the radian per second, but convention reserves it for frequency f and never uses it for angular frequency ω.",
    hz_sent)
# 14
rec('Angular frequency', 2,
    "Angular frequency differs from ordinary frequency by a factor of what?",
    "2π",
    "Angular frequency and frequency differ by a factor of 2π, so the two must not be interchanged without converting units of angle.",
    "Although angular frequency is often loosely referred to as frequency, it differs from frequency by a factor of 2π, which potentially leads confusion when the distinction is not made clear.")
# 15
circ = "ω is the angular frequency (SI unit: radians per second), T is the period (SI unit: seconds), f is the ordinary frequency (SI unit: hertz)."
rec('Angular frequency', 1,
    "In the circular-motion relations, the period T carries which SI unit?",
    "seconds",
    "In these relations the period T is given in seconds, while ω is in radians per second and f is in hertz.",
    circ)

# 17-19 Angular momentum
am_units = "Angular momentum's dependence on position and shape is reflected in its units versus linear momentum: kg⋅m2/s or N⋅m⋅s for angular momentum versus kg⋅m/s or N⋅s for linear momentum."
rec('Angular momentum', 2,
    "Angular momentum is expressed in kg⋅m2/s or N⋅m⋅s; linear momentum is expressed in which units?",
    "kg⋅m/s or N⋅s",
    "The unit difference reflects angular momentum's dependence on position and shape: kg⋅m2/s (or N⋅m⋅s) for angular momentum versus kg⋅m/s (or N⋅s) for linear momentum.",
    am_units)
rec('Angular momentum', 1,
    "Which unit expression belongs to angular momentum rather than linear momentum: kg⋅m2/s or kg⋅m/s?",
    "kg⋅m2/s",
    "Angular momentum carries kg⋅m2/s or N⋅m⋅s, while kg⋅m/s or N⋅s belongs to linear momentum.",
    am_units)
rec('Angular momentum', 2,
    "When computing angular momentum as the product of moment of inertia and angular velocity, in which unit must the angular velocity be expressed?",
    "radians per second",
    "The calculation only works when the angular velocity is expressed in radians per second, with the radian taken as dimensionless unity.",
    "When calculating angular momentum as the product of the moment of inertia times the angular velocity, the angular velocity must be expressed in radians per second, where the radian assumes the dimensionless value of unity.")
# 20
rec('Angular momentum', 2,
    "The orbital angular momentum of the Earth with respect to the Sun is about 2.66 × 10^40 in which SI unit?",
    "J⋅s",
    "The Earth's orbital angular momentum is quoted as 2.66 × 1040 J⋅s, so joule-seconds are the unit for this quantity.",
    "Thus, for example, the orbital angular momentum of the Earth with respect to the Sun is about 2.66 × 1040 J⋅s, while its rotational angular momentum is about 7.05 × 1033 J⋅s.")

# 21-22 Angular displacement
rec('Angular displacement', 1,
    "Angular displacement may be expressed with which two units?",
    "radian or degree",
    "Angular displacement is stated to be expressible with the unit radian or the unit degree.",
    "Angular displacement may be expressed with the unit radian or degree.")
rec('Angular displacement', 2,
    "In the ISQ/SI, the number of revolutions N is a ratio and hence a quantity of dimension what?",
    "one",
    "The number of revolutions N = θ/(2π rad) is a ratio of two like quantities, so it has dimension one.",
    "In the ISQ/SI, angular displacement is used to define the number of revolutions, N = θ/(2π rad), a ratio and hence a quantity of dimension one.")

# 23-24 Orbital mechanics
orb_units = r"To properly use this formula, the units must be consistent; for example,    M   {\displaystyle M}  must be in kilograms, and    r   {\displaystyle r}  must be in meters, then the answer will be in meters per second."
rec('Orbital mechanics', 1,
    "To properly use the circular-orbit velocity formula, what must be true of the units?",
    "consistent",
    "The formula only works correctly when the units are consistent: mass in kilograms and radius in meters.",
    orb_units)
rec('Orbital mechanics', 2,
    "In the circular-orbit velocity formula, if M is entered in kilograms and r in meters, the answer will be in which units?",
    "meters per second",
    "With M in kilograms and r in meters, the consistent units make the velocity come out in meters per second.",
    orb_units)
# 25
esc = "The escape velocity from the Earth's surface is about 11 km/s, but that is insufficient to send the body an infinite distance because of the gravitational pull of the Sun."
rec('Orbital mechanics', 1,
    "The escape velocity from the Earth's surface is about 11 km/s, a unit read as kilometres per what?",
    "second",
    "The escape velocity is quoted in km/s, that is, kilometres per second, about 11 of them from the Earth's surface.",
    esc)

# 27-29 Drag power example
drag_pow = "For example, a car cruising on a highway at 50 mph (80 km/h) may require only 10 horsepower (7.5 kW) to overcome aerodynamic drag, but that same car at 100 mph (160 km/h) requires 80 hp (60 kW)."
rec('Drag (physics)', 1,
    "A car cruising on a highway at 50 mph is traveling at how many km/h?",
    "80 km/h",
    "The drag example states the same cruising speed in both units: 50 mph equals 80 km/h.",
    drag_pow)
rec('Drag (physics)', 1,
    "That same car, when traveling at 100 mph, requires how many kW to overcome aerodynamic drag?",
    "60 kW",
    "At 100 mph the car requires 80 hp, which the text gives as 60 kW, to overcome aerodynamic drag.",
    drag_pow)
rec('Drag (physics)', 2,
    "A car needs 10 horsepower to overcome drag at 50 mph; how many horsepower does it need at 100 mph?",
    "80 hp",
    "The same car that needs 10 hp at 50 mph needs 80 hp at 100 mph, showing how quickly drag power grows with speed.",
    drag_pow)

# 30-31 Stokes viscosity
stokes = "Using 10−3 Pa·s as the dynamic viscosity of water in SI units, we find a drag force of 0.09 pN."
rec('Drag (physics)', 2,
    "In SI units, water's dynamic viscosity is given as 10−3 Pa·s, so Pa·s is the SI unit of which quantity?",
    "dynamic viscosity",
    "The Stokes-drag calculation enters water's dynamic viscosity in SI units as 10−3 Pa·s, making Pa·s the unit of dynamic viscosity.",
    stokes)
rec('Drag (physics)', 1,
    "A bacterium swimming through water experiences a drag force of about 0.09 in which unit?",
    "pN",
    "Using water's dynamic viscosity in SI units, the computed drag force is 0.09 pN, about what a swimming bacterium experiences.",
    stokes)
# 32 parasite area
paras = "For example, the Douglas DC-3 has an equivalent parasite area of 2.20 m2 (23.7 ft2) and the McDonnell Douglas DC-9, with 30 years of advancement in aircraft design, an area of 1.91 m2 (20.6 ft2) although it carried five times as many passengers."
rec('Drag (physics)', 2,
    "The Douglas DC-3 has an equivalent parasite area of 2.20 m2, which the same figure gives as how many ft2?",
    "23.7 ft2",
    "The DC-3's equivalent parasite area of 2.20 m2 is the same area expressed as 23.7 ft2 in the alternative unit.",
    paras)
rec('Drag (physics)', 1,
    "The McDonnell Douglas DC-9 has an equivalent parasite area of how many m2?",
    "1.91 m2",
    "With 30 years of design advancement, the DC-9's equivalent parasite area is 1.91 m2, quoted in square metres.",
    paras)
# 34
rec('Drag (physics)', 2,
    "For high-speed flow, drag force is proportional to the relative velocity raised to which power?",
    "2",
    "Drag is proportional to the velocity squared for high-speed flow, so the velocity enters to the power 2.",
    "Drag force is proportional to the relative velocity for low-speed flow and is proportional to the velocity squared for high-speed flow.")
# 35
rec('Drag (physics)', 2,
    "The power needed to push an object through a fluid increases as the cube of which quantity?",
    "velocity",
    "The power to overcome drag grows with the cube of the velocity, which is why small speed increases cost disproportionately more power.",
    "The power needed to push an object through a fluid increases as the cube of the velocity increases.")

# 36-45 Angstrom
ang_sym = "The unit's symbol is Å, which is a letter of the Swedish alphabet, regardless of how the unit is spelled."
rec('Angstrom', 1,
    "What is the symbol of the angstrom unit?",
    "Å",
    "The angstrom's symbol is Å, a letter of the Swedish alphabet, regardless of how the unit name is spelled.",
    ang_sym)
ang_nm = "In 1960, the metre itself was redefined in spectroscopic terms, which allowed the angstrom to be redefined as being exactly 0.1 nanometres."
rec('Angstrom', 1,
    "The angstrom was redefined as exactly 0.1 of which unit?",
    "nanometres",
    "After the metre's 1960 redefinition, the angstrom was redefined to be exactly 0.1 nanometres.",
    ang_nm)
rec('Angstrom', 2,
    "Since one angstrom is exactly 0.1 nanometres, how many angstroms equal one nanometre?",
    "10",
    "If 1 angstrom is 0.1 nanometres, then ten of them make one nanometre, since 10 × 0.1 = 1.",
    ang_nm)
ang_1010 = "In the late 19th century, spectroscopists adopted 10−10 of a metre as a convenient unit to express the wavelengths of characteristic spectral lines (monochromatic components of the emission spectrum) of chemical elements."
rec('Angstrom', 2,
    "In the late 19th century, spectroscopists adopted 10−10 of which unit as a convenient unit for spectral-line wavelengths?",
    "metre",
    "Spectroscopists took 10−10 of a metre as their convenient unit for expressing the wavelengths of characteristic spectral lines.",
    ang_1010)
radii = "The atomic (covalent) radii of phosphorus, sulfur, and chlorine are about 1 angstrom, while that of hydrogen is about 0.5 angstroms."
rec('Angstrom', 1,
    "The atomic covalent radius of phosphorus is about 1 in which unit?",
    "angstrom",
    "The covalent radii of phosphorus, sulfur, and chlorine are each about 1 angstrom, the unit suited to atomic-scale sizes.",
    radii)
rec('Angstrom', 1,
    "The covalent radius of hydrogen is about how many angstroms?",
    "0.5",
    "Hydrogen's covalent radius is about 0.5 angstroms, half the roughly 1-angstrom radii of phosphorus, sulfur, and chlorine.",
    radii)
rec('Angstrom', 1,
    "Visible light has wavelengths in the range of 4000–7000 in which unit?",
    "Å",
    "Visible-light wavelengths span 4000–7000 Å, the angstrom being the conventional unit for such short lengths.",
    "Visible light has wavelengths in the range of 4000–7000 Å.")
rec('Angstrom', 1,
    "Is the angstrom officially part of the International System of Units (SI)?",
    "No",
    "Although still widely used in physics and chemistry, the angstrom is not officially part of the SI.",
    "Although still widely used in physics and chemistry, the angstrom is not officially a part of the International System of Units (SI).")
rec('Angstrom', 2,
    "Ångström's 1868 chart of the solar spectrum expressed wavelengths in multiples of one ten-millionth of which unit?",
    "millimetre",
    "The 1868 chart used multiples of one ten-millionth of a millimetre (10−7 mm), the unit later named after Ångström.",
    "In 1868, Swedish physicist Anders Jonas Ångström created a chart of the spectrum of sunlight, in which he expressed the wavelengths of electromagnetic radiation in the electromagnetic spectrum in multiples of one ten-millionth of a millimetre (or 10−7 mm.)")
bohr = 'Ambiguously, the abbreviation "a.u." may also refer to the atomic unit of length, the bohr—about 0.53 Å—or the much larger astronomical unit (about 1.5×1011 m).'
rec('Angstrom', 2,
    "The atomic unit of length, the bohr, is about how many Å?",
    "0.53 Å",
    "The bohr, the atomic unit of length, measures about 0.53 Å, while the much larger astronomical unit is about 1.5×1011 m.",
    bohr)

# 46-47 Electromagnetism
rec('Electromagnetism', 1,
    "Formulas for physical laws of electromagnetism, such as Maxwell's equations, need to be adjusted depending on what?",
    "system of units",
    "Electromagnetic formulas must be adjusted to the system of units in use, because SI and CGS units do not correspond one-to-one.",
    "Formulas for physical laws of electromagnetism (such as Maxwell's equations) need to be adjusted depending on what system of units one uses.")
rec('Electromagnetism', 2,
    "In the electromagnetic CGS system, relative permeability is a dimensionless quantity whose value in vacuum is what?",
    "unity",
    "In the CGS system, relative permeability is dimensionless and takes the value unity (1) in vacuum.",
    "In the electromagnetic CGS system, electric current is a fundamental quantity defined via Ampère's law and takes the permeability as a dimensionless quantity (relative permeability) whose value in vacuum is unity.")

# ---- validation ----
errors = []
seen = set()
for i, r in enumerate(R, 1):
    if not has_quote(r['title'], r['quote']):
        errors.append("%d: quote not found verbatim in title '%s'" % (i, r['title']))
    norm = re.sub(r'\s+', ' ', r['question'].lower()).strip()
    if norm in seen:
        errors.append("%d: duplicate question" % i)
    seen.add(norm)
    if len(r['explanation']) > 400:
        errors.append("%d: explanation too long" % i)
    if r['difficulty'] not in (1, 2):
        errors.append("%d: bad difficulty" % i)
print("records:", len(R))
print("titles:", sorted({r['title'] for r in R}))
if errors:
    print("ERRORS:")
    for e in errors:
        print(" ", e)
    raise SystemExit(1)

out_dir = 'training/curriculum/authored/level1'
os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, 'dim_reasoning_b.jsonl')
with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
    for r in R:
        obj = {
            "source": "mango-authored-level1",
            "license": "CC0-1.0",
            "provenance": {"origin": "agent-authored", "corpus_title": r['title'], "quote": r['quote']},
            "domain": "scientific_reasoning",
            "family": "scientific_reasoning",
            "subject": "dimensional_reasoning",
            "difficulty": r['difficulty'],
            "curriculum_level": 1,
            "required_capability": "sci_dimensional_reasoning",
            "tool_eligible": False,
            "retrieval_eligible": True,
            "question": r['question'],
            "answer": r['answer'],
            "target_response": "Answer: \\boxed{" + r['answer'] + "}\n\n" + r['explanation'],
            "verification_state": "REVIEWED",
        }
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
print("written to", path)