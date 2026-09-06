"""Synthetic general-reasoning / instruction-behavior SFT items (T3).

A SMALL deterministic slice (~5-10% of the corpus) teaching response closure
and instruction compliance — the behavioral glue around math and science
content. Rules:
  * authored/generated deterministically from this file only;
  * every target closes with the canonical boxed answer marker;
  * phrasing is deliberately varied (scenario context, rotating templates)
    so items stay distinct under normalized/near-duplicate detection;
  * distinct by construction from the 18 sciencemath-eval-v1 synthetic items
    (different wording/content), and the corpus contamination gate re-checks
    every one of these against the frozen suite before the freeze;
  * calibration items teach honest "cannot be determined" for genuinely
    unanswerable questions — never for answerable ones.
All items are MIT (authored in this repository) and marked synthetic.
"""
from __future__ import annotations

from sciencemath.training.sft_format import (
    general_response,
    science_response,
)

SOURCE = "synthetic-sft-v1"
LICENSE = "MIT"


def _num(x: float) -> str:
    """Compact deterministic number formatting."""
    if float(x).is_integer():
        return str(int(x))
    return f"{x:g}"


def _items() -> list[dict]:
    items: list[dict] = []

    # ------------------------------------------------ instruction following
    # format-constrained short answers (content disjoint from the eval suite)
    instruction = [
        ("Reply with the single word: crimson", "crimson"),
        ("Reply with the single word: 23", "23"),
        ("How many letters are in the word 'gravity'? Reply with the number only.", "7"),
        ("What is the chemical symbol for potassium? Reply with the two-letter symbol only.", "K"),
        ("How many minutes are in one hour? Reply with the number only.", "60"),
        ("What is the SI unit of electric current? Reply with the unit name only.", "ampere"),
        ("Reply with the single word: photosynthesis", "photosynthesis"),
        ("State the boiling point of water in degrees Celsius as a bare number.", "100"),
        ("How many planets are in the Solar System? Reply with the number only.", "8"),
        ("What is the plural of 'criterion'? Reply with the single word only.", "criteria"),
        ("How many sides does an octagon have? Reply with the number as a word only.", "eight"),
        ("What is the SI unit of energy? Reply with the unit name only.", "joule"),
        ("How many hours are in two days? Reply with the number only.", "48"),
        ("What is the chemical symbol for iron? Reply with the two-letter symbol only.", "Fe"),
        ("State the number of degrees in a full circle as a bare number.", "360"),
        ("How many bones are in the adult human body (commonly cited count)? Reply with the number only.", "206"),
        ("What is the SI unit of power? Reply with the unit name only.", "watt"),
        ("How many minutes are in a quarter of an hour? Reply with the number only.", "15"),
        ("What is the chemical symbol for oxygen? Reply with the two-letter symbol only.", "O"),
        ("Spell the word 'science' backwards as a single word.", "ecneics"),
        ("How many vertices does a cube have? Reply with the number only.", "8"),
        ("What is the SI unit of frequency? Reply with the unit name only.", "hertz"),
        ("How many days are in the month of July? Reply with the number only.", "31"),
        ("What is the chemical symbol for gold? Reply with the two-letter symbol only.", "Au"),
        ("How many players from one team are on a soccer field at kickoff? Reply with the number only.", "11"),
        ("What is the SI unit of temperature? Reply with the unit name only.", "kelvin"),
        ("How many strings does a standard violin have? Reply with the number only.", "4"),
        ("What is the chemical symbol for silver? Reply with the two-letter symbol only.", "Ag"),
        ("How many moons does Mars have? Reply with the number only.", "2"),
        ("Reply with the single word: telescope", "telescope"),
        ("State the atomic number of helium as a bare number.", "2"),
        ("How many continents are there on Earth? Reply with the number only.", "7"),
    ]
    for q, a in instruction:
        items.append({
            "domain": "scientific_reasoning", "subject": "instruction_following",
            "question": q, "target": general_response(a),
            "answer_type": "text", "difficulty": 1,
        })

    # ------------------------------------------------------ unit conversion
    # scenario-wrapped, rotating phrasings so items stay near-dup-distinct
    conversion_specs = [
        (3, "kilometers", "meters", 1000.0,
         "A road sign outside Lyon shows a distance of {v} kilometers to the next city. Express this distance in meters."),
        (7, "kilometers", "meters", 1000.0,
         "A hiking trail is listed as {v} kilometers long. Convert this length to meters."),
        (12, "kilometers", "meters", 1000.0,
         "A cable spans a valley and measures {v} kilometers. How many meters long is the cable?"),
        (2.5, "kilometers", "meters", 1000.0,
         "A funicular route covers {v} kilometers. Give this route length in meters."),
        (36, "kilometers", "meters", 1000.0,
         "A cycling segment is {v} kilometers long. State the segment length in meters."),
        (1.2, "kilometers", "meters", 1000.0,
         "A model of a river reach represents {v} kilometers of the real river. How many meters is that?"),
        (4, "meters", "centimeters", 100.0,
         "A curtain rod is {v} meters long. Convert this length to centimeters."),
        (9, "meters", "centimeters", 100.0,
         "A classroom measures {v} meters across. Express this width in centimeters."),
        (6, "kilograms", "grams", 1000.0,
         "A bag of rice weighs {v} kilograms. How many grams does it weigh?"),
        (1.5, "kilograms", "grams", 1000.0,
         "A laboratory sample has a mass of {v} kilograms. State the mass in grams."),
        (0.5, "kilograms", "grams", 1000.0,
         "A spice jar contains {v} kilograms of paprika. Convert this mass to grams."),
        (8, "liters", "milliliters", 1000.0,
         "A water cooler bottle holds {v} liters. How many milliliters is that?"),
        (2, "liters", "milliliters", 1000.0,
         "A recipe uses {v} liters of stock. Convert this volume to milliliters."),
        (0.75, "liters", "milliliters", 1000.0,
         "A chemistry beaker contains {v} liters of solution. State the volume in milliliters."),
        (5, "hours", "minutes", 60.0,
         "A train journey takes {v} hours. How many minutes does the journey last?"),
        (3, "hours", "minutes", 60.0,
         "A flight is scheduled for {v} hours. Express the flight time in minutes."),
        (12, "hours", "minutes", 60.0,
         "A battery powered a sensor for {v} hours. Convert this duration to minutes."),
        (4, "minutes", "seconds", 60.0,
         "An animation loop lasts {v} minutes. How many seconds long is the loop?"),
        (2, "minutes", "seconds", 60.0,
         "A timer runs for {v} minutes. State the duration in seconds."),
        (45, "minutes", "seconds", 60.0,
         "A podcast segment lasts {v} minutes. Convert this segment length to seconds."),
        (10, "centimeters", "millimeters", 10.0,
         "A bolt is {v} centimeters long. How many millimeters is that?"),
        (25, "centimeters", "millimeters", 10.0,
         "A ruler marking sits at {v} centimeters. Express this position in millimeters."),
        (6, "days", "hours", 24.0,
         "A field experiment ran for {v} days. How many hours did it run?"),
        (2, "days", "hours", 24.0,
         "A fermentation batch takes {v} days. Convert this time to hours."),
        (3, "weeks", "days", 7.0,
         "A language course lasts {v} weeks. How many days does the course run?"),
        (5, "tonnes", "kilograms", 1000.0,
         "A truck carries {v} tonnes of gravel. Convert this mass to kilograms."),
    ]
    for val, src, dst, factor, template in conversion_specs:
        res = val * factor
        res_s = _num(res)
        q = template.format(v=_num(val))
        items.append({
            "domain": "scientific_reasoning", "subject": "unit_conversion",
            "question": q,
            "target": general_response(
                res_s, f"{_num(val)} {src} x {factor:g} = {res_s} {dst}."),
            "answer_type": "numeric", "difficulty": 1,
        })

    # ------------------------------------------------- clock/time arithmetic
    clock_specs = [
        (14, 45, 112, "A film starts at 14:45 and runs for 112 minutes with no break. At what clock time does it end? Reply as HH:MM."),
        (9, 20, 95, "A meeting begins at 09:20 and is scheduled to last 95 minutes. What clock time does the meeting end? Reply as HH:MM."),
        (22, 10, 140, "A night train departs at 22:10 and travels for 140 minutes. At what clock time does it arrive? Reply as HH:MM."),
        (7, 5, 50, "A bakery puts its first batch in the oven at 07:05 and bakes it for 50 minutes. At what clock time is the batch done? Reply as HH:MM."),
        (16, 40, 35, "A clinic appointment starts at 16:40 and takes 35 minutes. What clock time does the appointment end? Reply as HH:MM."),
        (11, 55, 80, "A lecture begins at 11:55 and runs 80 minutes. At what clock time does the lecture finish? Reply as HH:MM."),
        (18, 25, 65, "A choir rehearsal starts at 18:25 and lasts 65 minutes. What clock time does the rehearsal end? Reply as HH:MM."),
        (13, 15, 240, "A museum tour starts at 13:15 and takes 240 minutes. At what clock time does the tour conclude? Reply as HH:MM."),
    ]
    for h, m, dur, q in clock_specs:
        total = h * 60 + m + dur
        eh, em = total % (24 * 60) // 60, total % 60
        res = f"{eh:02d}:{em:02d}"
        items.append({
            "domain": "scientific_reasoning", "subject": "time_arithmetic",
            "question": q,
            "target": general_response(
                res, f"{h * 60 + m + dur} minutes after midnight is {res}."),
            "answer_type": "text", "difficulty": 2,
        })

    # ---------------------------------------------------------- comparisons
    comparison_specs = [
        ("A kettle holds 1.7 liters and a pitcher holds 1500 milliliters. Which holds more liquid? Reply with: kettle or pitcher.",
         "kettle", "1.7 liters = 1700 mL, which is more than 1500 mL."),
        ("Rope A is 250 centimeters long and rope B is 2.3 meters long. Which rope is longer? Reply with: rope A or rope B.",
         "rope A", "Rope A is 2.5 m, longer than rope B at 2.3 m."),
        ("Parcel X weighs 3.4 kilograms and parcel Y weighs 3400 grams. Do they weigh the same? Reply with: yes or no.",
         "yes", "3.4 kg equals 3400 g, so the parcels weigh the same."),
        ("A marathon is 42.195 kilometers. A 50-mile ultramarathon is longer. Is 50 miles more than 60 kilometers? Reply with: yes or no.",
         "yes", "50 miles is about 80.5 km, which exceeds 60 km."),
        ("Container A holds 2.5 liters and container B holds 2600 milliliters. Which container is larger? Reply with: container A or container B.",
         "container B", "Container B holds 2600 mL, more than container A's 2500 mL."),
        ("Bridge P is 1.2 kilometers long; bridge Q is 980 meters long. Which bridge is longer? Reply with: bridge P or bridge Q.",
         "bridge P", "Bridge P is 1200 m, longer than bridge Q at 980 m."),
    ]
    for q, a, expl in comparison_specs:
        items.append({
            "domain": "scientific_reasoning", "subject": "quantitative_comparison",
            "question": q, "target": general_response(a, expl),
            "answer_type": "text", "difficulty": 2,
        })

    # ------------------------------------------------------- logic deduction
    logic = [
        ("All bloops are razzies. All razzies are lazzies. Are all bloops definitely lazzies? Answer yes or no.",
         "yes", "Since every bloop is a razzie and every razzie is a lazzy, every bloop is a lazzy."),
        ("If it is raining, the ground gets wet. The ground is not wet. Is it raining? Answer yes or no.",
         "no", "Rain always wets the ground; a dry ground rules out rain (contrapositive)."),
        ("Every musician in the band can read music. Kim is in the band. Can Kim read music? Answer yes or no.",
         "yes", "Kim is a band member, and all band members can read music."),
        ("No reptile is warm-blooded. A snake is a reptile. Is a snake warm-blooded? Answer yes or no.",
         "no", "Snakes are reptiles, and no reptile is warm-blooded."),
        ("All squares are rectangles. A figure is not a rectangle. Is it a square? Answer yes or no.",
         "no", "If it were a square it would be a rectangle, which contradicts the given."),
        ("If a number is even, doubling it gives an even number. 6 is even. Is 12 even? Answer yes or no.",
         "yes", "12 is double 6, and doubling an even number gives an even number."),
        ("Every A is a B. Some B are C. Does it necessarily follow that some A are C? Answer yes or no.",
         "no", "The A's could all be among the B's that are not C, so it does not follow."),
        ("Tom is taller than Sara. Sara is taller than Mia. Is Tom taller than Mia? Answer yes or no.",
         "yes", "Height ordering is transitive: Tom > Sara > Mia."),
        ("Every entry ticket includes a free map. Ana bought an entry ticket. Did Ana get a free map? Answer yes or no.",
         "yes", "Ana's ticket includes a free map by the stated rule."),
        ("Only members may enter the archive. Ben entered the archive. Is Ben a member? Answer yes or no.",
         "yes", "Entry is restricted to members, so anyone inside must be a member."),
    ]
    for q, a, expl in logic:
        items.append({
            "domain": "scientific_reasoning", "subject": "logic_deduction",
            "question": q, "target": general_response(a, expl),
            "answer_type": "text", "difficulty": 2,
        })

    # -------------------------------------------------------- calibration
    # genuinely unanswerable -> honest uncertainty (never for answerable Qs)
    calibration = [
        ("What will be the exact price of gasoline in Brazil on 4 June 2031?",
         "The exact future price cannot be determined."),
        ("How many raindrops fell on Tokyo at exactly 12:00 UTC on 3 May 1740?",
         "No records exist; the exact count cannot be determined."),
        ("What is the exact number of stars in the Milky Way as counted one by one?",
         "Stars cannot be counted one by one; the exact number cannot be determined."),
        ("What will the winning lottery numbers be next Saturday?",
         "Future lottery numbers cannot be determined in advance."),
        ("What was the name of the first person to ever boil water?",
         "Prehistoric events have no records; the name cannot be determined."),
        ("What exact thought will you have at 3:00 pm next Tuesday?",
         "A future private thought cannot be determined."),
        ("How many grains of sand exist on Earth at this exact moment?",
         "The exact instantaneous count cannot be determined."),
        ("What is the exact height of the tallest tree on Earth in centimeters, measured today?",
         "No complete survey exists; the exact value cannot be determined."),
        ("Which person will be born first next year?",
         "A future event like this cannot be determined in advance."),
        ("What did Julius Caesar dream about on the night before 10 January 49 BCE?",
         "Private dreams leave no historical record; this cannot be determined."),
        ("How many fish are swimming in the ocean at this very second?",
         "The exact instantaneous count cannot be determined."),
        ("What will tomorrow's headline in a newspaper I have not chosen say?",
         "A future, unspecified headline cannot be determined."),
    ]
    for q, expl in calibration:
        items.append({
            "domain": "scientific_reasoning", "subject": "uncertainty",
            "question": q, "target": science_response("cannot be determined", expl),
            "answer_type": "text", "difficulty": 1,
        })

    # ------------------------------------------------- scientific reasoning
    # short explanation-quality items (single verified facts, not eval items)
    facts = [
        ("Why do objects fall toward the ground on Earth?",
         "gravity", "Earth's gravity pulls objects toward its center."),
        ("What gas do plants primarily absorb for photosynthesis?",
         "carbon dioxide", "Plants take in carbon dioxide and release oxygen during photosynthesis."),
        ("What particles orbit the nucleus of an atom?",
         "electrons", "Electrons occupy orbitals around the positively charged nucleus."),
        ("What organ pumps blood through the human body?",
         "the heart", "The heart is a muscular pump driving blood through the circulatory system."),
        ("What process splits an atomic nucleus into smaller nuclei?",
         "nuclear fission", "Fission splits a heavy nucleus, releasing energy and neutrons."),
        ("What is the main source of energy for Earth's climate system?",
         "the Sun", "Solar radiation drives virtually all of Earth's climate energy input."),
        ("What molecule carries genetic instructions in living cells?",
         "DNA", "DNA stores hereditary information in its base sequence."),
        ("What happens to the volume of a gas when it is heated at constant pressure?",
         "it increases", "Charles's law: volume is proportional to absolute temperature at fixed pressure."),
        ("Why does ice float on liquid water?",
         "ice is less dense than water", "Water expands as it freezes, so ice has lower density and floats."),
        ("What force keeps the planets in orbit around the Sun?",
         "gravity", "The Sun's gravity provides the centripetal force holding planets in orbit."),
        ("What is the process by which plants lose water vapor through leaves?",
         "transpiration", "Transpiration moves water from roots to leaves, where it evaporates."),
        ("What type of energy is stored in a stretched spring?",
         "elastic potential energy", "Deforming the spring stores elastic potential energy."),
    ]
    for q, a, expl in facts:
        items.append({
            "domain": "scientific_reasoning", "subject": "scientific_reasoning",
            "question": q, "target": science_response(expl, a),
            "answer_type": "text", "difficulty": 1,
        })

    # ------------------------------------------- science vocabulary/tools
    vocab = [
        ("Which instrument measures atmospheric pressure? Reply with the instrument name only.",
         "barometer", "A barometer measures atmospheric pressure."),
        ("Which instrument measures temperature? Reply with the instrument name only.",
         "thermometer", "A thermometer measures temperature."),
        ("Which laboratory tool is used to view very small cells? Reply with the tool name only.",
         "microscope", "Optical microscopes magnify cells for observation."),
        ("What is the SI unit of mass? Reply with the unit name only.",
         "kilogram", "The kilogram is the SI base unit of mass."),
        ("Which instrument measures atmospheric humidity? Reply with the instrument name only.",
         "hygrometer", "A hygrometer measures moisture in the air."),
        ("What is the SI unit of force? Reply with the unit name only.",
         "newton", "Force is measured in newtons."),
        ("Which instrument is used to detect earthquakes? Reply with the instrument name only.",
         "seismograph", "Seismographs record ground motion from earthquakes."),
        ("What is the SI unit of pressure? Reply with the unit name only.",
         "pascal", "Pressure is measured in pascals (N/m^2)."),
        ("Which cloud type brings thunderstorms? Reply with the cloud name only.",
         "cumulonimbus", "Cumulonimbus clouds are associated with thunderstorms."),
        ("What is the pH of a neutral solution at 25 degrees Celsius? Reply with the number only.",
         "7", "Neutral water at 25 C has pH 7."),
        ("How many chambers does the human heart have? Reply with the number only.",
         "4", "The heart has two atria and two ventricles."),
        ("What blood vessels carry blood away from the heart? Reply with the vessel name only.",
         "arteries", "Arteries carry blood away from the heart."),
        ("Which organ produces insulin? Reply with the organ name only.",
         "the pancreas", "Beta cells in the pancreas secrete insulin."),
        ("What is the most abundant gas in Earth's atmosphere? Reply with the gas name only.",
         "nitrogen", "Nitrogen makes up about 78% of the atmosphere."),
        ("Which planet is closest to the Sun? Reply with the planet name only.",
         "Mercury", "Mercury orbits closest to the Sun."),
        ("What is the hardest naturally occurring mineral? Reply with the mineral name only.",
         "diamond", "Diamond scores 10 on the Mohs hardness scale."),
        ("What kind of rock forms from cooled magma? Reply with the rock type only.",
         "igneous rock", "Igneous rock solidifies from molten magma or lava."),
        ("What gas do humans exhale as a metabolic waste product? Reply with the gas name only.",
         "carbon dioxide", "Cellular respiration produces CO2, exhaled by the lungs."),
        ("Which particle carries a negative electric charge? Reply with the particle name only.",
         "electron", "Electrons carry a -1 elementary charge."),
        ("What organelle is known as the powerhouse of the cell? Reply with the organelle name only.",
         "mitochondrion", "Mitochondria produce most cellular ATP."),
        ("What is the process of a liquid changing into a gas called? Reply with the process name only.",
         "evaporation", "Evaporation is the liquid-to-gas phase change."),
        ("Which scientist proposed the three laws of motion? Reply with the scientist's name only.",
         "Newton", "Isaac Newton formulated the three laws of motion."),
        ("What is the largest planet in the Solar System? Reply with the planet name only.",
         "Jupiter", "Jupiter has more mass than all other planets combined."),
        ("What metal is liquid at room temperature? Reply with the metal name only.",
         "mercury", "Mercury melts at -39 C, so it is liquid at room temperature."),
    ]
    for q, a, expl in vocab:
        items.append({
            "domain": "scientific_reasoning", "subject": "science_vocabulary",
            "question": q, "target": science_response(expl, a),
            "answer_type": "text", "difficulty": 1,
        })

    # ------------------------------------------------------ ordering/limits
    ordering = [
        ("List these states of matter from coldest to hottest typical arrangement: gas, solid, liquid. Reply with the three words in order, separated by commas.",
         "solid, liquid, gas",
         "Solids are typically coldest, then liquids, then gases."),
        ("Arrange these lengths from shortest to longest: 1 meter, 90 centimeters, 0.1 kilometers. Reply in order separated by commas.",
         "90 centimeters, 1 meter, 0.1 kilometers",
         "90 cm < 100 cm < 10000 cm."),
        ("Arrange these durations from shortest to longest: 90 minutes, 2 hours, 1 day. Reply in order separated by commas.",
         "90 minutes, 2 hours, 1 day",
         "90 minutes < 120 minutes (2 hours) < 24 hours (1 day)."),
        ("Which temperature is highest: 15 degrees Celsius, 290 kelvin, or 60 degrees Fahrenheit? Reply with one of the three.",
         "290 kelvin",
         "15 C = 288 K = 59 F; 290 K is about 17 C, the highest of the three."),
        ("Put these planets in order from the Sun: Earth, Mercury, Mars. Reply in order separated by commas.",
         "Mercury, Earth, Mars",
         "Orbital order from the Sun is Mercury, Earth, then Mars."),
    ]
    for q, a, expl in ordering:
        items.append({
            "domain": "scientific_reasoning", "subject": "quantitative_comparison",
            "question": q, "target": general_response(a, expl),
            "answer_type": "text", "difficulty": 2,
        })

    # ------------------------------------- more conversion scenarios (v2)
    conversion_specs_v2 = [
        (90, "km/h", "m/s", None,
         "A car travels at {v} km/h. Express this speed in meters per second (1 km/h = 1/3.6 m/s).",
         "25", "90 km/h / 3.6 = 25 m/s."),
        (72, "km/h", "m/s", None,
         "A cyclist's peak speed is {v} km/h. Convert this speed to meters per second.",
         "20", "72 km/h / 3.6 = 20 m/s."),
        (3, "m^2", "cm^2", None,
         "A solar cell has area {v} square meters. How many square centimeters is that?",
         "30000", "1 m^2 = 10000 cm^2, so 3 m^2 = 30000 cm^2."),
        (0.5, "m^2", "cm^2", None,
         "A whiteboard covers {v} square meters of wall. Convert this area to square centimeters.",
         "5000", "0.5 m^2 x 10000 = 5000 cm^2."),
        (2, "m^3", "liters", None,
         "A small pool holds {v} cubic meters of water. Convert this volume to liters.",
         "2000", "1 m^3 = 1000 L, so 2 m^3 = 2000 L."),
        (350, "mL", "liters", None,
         "A soft-drink can contains {v} milliliters. Express this volume in liters.",
         "0.35", "350 mL = 0.35 L."),
        (2.5, "GB", "MB", None,
         "A software download is {v} gigabytes. How many megabytes is that (1 GB = 1000 MB)?",
         "2500", "2.5 GB x 1000 = 2500 MB."),
        (500, "mA", "A", None,
         "A phone charger outputs {v} milliamperes. Convert this current to amperes.",
         "0.5", "500 mA = 0.5 A."),
        (1.5, "tonnes", "kg", None,
         "A delivery of steel weighs {v} tonnes. How many kilograms is that?",
         "1500", "1.5 t x 1000 = 1500 kg."),
        (180, "s", "minutes", None,
         "A process takes {v} seconds. State this duration in minutes.",
         "3", "180 s / 60 = 3 minutes."),
        (48, "h", "days", None,
         "A storm warning is in effect for {v} hours. How many days is that?",
         "2", "48 h / 24 = 2 days."),
        (5, "m", "mm", None,
         "A copper pipe is {v} meters long. Convert this length to millimeters.",
         "5000", "5 m x 1000 = 5000 mm."),
        (0.25, "km", "m", None,
         "A sprint segment measures {v} kilometers. How many meters is that?",
         "250", "0.25 km x 1000 = 250 m."),
        (1200, "g", "kg", None,
         "A flour sack label reads {v} grams. Convert this mass to kilograms.",
         "1.2", "1200 g / 1000 = 1.2 kg."),
    ]
    for val, src, dst, _, template, res_s, expl in conversion_specs_v2:
        q = template.format(v=_num(val))
        items.append({
            "domain": "scientific_reasoning", "subject": "unit_conversion",
            "question": q, "target": general_response(res_s, expl),
            "answer_type": "numeric", "difficulty": 2,
        })

    # ------------------------------------------- more clock scenarios (v2)
    clock_v2 = [
        ("A bus leaves the depot at 06:50 and its route takes 85 minutes. At what clock time does the bus finish its route? Reply as HH:MM.", "08:15"),
        ("A load of laundry starts at 19:05 and the cycle runs 105 minutes. At what clock time does the cycle end? Reply as HH:MM.", "20:50"),
        ("A ferry departs at 12:30 and the crossing takes 3 hours and 20 minutes. At what clock time does it dock? Reply as HH:MM.", "15:40"),
        ("A security shift starts at 21:30 and lasts 8 hours. At what clock time does it end? Reply as HH:MM.", "05:30"),
        ("An exam begins at 09:00 and lasts 2 hours and 30 minutes. At what clock time does the exam end? Reply as HH:MM.", "11:30"),
        ("A cake needs 40 minutes in the oven and goes in at 15:25. At what clock time should it come out? Reply as HH:MM.", "16:05"),
        ("A webinar starts at 17:45 and runs for 75 minutes. At what clock time does it finish? Reply as HH:MM.", "19:00"),
        ("A night-shift nurse's round begins at 23:20 and takes 110 minutes. At what clock time is the round complete? Reply as HH:MM.", "01:10"),
        ("A train due at 08:40 is running 25 minutes late. At what clock time will it arrive? Reply as HH:MM.", "09:05"),
        ("A parking session begins at 10:15 and is paid for 190 minutes. At what clock time does it expire? Reply as HH:MM.", "13:25"),
        ("A radio bulletin airs every hour starting 06:00; a listener tunes in 3 hours and 10 minutes after the first bulletin. At what clock time is the listener tuning in? Reply as HH:MM.", "09:10"),
        ("A robot vacuum starts at 13:05 and cleans for 95 minutes. At what clock time does it stop? Reply as HH:MM.", "14:40"),
    ]
    for q, res in clock_v2:
        h, m = map(int, res.split(":"))
        expl = f"{int(res[:2]) * 60 + m} minutes after midnight is {res}."
        items.append({
            "domain": "scientific_reasoning", "subject": "time_arithmetic",
            "question": q, "target": general_response(res, expl),
            "answer_type": "text", "difficulty": 2,
        })

    # ------------------------------------------- more instruction items (v2)
    instruction_v2 = [
        ("How many letters are in the word 'momentum'? Reply with the number only.", "8"),
        ("How many letters are in the word 'enzyme'? Reply with the number only.", "6"),
        ("What is the chemical symbol for copper? Reply with the two-letter symbol only.", "Cu"),
        ("What is the chemical symbol for calcium? Reply with the two-letter symbol only.", "Ca"),
        ("What is the SI unit of capacitance? Reply with the unit name only.", "farad"),
        ("What is the SI unit of resistance? Reply with the unit name only.", "ohm"),
        ("How many sides does a hexagon have? Reply with the number only.", "6"),
        ("How many edges does a triangular prism have? Reply with the number only.", "9"),
        ("State the melting point of water in degrees Celsius as a bare number.", "0"),
        ("How many seconds are in five minutes? Reply with the number only.", "300"),
        ("How many days are in a common (non-leap) year? Reply with the number only.", "365"),
        ("Reply with the single word: orbit", "orbit"),
        ("Reply with the single word: 87", "87"),
        ("Spell the word 'logic' backwards as a single word.", "negol"),
        ("What is the plural of 'phenomenon'? Reply with the single word only.", "phenomena"),
        ("How many colors are in a rainbow (traditional count)? Reply with the number only.", "7"),
        ("What is the SI unit of magnetic field strength? Reply with the unit name only.", "tesla"),
        ("How many strokes are in a four-stroke engine's cycle? Reply with the number only.", "4"),
        ("What is the chemical symbol for helium? Reply with the two-letter symbol only.", "He"),
        ("How many legs does an insect have? Reply with the number only.", "6"),
    ]
    for q, a in instruction_v2:
        items.append({
            "domain": "scientific_reasoning", "subject": "instruction_following",
            "question": q, "target": general_response(a),
            "answer_type": "text", "difficulty": 1,
        })

    return items


def synthetic_general_records() -> list[dict]:
    """All synthetic general items as raw target-bearing records."""
    out = []
    for i, it in enumerate(_items()):
        out.append({
            "source": SOURCE, "license": LICENSE, "synthetic": True,
            "source_id": f"synth-sft-{i:03d}",
            "domain": it["domain"], "subject": it["subject"],
            "difficulty": it["difficulty"], "answer_type": it["answer_type"],
            "question": it["question"],
            "answer": it["target"],   # pre-built canonical target
        })
    return out