import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_schema_files_are_valid():
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)

