"""taxonomy — canonical Mango scientific domain taxonomy (T5.3).

Kept separate from evaluation.taxonomy (the T1/T2 *question-subject*
taxonomy for the eval suites): this module is the corpus-side *domain*
taxonomy used for retrieval classification and metadata filtering.

Mathematics is deliberately NOT a science domain here. Pure-math
questions should prefer deterministic computation (T4 tools); retrieval
for mathematics is available only through explicit MIXED routing.
"""
from __future__ import annotations

import re

# canonical tree: domain -> subjects
SCIENCE_TAXONOMY: dict[str, tuple[str, ...]] = {
    "physics": (
        "mechanics", "electromagnetism", "thermodynamics", "optics",
        "quantum", "relativity", "nuclear_particle",
    ),
    "chemistry": (
        "general", "organic", "inorganic", "physical", "analytical",
        "biochemistry",
    ),
    "biology": (
        "cell_biology", "genetics", "molecular_biology", "evolution",
        "ecology", "physiology", "microbiology",
    ),
    "astronomy": (
        "stellar", "planetary", "cosmology", "observational",
    ),
    "earth_science": (
        "geology", "meteorology", "oceanography", "climate_science",
    ),
    "computer_science": (),  # "where relevant" — no fixed subjects in v0.1
    "interdisciplinary": (),
}

# non-science top-level categories the router can classify into
NON_SCIENCE_DOMAINS = ("mathematics", "general")

DOMAINS = tuple(SCIENCE_TAXONOMY) + NON_SCIENCE_DOMAINS

# aliases -> canonical (domain, subject); subject "" = domain-level
_ALIASES: dict[str, tuple[str, str]] = {
    # physics
    "force": ("physics", "mechanics"), "motion": ("physics", "mechanics"),
    "newton": ("physics", "mechanics"), "kinematics": ("physics", "mechanics"),
    "energy": ("physics", "mechanics"),
    "electricity": ("physics", "electromagnetism"),
    "magnetism": ("physics", "electromagnetism"),
    "circuits": ("physics", "electromagnetism"),
    "heat": ("physics", "thermodynamics"),
    "temperature": ("physics", "thermodynamics"),
    "entropy": ("physics", "thermodynamics"),
    "light": ("physics", "optics"), "waves": ("physics", "optics"),
    "photon": ("physics", "quantum"),
    "relativity": ("physics", "relativity"),
    "radioactive": ("physics", "nuclear_particle"),
    "atoms": ("chemistry", "general"), "atom": ("chemistry", "general"),
    "elements": ("chemistry", "general"), "periodic_table": ("chemistry", "general"),
    "molecules": ("chemistry", "general"),
    "reaction": ("chemistry", "general"),
    "enzyme": ("biology", "biochemistry"),
    "cell": ("biology", "cell_biology"), "cells": ("biology", "cell_biology"),
    "organelle": ("biology", "cell_biology"),
    "mitochondria": ("biology", "cell_biology"),
    "ribosomes": ("biology", "cell_biology"),
    "dna": ("biology", "molecular_biology"), "rna": ("biology", "molecular_biology"),
    "protein": ("biology", "molecular_biology"),
    "gene": ("biology", "genetics"), "heredity": ("biology", "genetics"),
    "evolution": ("biology", "evolution"),
    "ecosystem": ("biology", "ecology"),
    "bacteria": ("biology", "microbiology"),
    "virus": ("biology", "microbiology"),
    "photosynthesis": ("biology", "biochemistry"),
    "star": ("astronomy", "stellar"), "stars": ("astronomy", "stellar"),
    "planet": ("astronomy", "planetary"), "planets": ("astronomy", "planetary"),
    "solar_system": ("astronomy", "planetary"),
    "universe": ("astronomy", "cosmology"),
    "telescope": ("astronomy", "observational"),
    "mars": ("astronomy", "planetary"), "jupiter": ("astronomy", "planetary"),
    "saturn": ("astronomy", "planetary"), "venus": ("astronomy", "planetary"),
    "neptune": ("astronomy", "planetary"), "pluto": ("astronomy", "planetary"),
    "moon": ("astronomy", "planetary"), "sun": ("astronomy", "stellar"),
    "electron": ("physics", "quantum"), "proton": ("physics", "nuclear_particle"),
    "neutron": ("physics", "nuclear_particle"),
    "gravity": ("physics", "mechanics"),
    "acceleration": ("physics", "mechanics"),
    "velocity": ("physics", "mechanics"),
    "momentum": ("physics", "mechanics"),
    "voltage": ("physics", "electromagnetism"),
    "current": ("physics", "electromagnetism"),
    "resistance": ("physics", "electromagnetism"),
    "magnet": ("physics", "electromagnetism"),
    "rocks": ("earth_science", "geology"), "minerals": ("earth_science", "geology"),
    "earth": ("earth_science", "geology"),
    "rain": ("earth_science", "meteorology"), "snow": ("earth_science", "meteorology"),
    "clouds": ("earth_science", "meteorology"),
    "hurricane": ("earth_science", "meteorology"),
    "climate": ("earth_science", "climate_science"),
    "volcano": ("earth_science", "geology"), "earthquake": ("earth_science", "geology"),
    "ocean": ("earth_science", "oceanography"),
    "plate_tectonics": ("earth_science", "geology"),
    "weather": ("earth_science", "meteorology"),
    "climate": ("earth_science", "climate_science"),
    "ocean": ("earth_science", "oceanography"),
}


