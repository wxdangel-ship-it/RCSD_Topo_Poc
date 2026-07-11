from __future__ import annotations

import json

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json


def test_write_json_preserves_pretty_printed_bytes(tmp_path) -> None:
    path = tmp_path / "nested" / "payload.json"
    payload = {"中文": "保留", "values": [1, 2], "nested": {"ok": True}}

    write_json(path, payload)

    assert path.read_text(encoding="utf-8") == json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
