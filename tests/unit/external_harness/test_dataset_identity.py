import json

from app.external_harness.dataset_identity import canonical_dataset_sha256


def test_dataset_identity_ignores_json_formatting_and_line_endings(tmp_path) -> None:
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    value = {"schema_version": "v1", "cases": [{"id": "a", "question": "政策"}]}
    compact.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8", newline="\n")
    pretty.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\r\n",
    )

    assert canonical_dataset_sha256(compact) == canonical_dataset_sha256(pretty)
