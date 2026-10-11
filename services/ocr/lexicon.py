"""Lexicons and OCR-noise-tolerant matching for medication labels.

Only standard generic drug names are listed. The lexicon is used to *recognize*
tokens that already exist in the source text, optionally correcting predictable
OCR character confusions (``Metform1n`` -> ``Metformin``). It is never used to
invent a name that is absent from the source text.
"""

from __future__ import annotations

from typing import Iterable

# Standard generic (INN) names used by the synthetic test set and typical labels.
DRUG_NAMES: tuple[str, ...] = (
    "Acetaminophen",
    "Albuterol",
    "Amlodipine",
    "Amoxicillin",
    "Atorvastatin",
    "Azithromycin",
    "Bupropion",
    "Carvedilol",
    "Cephalexin",
    "Cetirizine",
    "Ciprofloxacin",
    "Clopidogrel",
    "Doxycycline",
    "Escitalopram",
    "Finasteride",
    "Fluconazole",
    "Furosemide",
    "Gabapentin",
    "Hydrochlorothiazide",
    "Ibuprofen",
    "Levothyroxine",
    "Lisinopril",
    "Losartan",
    "Metformin",
    "Metoprolol",
    "Montelukast",
    "Naproxen",
    "Omeprazole",
    "Pantoprazole",
    "Prednisone",
    "Rosuvastatin",
    "Sertraline",
    "Simvastatin",
    "Sitagliptin",
    "Spironolactone",
    "Tamsulosin",
    "Tramadol",
    "Trazodone",
    "Valsartan",
    "Warfarin",
    "Acyclovir",
    "Advil",
    "Alendronate",
    "Aleve",
    "Allegra",
    "Allopurinol",
    "Alprazolam",
    "Amitriptyline",
    "Apixaban",
    "Aripiprazole",
    "Aspirin",
    "Atenolol",
    "Baclofen",
    "Benadryl",
    "Benazepril",
    "Benzonatate",
    "Bisacodyl",
    "Bisoprolol",
    "Bumetanide",
    "Buspirone",
    "Candesartan",
    "Carbamazepine",
    "Cefuroxime",
    "Celecoxib",
    "Chlorthalidone",
    "Citalopram",
    "Claritin",
    "Clindamycin",
    "Clonazepam",
    "Clonidine",
    "Colchicine",
    "Crestor",
    "Cyanocobalamin",
    "Cyclobenzaprine",
    "Dapagliflozin",
    "Dexamethasone",
    "Dextromethorphan",
    "Diazepam",
    "Diclofenac",
    "Digoxin",
    "Diltiazem",
    "Diphenhydramine",
    "Docusate",
    "Donepezil",
    "Duloxetine",
    "Empagliflozin",
    "Enalapril",
    "Esomeprazole",
    "Estradiol",
    "Ezetimibe",
    "Famotidine",
    "Fenofibrate",
    "Fexofenadine",
    "Fluoxetine",
    "Fluticasone",
    "Gemfibrozil",
    "Glimepiride",
    "Glipizide",
    "Glucophage",
    "Glyburide",
    "Guaifenesin",
    "Hydralazine",
    "Hydrocodone",
    "Hydroxychloroquine",
    "Hydroxyzine",
    "Irbesartan",
    "Isosorbide",
    "Labetalol",
    "Lamotrigine",
    "Lansoprazole",
    "Levetiracetam",
    "Levocetirizine",
    "Levofloxacin",
    "Lexapro",
    "Linagliptin",
    "Liothyronine",
    "Lipitor",
    "Lithium",
    "Loperamide",
    "Loratadine",
    "Lorazepam",
    "Lovastatin",
    "Medroxyprogesterone",
    "Melatonin",
    "Meloxicam",
    "Memantine",
    "Methocarbamol",
    "Methotrexate",
    "Methylprednisolone",
    "Metoclopramide",
    "Metronidazole",
    "Mirtazapine",
    "Morphine",
    "Motrin",
    "Mucinex",
    "Nebivolol",
    "Nexium",
    "Nifedipine",
    "Nitrofurantoin",
    "Nortriptyline",
    "Norvasc",
    "Olanzapine",
    "Olmesartan",
    "Ondansetron",
    "Oseltamivir",
    "Oxybutynin",
    "Oxycodone",
    "Paroxetine",
    "Penicillin",
    "Pepcid",
    "Pioglitazone",
    "Pramipexole",
    "Pravastatin",
    "Prednisolone",
    "Pregabalin",
    "Prilosec",
    "Propranolol",
    "Prozac",
    "Pseudoephedrine",
    "Quetiapine",
    "Raloxifene",
    "Ramipril",
    "Ranitidine",
    "Risperidone",
    "Rivaroxaban",
    "Robitussin",
    "Ropinirole",
    "Sildenafil",
    "Simethicone",
    "Singulair",
    "Sudafed",
    "Sulfamethoxazole",
    "Sumatriptan",
    "Synthroid",
    "Tadalafil",
    "Telmisartan",
    "Tizanidine",
    "Topiramate",
    "Torsemide",
    "Triamterene",
    "Trimethoprim",
    "Tylenol",
    "Valacyclovir",
    "Venlafaxine",
    "Verapamil",
    "Xanax",
    "Zantac",
    "Zocor",
    "Zoloft",
    "Zolpidem",
    "Zyrtec",
)

