import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from processor.extract import InterpreterError, create_interpreter
from processor.manual import MAX_IMAGES
from processor.openai_provider import MAX_RESPONSE_BYTES, OpenAIInterpreter, _NoRedirect
from processor.schemas import ValidationError, load_json
from scripts.process_post import main, process_manual_post

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/fixtures/data"
STAMP = "2026-10-16T18:30:00+08:00"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=")


def response_for(proposal):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(proposal, ensure_ascii=False)}]}]}


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.manual = load_json(ROOT / "examples/manual-post.json")
        self.proposal = load_json(ROOT / "tests/fixtures/schedule-change.json")["proposal"]
        self.interpreter = Mock()
        self.interpreter.extract.return_value = deepcopy(self.proposal)
        self.schedule = load_json(DATA / "schedule.json")

    def process(self, manual=None, base_dir=None, data_dir=None):
        return process_manual_post(self.manual if manual is None else manual, data_dir or DATA, STAMP,
                                   self.interpreter, base_dir=base_dir or ROOT)

    def test_text_uses_existing_review_merge_and_revision(self):
        before = deepcopy(self.manual)
        result = self.process()
        self.assertEqual(self.manual, before)
        self.assertEqual(result["decision"], "review")
        self.assertEqual(result["posts"][-1]["status"], "pending_review")
        self.assertEqual(result["revisions"][0]["before"]["time"], "20:00")
        self.assertEqual(result["revisions"][0]["after"]["time"], "21:00")
        self.assertEqual(result["revisions"][0]["source_post_id"], self.manual["post"]["post_id"])
        post, schedule = self.interpreter.extract.call_args.args
        self.assertEqual(post["post_text"], self.manual["post_text"])
        self.assertEqual(post["published_at"], self.manual["post"]["published_at"])
        self.assertEqual(post["member"]["id"], "demo-miri")
        self.assertTrue(all(event["member_id"] == "demo-miri" for event in schedule["events"]))
        self.assertEqual(load_json(DATA / "schedule.json"), self.schedule)

    def test_all_six_scenarios_use_replaceable_provider(self):
        for name, decision, count in (("weekly", "review", 2), ("schedule-change", "review", 1),
                                      ("cancellation", "review", 1), ("sudden-stream", "review", 1),
                                      ("irrelevant", "ignored", 0), ("uncertain", "record_only", 0)):
            with self.subTest(name=name):
                self.interpreter.extract.return_value = load_json(ROOT / "tests/fixtures" / f"{name}.json")["proposal"]
                result = self.process()
                self.assertEqual(result["decision"], decision)
                self.assertEqual(len(result["revisions"]), count)
                if not count:
                    self.assertEqual(result["schedule"], self.schedule)

    def test_image_only_resolves_relative_path_and_keeps_binary_out_of_proposal(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "週表.png").write_bytes(PNG)
            self.manual.update(post_text="", images=["週表.png"])
            self.interpreter.extract.return_value = load_json(ROOT / "tests/fixtures/weekly.json")["proposal"]
            result = self.process(base_dir=base)
        images = self.interpreter.extract.call_args.args[0]["images"]
        self.assertEqual(base64.b64decode(images[0].split(",", 1)[1]), PNG)
        self.assertTrue(images[0].startswith("data:image/png;base64,"))
        serialized = json.dumps(result)
        self.assertNotIn("base64", serialized)
        self.assertNotIn(str(base), serialized)
        self.assertEqual(len(result["revisions"]), 2)

    def test_https_images_from_metadata_and_manual_list_are_deduplicated_and_preserved(self):
        url = "https://example.com/weekly.png"
        self.manual["post"]["media"] = [{"type": "image", "url": url}]
        self.manual["images"] = [url, "https://example.com/second.png"]
        result = self.process()
        self.assertEqual(self.interpreter.extract.call_args.args[0]["images"], [url, self.manual["images"][1]])
        self.assertEqual(len(result["posts"][-1]["media"]), 2)
        self.assertEqual(len(self.manual["post"]["media"]), 1)

    def test_invalid_input_stops_before_provider(self):
        invalids = [None, [], {}, {**self.manual, "extra": True}, {**self.manual, "post_text": 3},
                    {**self.manual, "images": "weekly.png"}, {**self.manual, "images": [None]},
                    {**self.manual, "images": [""]}, {**self.manual, "post_text": " "}]
        for value in invalids:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                process_manual_post(value, DATA, STAMP, self.interpreter, base_dir=ROOT)
        self.interpreter.extract.assert_not_called()

    def test_invalid_metadata_and_duplicate_post_stop_before_provider(self):
        invalids = [{"member_id": "missing"}, {"published_at": "2026-10-16"}, {"source": "other"},
                    {"source_url": "javascript:bad"}, {"post_id": "demo-weekly-001"}, {"extra": True}]
        for changes in invalids:
            value = deepcopy(self.manual)
            value["post"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.process(value)
        self.interpreter.extract.assert_not_called()

    def test_disabled_member_stops_before_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ("members", "schedule", "posts", "revisions"):
                value = load_json(DATA / f"{name}.json")
                if name == "members":
                    value[0]["enabled"] = False
                (directory / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValidationError):
                self.process(data_dir=directory)
        self.interpreter.extract.assert_not_called()

    def test_bad_image_inputs_stop_before_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "fake.png").write_bytes(b"not an image")
            (base / "empty.png").write_bytes(b"")
            for images, error in ((["missing.png"], OSError), (["fake.png"], ValidationError),
                                  (["empty.png"], ValidationError), (["http://example.com/a.png"], ValidationError),
                                  (["https://user:password@example.com/a.png"], ValidationError),
                                  ([f"https://example.com/{index}.png" for index in range(MAX_IMAGES + 1)], ValidationError)):
                self.manual["images"] = images
                with self.subTest(images=images), self.assertRaises(error):
                    self.process(base_dir=base)
        self.interpreter.extract.assert_not_called()

    def test_local_image_size_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "a.png").write_bytes(PNG)
            (base / "b.png").write_bytes(PNG)
            self.manual["images"] = ["a.png"]
            with patch("processor.manual.MAX_IMAGE_BYTES", len(PNG) - 1), self.assertRaises(ValidationError):
                self.process(base_dir=base)
            self.manual["images"] = ["a.png", "b.png"]
            with patch("processor.manual.MAX_TOTAL_IMAGE_BYTES", len(PNG)), self.assertRaises(ValidationError):
                self.process(base_dir=base)
        self.interpreter.extract.assert_not_called()

    def test_provider_output_is_validated_even_for_custom_provider(self):
        for proposal in ({}, {**self.proposal, "confidence": 1.1}, {**self.proposal, "extra": True}):
            self.interpreter.extract.return_value = proposal
            with self.subTest(proposal=proposal), self.assertRaises(ValidationError):
                self.process()

    def test_cross_member_changes_are_rejected(self):
        self.proposal["changes"][0]["match"]["member_id"] = "demo-snow"
        self.interpreter.extract.return_value = self.proposal
        with self.assertRaises(ValidationError):
            self.process()
        self.assertEqual(load_json(DATA / "schedule.json"), self.schedule)

    def test_custom_provider_cannot_mutate_merge_context(self):
        def extract(post, schedule):
            post["member"]["id"] = "altered"
            schedule["events"].clear()
            return self.proposal
        self.interpreter.extract.side_effect = extract
        self.assertEqual(self.process()["revisions"][0]["before"]["time"], "20:00")

    def test_cli_writes_review_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "post.json"
            source.write_text(json.dumps(self.manual), encoding="utf-8")
            output = directory / "proposal.json"
            stdout = io.StringIO()
            with patch("scripts.process_post.create_interpreter", return_value=self.interpreter), redirect_stdout(stdout):
                code = main(["--manual", str(source), "--data-dir", str(DATA), "--output", str(output), "--model", "test-model"])
            self.assertEqual(code, 0)
            self.assertEqual(load_json(output)["decision"], "review")
            log = json.loads(stdout.getvalue())
            self.assertEqual(log["result"], "review")
            self.assertNotIn(self.manual["post_text"], stdout.getvalue())

    def test_cli_failures_preserve_previous_proposal_and_production_data(self):
        before = {path: path.read_bytes() for path in (ROOT / "data").glob("*.json")}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "post.json"
            source.write_text(json.dumps(self.manual), encoding="utf-8")
            output = directory / "proposal.json"
            for failure in (InterpreterError("AI API 逾時"), ValidationError("Schema invalid")):
                output.write_bytes(b"previous proposal")
                self.interpreter.extract.side_effect = failure
                stderr = io.StringIO()
                with patch("scripts.process_post.create_interpreter", return_value=self.interpreter), redirect_stderr(stderr):
                    self.assertEqual(main(["--manual", str(source), "--data-dir", str(DATA), "--output", str(output)]), 1)
                self.assertEqual(output.read_bytes(), b"previous proposal")
                self.assertEqual(json.loads(stderr.getvalue())["result"], "failed")
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_cli_image_flows_through_real_provider_to_review_bundle(self):
        proposal = load_json(ROOT / "tests/fixtures/weekly.json")["proposal"]
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response_for(proposal)).encode()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "weekly.png").write_bytes(PNG)
            self.manual.update(post_text="", images=["weekly.png"])
            source = directory / "post.json"
            source.write_text(json.dumps(self.manual), encoding="utf-8")
            output = directory / "proposal.json"
            with patch("processor.openai_provider.build_opener", return_value=opener), redirect_stdout(io.StringIO()), patch.dict(
                "os.environ", {"OPENAI_API_KEY": "test-only-key", "OPENAI_MODEL": "configured-model"}, clear=True
            ):
                self.assertEqual(main(["--manual", str(source), "--data-dir", str(DATA), "--output", str(output)]), 0)
            result = load_json(output)
        self.assertEqual(result["decision"], "review")
        self.assertEqual(len(result["revisions"]), 2)
        content = json.loads(opener.open.call_args.args[0].data)["input"][0]["content"]
        self.assertEqual(base64.b64decode(content[1]["image_url"].split(",", 1)[1]), PNG)
        self.assertEqual(opener.open.call_count, 1)

    def test_cli_rejects_production_or_input_overwrite_and_conflicting_modes(self):
        for arguments in (["--manual", str(ROOT / "examples/manual-post.json"), "--output", str(ROOT / "data/proposal.json")],
                          ["--manual", str(ROOT / "examples/manual-post.json"), "--output", str(ROOT / "examples/manual-post.json")],
                          [str(ROOT / "tests/fixtures/weekly.json"), "--manual", str(ROOT / "examples/manual-post.json")], []):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(arguments)
            self.assertEqual(error.exception.code, 2)

    def test_factory_loads_custom_provider_without_openai_credentials(self):
        factory = Mock(return_value=self.interpreter)
        with patch("processor.extract.import_module", return_value=SimpleNamespace(create=factory)), patch.dict("os.environ", {}, clear=True):
            self.assertIs(create_interpreter("custom_provider:create", model="custom-model", timeout=12), self.interpreter)
        factory.assert_called_once_with(model="custom-model", timeout=12)

    def test_factory_rejects_missing_custom_provider(self):
        with self.assertRaises(InterpreterError):
            create_interpreter("invalid-provider")


