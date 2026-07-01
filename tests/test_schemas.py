import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


def test_schema_files_are_valid():
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_worker_prompt_result_fields_exist_in_result_schema():
    prompt = Path("prompts/worker_prompt.md").read_text(encoding="utf-8")
    schema = json.loads(Path("schemas/result.schema.json").read_text(encoding="utf-8"))
    match = re.search(r"```json\s*(\{.*?\})\s*```", prompt, re.DOTALL)
    assert match, "worker prompt must include a JSON output contract"

    prompt_fields = set(re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:', match.group(1)))
    schema_fields = set(schema["properties"])

    assert prompt_fields <= schema_fields


def test_result_schema_required_fields_are_in_prompt_or_orchestrator_injected():
    prompt = Path("prompts/worker_prompt.md").read_text(encoding="utf-8")
    schema = json.loads(Path("schemas/result.schema.json").read_text(encoding="utf-8"))
    match = re.search(r"```json\s*(\{.*?\})\s*```", prompt, re.DOTALL)
    assert match, "worker prompt must include a JSON output contract"

    prompt_fields = set(re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:', match.group(1)))
    orchestrator_injected = {
        "task_id",
        "model_used",
        "tests_run",
        "tests_passed",
        "diff_path",
        "needs_user",
    }

    required_fields = set(schema["required"])
    assert required_fields <= prompt_fields | orchestrator_injected
