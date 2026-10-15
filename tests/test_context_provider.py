import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aidub.context import CONTEXT_SCHEMA, context_request, validate_context_response
from aidub.providers import invoke_checked
from aidub.util import read_json, write_json
from scripts.provider_cursor_agent import _prompt


class ContextProviderRegressionTests(unittest.TestCase):
    def test_summary_contract_is_explicit_and_retry_surfaces_actual_error(self):
        request = context_request("j", [{"id": 1, "start": 0.0, "end": 1.0, "spanish": "Hola."}], 0, 1, None)
        contract = request["response_contract"]
        summary_rule = contract["fields"]["summary"]
        self.assertEqual(contract["schema"], CONTEXT_SCHEMA)
        self.assertIn("summary", contract["top_level_fields"])
        self.assertIn("1 to 4000 characters inclusive", summary_rule)
        self.assertIn("nonempty", summary_rule)
        self.assertIn(CONTEXT_SCHEMA, request["agent_instructions"])
        self.assertIn("1 to 4000 characters inclusive", request["agent_instructions"])
        self.assertIn("summarize thoughtfully instead of truncating", request["agent_instructions"])

        valid = {"schema": CONTEXT_SCHEMA, "job_id": "j", "translator": {"kind": "command"},
                 "summary": "The speaker greets the audience.", "speaker_register": "Casual", "glossary": [], "style_notes": []}
        seen = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            req_path, response_path = root / "request.json", root / "response.json"
            write_json(req_path, request)

            def provider(spec, request_path, result_path, role):
                current = read_json(request_path)
                seen.append(current)
                result = dict(valid)
                if len(seen) == 1:
                    # Reproduce the observed 4,409-character context summary.
                    result["summary"] = "x" * 4409
                write_json(result_path, result)
                return result

            spec = {"kind": "command", "command": [sys.executable], "max_attempts": 2}
            with patch("aidub.providers.invoke_provider", side_effect=provider):
                accepted = invoke_checked(spec, req_path, response_path, "context")

            self.assertEqual(len(seen), 2)
            error = "summary must be a nonempty string of at most 4000 characters"
            self.assertEqual(seen[1]["validation_feedback"]["errors"], [error])
            self.assertIn("Correct every listed validator error", seen[1]["validation_feedback"]["instruction"])
            self.assertEqual(accepted["summary"], valid["summary"])
            self.assertEqual(validate_context_response(request, accepted), [])
            self.assertEqual(read_json(response_path), valid)

            command_prompt = _prompt("context", seen[1])
            self.assertIn("Correct every actual validator error", command_prompt)
            self.assertIn(error, command_prompt)

    def test_empty_summary_still_fails_validation(self):
        request = context_request("j", [{"id": 1, "start": 0.0, "end": 1.0, "spanish": "Hola."}], 0, 1, None)
        response = {"schema": CONTEXT_SCHEMA, "job_id": "j", "translator": {}, "summary": " ",
                    "speaker_register": "Casual", "glossary": [], "style_notes": []}
        self.assertIn("summary must be a nonempty string of at most 4000 characters",
                      validate_context_response(request, response))


if __name__ == "__main__":
    unittest.main()