class OpenAIProviderTests(unittest.TestCase):
    def setUp(self):
        self.proposal = load_json(ROOT / "tests/fixtures/schedule-change.json")["proposal"]
        self.post = {"member": load_json(DATA / "members.json")[0], "post_text": "今天改九點",
                     "published_at": "2026-10-15T17:30:00Z", "images": []}
        self.schedule = load_json(DATA / "schedule.json")
        self.provider = OpenAIInterpreter(model="configured-model", api_key="test-only-key", timeout=12)
        self.opener = MagicMock()
        self.response = self.opener.open.return_value.__enter__.return_value
        self.response.read.return_value = json.dumps(response_for(self.proposal)).encode()
        self.patch = patch("processor.openai_provider.build_opener", return_value=self.opener)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_request_uses_text_images_schema_and_publication_date(self):
        self.post["images"] = ["data:image/png;base64,example", "https://example.com/weekly.png"]
        self.assertEqual(self.provider.extract(self.post, self.schedule), self.proposal)
        request = self.opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-key")
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 12)
        self.assertEqual(payload["model"], "configured-model")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["text"]["format"]["type"], "json_object")
        self.assertIn("JSON Schema", payload["instructions"])
        content = payload["input"][0]["content"]
        context = json.loads(content[0]["text"])
        self.assertEqual(context["taipei_published_date"], "2026-10-16")
        self.assertEqual(context["current_schedule"], self.schedule)
        self.assertEqual(content[1]["image_url"], self.post["images"][0])
        self.assertEqual(content[2]["type"], "input_image")
        self.assertNotIn("test-only-key", request.data.decode())

    def test_each_spec_response_validates_and_extracts(self):
        for name in ("weekly", "schedule-change", "cancellation", "sudden-stream", "irrelevant", "uncertain"):
            proposal = load_json(ROOT / "tests/fixtures" / f"{name}.json")["proposal"]
            self.response.read.return_value = json.dumps(response_for(proposal)).encode()
            with self.subTest(name=name):
                self.assertEqual(self.provider.extract(self.post, self.schedule), proposal)

    def test_classify_returns_classification_without_merge_changes(self):
        self.assertEqual(self.provider.classify(self.post), {key: self.proposal[key] for key in ("classification", "confidence", "reason")})

    def test_network_errors_do_not_expose_response_body_or_credentials(self):
        failures = (TimeoutError("test-only-key"), URLError("test-only-key"),
                    HTTPError("https://api.openai.com", 429, "test-only-key", {}, io.BytesIO(b"test-only-key")),
                    HTTPError("https://api.openai.com", 401, "test-only-key", {}, io.BytesIO(b"test-only-key")))
        for failure in failures:
            self.opener.open.side_effect = failure
            with self.subTest(failure=type(failure)), self.assertRaises(InterpreterError) as error:
                self.provider.extract(self.post, self.schedule)
            self.assertNotIn("test-only-key", str(error.exception))

    def test_incomplete_refused_missing_and_invalid_responses_are_rejected(self):
        invalids = [[], {"status": "incomplete", "output": []}, {"status": "failed"},
                    {"status": "completed", "output": []}, {"status": "completed", "output": None},
                    {"status": "completed", "output": [{"type": "message", "content": [None]}]},
                    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
                    response_for({}), response_for({**self.proposal, "confidence": True})]
        for envelope in invalids:
            self.response.read.return_value = json.dumps(envelope).encode()
            with self.subTest(envelope=envelope), self.assertRaises(InterpreterError):
                self.provider.extract(self.post, self.schedule)
        for body in (b"not json", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1)):
            self.response.read.return_value = body
            with self.subTest(length=len(body)), self.assertRaises(InterpreterError):
                self.provider.extract(self.post, self.schedule)

    def test_markdown_and_non_finite_ai_json_are_rejected(self):
        for text in ("```json\n{}\n```", json.dumps(self.proposal).replace("0.97", "NaN")):
            envelope = response_for(self.proposal)
            envelope["output"][0]["content"][0]["text"] = text
            self.response.read.return_value = json.dumps(envelope).encode()
            with self.subTest(text=text), self.assertRaises(InterpreterError):
                self.provider.extract(self.post, self.schedule)

    def test_configuration_is_required_without_hardcoded_model(self):
        for changes in ({"model": None}, {"api_key": ""}, {"timeout": 0}, {"timeout": float("nan")}):
            arguments = {"model": "configured-model", "api_key": "test-only-key", "timeout": 60, **changes}
            with self.subTest(changes=changes), self.assertRaises(InterpreterError):
                OpenAIInterpreter(**arguments)
        with patch.dict("os.environ", {"OPENAI_MODEL": "env-model", "OPENAI_API_KEY": "test-only-key"}, clear=True):
            self.assertEqual(create_interpreter().model, "env-model")
            self.assertEqual(create_interpreter(model="explicit-model").model, "explicit-model")

    def test_redirects_are_not_followed_with_authorization(self):
        opener = build_opener(_NoRedirect())
        request = Request("https://api.openai.com/v1/responses", headers={"Authorization": "Bearer test-only-key"})
        with patch.object(opener, "open") as redirected_request, self.assertRaises(HTTPError) as error:
            opener.error("http", request, io.BytesIO(), 302, "Found", {"location": "https://elsewhere.example"})
        redirected_request.assert_not_called()
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