def is_valid_domain(domain: str) -> bool:
    return domain in DOMAINS


def is_valid_subject(domain: str, subject: str) -> bool:
    if subject == "":
        return domain in SCIENCE_TAXONOMY or domain in NON_SCIENCE_DOMAINS
    return domain in SCIENCE_TAXONOMY and subject in SCIENCE_TAXONOMY[domain]


def normalize_domain(raw: str | None) -> str:
    """Map a raw domain string to the canonical taxonomy, or 'general'."""
    if not raw:
        return "general"
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in DOMAINS:
        return key
    if key in _ALIASES:
        return _ALIASES[key][0]
    # plural/singular and simple containment fallbacks
    singular = key[:-1] if key.endswith("s") else key
    if singular in DOMAINS:
        return singular
    if singular in _ALIASES:
        return _ALIASES[singular][0]
    for d, subjects in SCIENCE_TAXONOMY.items():
        if key in subjects or singular in subjects:
            return d
    for alias, (d, _s) in _ALIASES.items():
        if key == alias or singular == alias:
            return d
    return "general"


def classify_domain(question: str) -> str:
    """Cheap keyword classifier over the alias table (router-grade, not
    a model). Returns the canonical domain or 'general'. Whole-word
    matching only (no prefix false-positives like 'sun'/'sunlight')."""
    if not question:
        return "general"
    q = question.lower().replace("-", " ")
    best: tuple[int, str] | None = None
    for alias, (domain, _subject) in _ALIASES.items():
        token = alias.replace("_", " ")
        # plural tolerance: 'enzyme'/'enzymes', 'cell'/'cells'
        if re.search(rf"\b{re.escape(token)}(?:es|s)?\b", q):
            w = len(token)
            if best is None or w > best[0]:
                best = (w, domain)
    # direct domain-word matches beat any alias hit
    for d in SCIENCE_TAXONOMY:
        if re.search(rf"\b{re.escape(d.replace('_', ' '))}\b", q):
            return d
    return best[1] if best else "general"


def domain_path(domain: str) -> str:
    """Display path like 'science/physics/mechanics' or 'mathematics'."""
    if domain in SCIENCE_TAXONOMY:
        return f"science/{domain}"
    if domain == "mathematics":
        return "mathematics"
    return f"general/{domain}"