_NAME_INDEX: dict[str, str] = {name.casefold(): name for name in DRUG_NAMES}

# Salt / release / dosage-form suffix tokens that may trail a drug name.
SALT_SUFFIXES: frozenset[str] = frozenset(
    {
        "hydrochloride",
        "hydrobromide",
        "hcl",
        "hci",  # OCR confusion of HCl
        "hc1",
        "sodium",
        "potassium",
        "calcium",
        "magnesium",
        "tartrate",
        "bitartrate",
        "succinate",
        "maleate",
        "fumarate",
        "besylate",
        "bisulfate",
        "mesylate",
        "citrate",
        "phosphate",
        "sulfate",
        "sulphate",
        "acetate",
        "hyclate",
        "monohydrate",
        "dihydrate",
        "anhydrous",
        "mononitrate",
        "dinitrate",
        "lactate",
        "gluconate",
        "carbonate",
        "chloride",
        "nitrate",
        "usp",
        "ip",
        "bp",
        "er",
        "xr",
        "sr",
        "cr",
        "xl",
        "md",
        "hct",
    }
)

# Dosage form words -> canonical singular form.
FORM_CANONICAL: dict[str, str] = {
    "tablet": "tablet",
    "tablets": "tablet",
    "table": "tablet",  # OCR-truncated "TABLE(T|TS)"
    "tab": "tablet",
    "tabs": "tablet",
    "caplet": "caplet",
    "caplets": "caplet",
    "capsule": "capsule",
    "capsules": "capsule",
    "cap": "capsule",
    "caps": "capsule",
    "softgel": "softgel",
    "softgels": "softgel",
    "gelcap": "gelcap",
    "gelcaps": "gelcap",
    "pill": "pill",
    "pills": "pill",
    "solution": "solution",
    "solutions": "solution",
    "suspension": "suspension",
    "syrup": "syrup",
    "elixir": "elixir",
    "cream": "cream",
    "ointment": "ointment",
    "gel": "gel",
    "drop": "drops",
    "drops": "drops",
    "spray": "spray",
    "sprays": "spray",
    "inhaler": "inhaler",
    "inhalation": "inhalation",
    "injection": "injection",
    "patch": "patch",
    "patches": "patch",
    "suppository": "suppository",
    "suppositories": "suppository",
    "powder": "powder",
    "lozenge": "lozenge",
    "lozenges": "lozenge",
    "sachet": "sachet",
    "sachets": "sachet",
}

# Mass / concentration unit -> canonical unit string.
UNIT_CANONICAL: dict[str, str] = {
    "mg": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "mcg": "mcg",
    "ug": "mcg",
    "µg": "mcg",
    "microgram": "mcg",
    "micrograms": "mcg",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "iu": "IU",
    "unit": "unit",
    "units": "unit",
    "%": "%",
}

# Characters that OCR commonly confuses inside numeric tokens.
CONFUSABLE_DIGITS: dict[str, str] = {
    "o": "0",
    "O": "0",
    "q": "9",
    "Q": "9",
    "i": "1",
    "I": "1",
    "l": "1",
    "s": "5",
    "S": "5",
    "b": "8",
    "B": "8",
    "z": "2",
    "Z": "2",
    "g": "6",
    "G": "6",
}

# Digits that OCR commonly confuses inside letter tokens.
CONFUSABLE_LETTERS: dict[str, str] = {
    "0": "o",
    "1": "l",
    "2": "z",
    "3": "e",
    "4": "a",
    "5": "s",
    "6": "g",
    "7": "t",
    "8": "b",
    "9": "g",
}
CONFUSABLE_LETTERS_ALT: dict[str, str] = {"1": "i"}


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return UNIT_CANONICAL.get(unit.casefold(), unit.casefold())


