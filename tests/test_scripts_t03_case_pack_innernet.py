from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


SCRIPT_PATH = Path("scripts/t03_pack_failed_cases_first50_innernet.sh")
EXPECTED_CASE_IDS = (
    "705838",
    "706389",
    "706399",
    "708009",
    "709492",
    "723937",
    "724917",
    "759378",
    "768683",
    "787617",
    "793459",
    "823840",
    "830724",
    "836915",
    "837069",
    "857899",
    "864079",
    "864147",
    "867264",
    "895511",
    "899127",
    "899588",
    "909265",
    "912232",
    "920721",
    "922146",
    "928650",
    "949246",
    "950770",
    "952797",
    "954218",
    "991243",
    "992670",
    "992932",
    "994005",
    "994202",
    "995690",
    "995764",
    "997391",
    "998819",
    "1017385",
    "1019887",
    "1029724",
    "1042709",
    "1049277",
    "1056008",
    "1056150",
    "1062256",
    "1071049",
    "1071119",
)


def test_t03_failed_case_pack_script_uses_exact_first_50_ids_and_fixed_inputs() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    match = re.search(r"CASE_IDS=\((.*?)\n\)", text, flags=re.DOTALL)

    assert match is not None
    assert tuple(match.group(1).split()) == EXPECTED_CASE_IDS
    assert '/mnt/d/TestData/POC_QA/SWSD/nodes.gpkg' in text
    assert '/mnt/d/TestData/POC_QA/SWSD/roads.gpkg' in text
    assert '/mnt/d/TestData/POC_QA/Patch_vector/DriveZone.gpkg' in text
    assert '/mnt/d/TestData/POC_QA/Patch_vector/DivStripZone.gpkg' in text
    assert '/mnt/d/TestData/POC_QA/FRCSD/RCSDRoad.gpkg' in text
    assert '/mnt/d/TestData/POC_QA/FRCSD/RCSDNode.gpkg' in text
    assert "--decode-after-export 1" in text
    assert "--allow-partial-cases" not in text


def test_t03_failed_case_pack_script_has_valid_bash_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None:
        return

    subprocess.run([bash, "-n", str(SCRIPT_PATH)], check=True)