def normalize_form(word: str | None) -> str | None:
    if word is None:
        return None
    return FORM_CANONICAL.get(word.casefold())


def _alnum(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def normalize_for_match(token: str, mapping: dict[str, str] = CONFUSABLE_LETTERS) -> str:
    """Casefold, map digit confusions, then collapse common OCR joins."""
    mapped = "".join(mapping.get(ch, ch) for ch in _alnum(token))
    mapped = mapped.replace("rn", "m").replace("vv", "w")
    return mapped


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def _distance_threshold(length: int) -> int:
    if length >= 9:
        return 2
    if length >= 6:
        return 1
    return 0


def match_drug_name(token: str, extra_names: Iterable[str] = ()) -> tuple[str, int] | None:
    """Match one token against the lexicon.

    Returns ``(canonical_name, edit_distance)`` or ``None``. A match requires the
    normalized token to align with a known name (same first letter when fuzzy) and
    a suffix that is empty, a known salt/release suffix, or a glued strength/form
    fragment (``LEVOTHYROXINE100MCGTABLETS``). This recognizes names that exist in
    the source text; it never synthesizes new ones.
    """
    norm = normalize_for_match(token)
    plain = "".join(ch for ch in token.casefold() if ch.isalnum())
    if len(norm) < 4 and len(plain) < 4:
        return None
    best: tuple[str, int] | None = None
    candidates = list(_NAME_INDEX.items()) + [(n.casefold(), n) for n in extra_names]
    # Glued OCR token: name directly followed by strength/form/salt characters.
    for name_norm, canonical in candidates:
        if plain.startswith(name_norm) and glued_remainder_ok(plain[len(name_norm) :]):
            return canonical, 0
    variants = {norm}
    alt = normalize_for_match(token, CONFUSABLE_LETTERS_ALT)
    variants.add(alt)
    for variant in variants:
        for name_norm, canonical in candidates:
            if not name_norm:
                continue
            # Direct match (with optional salt/form suffix glued on by OCR).
            if variant == name_norm:
                distance = 0
            elif variant.startswith(name_norm) and _is_suffixish(variant[len(name_norm):]):
                distance = 0
            elif variant.endswith(name_norm) and _is_suffixish(variant[: -len(name_norm)]):
                distance = 0
            else:
                threshold = _distance_threshold(len(name_norm))
                distance = _levenshtein(variant, name_norm)
                if distance == 0 or distance > threshold:
                    continue
                if variant[:1] != name_norm[:1]:
                    continue
            if best is None or distance < best[1] or (distance == best[1] and canonical < best[0]):
                best = (canonical, distance)
                if distance == 0:
                    return best
    return best


def _is_suffixish(remainder: str) -> bool:
    return remainder == "" or remainder in SALT_SUFFIXES or normalize_form(remainder) is not None


def glued_remainder_ok(remainder: str) -> bool:
    """True when an OCR-glued token remainder can follow a drug name.

    Accepts ``""``, salt/release suffixes, and remainders that start with a
    digit (glued strength + form, e.g. ``100MCGTABLETS``).
    """
    if remainder == "":
        return True
    if remainder in SALT_SUFFIXES:
        return True
    if any(remainder.startswith(salt) for salt in SALT_SUFFIXES):
        return True
    return remainder[0].isdigit()


def normalized_variants(text: str) -> tuple[str, ...]:
    """All OCR-noise normalizations of a token (deduplicated)."""
    return tuple({normalize_for_match(text), normalize_for_match(text, CONFUSABLE_LETTERS_ALT)})


def name_similarity(left: str, right: str) -> float:
    """Similarity in ``[0, 1]`` between two drug names, tolerant to OCR noise.

    Handles case, spacing, digit/letter confusions (``1``<->``l``/``i``,
    ``0``<->``o``, ``5``<->``s``), glued salt/strength suffixes, and small edit
    distances. Used by the registered-candidate matcher; it compares names that
    are already present in the inputs and never looks names up on its own.
    """
    if not left or not right:
        return 0.0
    best = 0.0
    for a in normalized_variants(left):
        if not a:
            continue
        for b in normalized_variants(right):
            if not b:
                continue
            if a == b:
                return 1.0
            if a.startswith(b) and glued_remainder_ok(a[len(b) :]):
                best = max(best, 0.97)
                continue
            if b.startswith(a) and glued_remainder_ok(b[len(a) :]):
                best = max(best, 0.97)
                continue
            distance = _levenshtein(a, b)
            best = max(best, 1.0 - distance / max(len(a), len(b)))
    return max(0.0, min(1.0, best))
