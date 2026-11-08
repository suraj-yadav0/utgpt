"""
Unit tests for backend/backend.py.

Scope (per PR diff): these tests only cover code paths that were added or
changed in this PR:

  - ensure_llama_cli()              -> multi-URL fallback + OR-based binary
                                        verification (was AND-based, single
                                        tag/URL before)
  - download_llama_cli_in_background() -> OR-based binary verification
  - get_release_notes()             -> new function
  - initialize()                    -> now also returns "version" and
                                        "releaseNotes"

No third-party test dependencies are used (stdlib `unittest` +
`unittest.mock` only) since the repository has no existing test tooling
installed.
"""

import json
import os
import sys
import tempfile
import shutil
import io
import threading
import unittest
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import backend  # noqa: E402


class FakeHTTPResponse:
    """Minimal stand-in for the context-manager object returned by
    urllib.request.urlopen()/backend._urlopen()."""

    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class LlamaCliGlobalsResetMixin:
    """Saves and restores the module-level LLAMA_CLI_* globals so tests
    that call download_llama_cli_in_background()/initialize() don't leak
    state into other tests."""

    def setUp(self):
        super().setUp()
        self._saved_ready = backend.LLAMA_CLI_READY
        self._saved_error = backend.LLAMA_CLI_ERROR
        self._saved_downloading = backend.LLAMA_CLI_DOWNLOADING
        backend.LLAMA_CLI_READY = False
        backend.LLAMA_CLI_ERROR = None
        backend.LLAMA_CLI_DOWNLOADING = False

    def tearDown(self):
        backend.LLAMA_CLI_READY = self._saved_ready
        backend.LLAMA_CLI_ERROR = self._saved_error
        backend.LLAMA_CLI_DOWNLOADING = self._saved_downloading
        super().tearDown()


class TestEnsureLlamaCliAlreadyWorking(unittest.TestCase):
    """ensure_llama_cli() should short-circuit (no network/download calls)
    as soon as *either* binary already works (OR, not AND)."""

    @patch.object(backend, "_download_and_extract_tar")
    @patch.object(backend, "is_binary_working")
    @patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion")
    @patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli")
    def test_returns_true_when_only_cli_binary_works(
        self, mock_cli_path, mock_completion_path, mock_is_working, mock_download
    ):
        mock_is_working.side_effect = lambda path: path == "/fake/llama-cli"

        self.assertTrue(backend.ensure_llama_cli())
        mock_download.assert_not_called()

    @patch.object(backend, "_download_and_extract_tar")
    @patch.object(backend, "is_binary_working")
    @patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion")
    @patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli")
    def test_returns_true_when_only_completion_binary_works(
        self, mock_cli_path, mock_completion_path, mock_is_working, mock_download
    ):
        mock_is_working.side_effect = lambda path: path == "/fake/llama-completion"

        self.assertTrue(backend.ensure_llama_cli())
        mock_download.assert_not_called()

    @patch.object(backend, "_download_and_extract_tar")
    @patch.object(backend, "is_binary_working", return_value=False)
    @patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion")
    @patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli")
    def test_attempts_download_when_neither_binary_works(
        self, mock_cli_path, mock_completion_path, mock_is_working, mock_download
    ):
        mock_download.return_value = False
        with patch.object(backend, "_urlopen", side_effect=Exception("no network")):
            backend.ensure_llama_cli()
        mock_download.assert_called()


class TestEnsureLlamaCliDownloadFlow(unittest.TestCase):
    """Covers the new multi-URL fallback chain and per-URL OR verification
    added to ensure_llama_cli()."""

    def _run(self, machine, github_releases=None, github_raises=False,
              download_results=None, working_after_download=False):
        """Helper that drives ensure_llama_cli() with controlled mocks and
        returns (result, urls_attempted)."""
        urls_attempted = []
        download_results = list(download_results or [])

        state = {"downloaded": False}

        def fake_download(url):
            urls_attempted.append(url)
            result = download_results.pop(0) if download_results else False
            if result and working_after_download:
                state["downloaded"] = True
            return result

        def fake_is_binary_working(path):
            return state["downloaded"]

        patches = [
            patch.object(backend.platform, "machine", return_value=machine),
            patch.object(backend.platform, "system", return_value="linux"),
            patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli"),
            patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion"),
            patch.object(backend, "is_binary_working", side_effect=fake_is_binary_working),
            patch.object(backend, "_download_and_extract_tar", side_effect=fake_download),
        ]

        if github_raises:
            patches.append(patch.object(backend, "_urlopen", side_effect=Exception("network down")))
        else:
            payload = json.dumps(github_releases or []).encode("utf-8")
            patches.append(patch.object(backend, "_urlopen", return_value=FakeHTTPResponse(payload)))

        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.ensure_llama_cli()
        return result, urls_attempted

    def test_x64_uses_fallback_url_when_github_api_unreachable(self):
        result, urls = self._run(
            machine="x86_64",
            github_raises=True,
            download_results=[True],
            working_after_download=True,
        )
        self.assertTrue(result)
        self.assertEqual(
            urls,
            ["https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"],
        )

    def test_x64_uses_fallback_url_when_no_matching_release_asset(self):
        # GitHub API responds successfully, but no release exposes the
        # expected "-bin-ubuntu-x64.tar.gz" asset -> urls_to_try stays empty
        # and the suraj-yadav0 fallback is used.
        releases = [
            {"tag_name": "b9999", "assets": [{"name": "llama-b9999-bin-ubuntu-arm64.tar.gz"}]}
        ]
        result, urls = self._run(
            machine="x86_64",
            github_releases=releases,
            download_results=[True],
            working_after_download=True,
        )
        self.assertTrue(result)
        self.assertEqual(
            urls,
            ["https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"],
        )

    def test_x64_never_tries_arm64_compat_url_first(self):
        releases = [
            {"tag_name": "b1234", "assets": [{"name": "llama-b1234-bin-ubuntu-x64.tar.gz"}]}
        ]
        result, urls = self._run(
            machine="x86_64",
            github_releases=releases,
            download_results=[True],
            working_after_download=True,
        )
        self.assertTrue(result)
        self.assertEqual(len(urls), 1)
        self.assertNotIn("arm64", urls[0])
        self.assertIn(
            "https://github.com/ggml-org/llama.cpp/releases/download/b1234/llama-b1234-bin-ubuntu-x64.tar.gz",
            urls,
        )

    def test_arm64_prioritizes_verified_compat_build_before_github_release(self):
        releases = [
            {"tag_name": "b5555", "assets": [{"name": "llama-b5555-bin-ubuntu-arm64.tar.gz"}]}
        ]
        # First (compat) URL download fails, second (GitHub-resolved) URL
        # succeeds -> proves both the priority ordering and the fallback
        # chain work together.
        result, urls = self._run(
            machine="aarch64",
            github_releases=releases,
            download_results=[False, True],
            working_after_download=True,
        )
        self.assertTrue(result)
        self.assertEqual(
            urls[0],
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz",
        )
        self.assertEqual(
            urls[1],
            "https://github.com/ggml-org/llama.cpp/releases/download/b5555/llama-b5555-bin-ubuntu-arm64.tar.gz",
        )

    def test_arm64_stops_after_first_successful_verified_download(self):
        releases = [
            {"tag_name": "b5555", "assets": [{"name": "llama-b5555-bin-ubuntu-arm64.tar.gz"}]}
        ]
        result, urls = self._run(
            machine="aarch64",
            github_releases=releases,
            download_results=[True],
            working_after_download=True,
        )
        self.assertTrue(result)
        # Only the (successful) compat URL should have been attempted.
        self.assertEqual(len(urls), 1)

    def test_returns_false_when_all_downloads_fail_verification(self):
        releases = [
            {"tag_name": "b5555", "assets": [{"name": "llama-b5555-bin-ubuntu-arm64.tar.gz"}]}
        ]
        # Downloads "succeed" (extraction returns True) but the extracted
        # binaries never pass is_binary_working() -> overall failure.
        result, urls = self._run(
            machine="aarch64",
            github_releases=releases,
            download_results=[True, True],
            working_after_download=False,
        )
        self.assertFalse(result)
        self.assertEqual(len(urls), 2)

    def test_returns_false_when_extraction_fails_for_every_url(self):
        result, urls = self._run(
            machine="x86_64",
            github_raises=True,
            download_results=[False],
            working_after_download=True,
        )
        self.assertFalse(result)
        self.assertEqual(len(urls), 1)

    def test_unknown_machine_string_falls_back_to_x64(self):
        result, urls = self._run(
            machine="riscv64",
            github_raises=True,
            download_results=[True],
            working_after_download=True,
        )
        self.assertTrue(result)
        self.assertIn("x64", urls[0])


class TestDownloadLlamaCliInBackground(LlamaCliGlobalsResetMixin, unittest.TestCase):
    @patch.object(backend, "is_binary_working")
    @patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion")
    @patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli")
    @patch.object(backend, "ensure_llama_cli", return_value=True)
    def test_ready_true_when_only_completion_binary_verifies(
        self, mock_ensure, mock_cli_path, mock_completion_path, mock_is_working
    ):
        mock_is_working.side_effect = lambda path: path == "/fake/llama-completion"

        backend.download_llama_cli_in_background()

        self.assertTrue(backend.LLAMA_CLI_READY)
        self.assertIsNone(backend.LLAMA_CLI_ERROR)
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @patch.object(backend, "is_binary_working", return_value=False)
    @patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion")
    @patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli")
    @patch.object(backend, "ensure_llama_cli", return_value=True)
    def test_error_set_when_binaries_fail_verification_after_successful_ensure(
        self, mock_ensure, mock_cli_path, mock_completion_path, mock_is_working
    ):
        backend.download_llama_cli_in_background()

        self.assertFalse(backend.LLAMA_CLI_READY)
        self.assertEqual(
            backend.LLAMA_CLI_ERROR,
            "Downloaded binary is incompatible with this device (Illegal instruction / crash).",
        )
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @patch.object(backend, "ensure_llama_cli", return_value=False)
    def test_default_error_set_when_ensure_llama_cli_fails(self, mock_ensure):
        backend.download_llama_cli_in_background()

        self.assertFalse(backend.LLAMA_CLI_READY)
        self.assertEqual(backend.LLAMA_CLI_ERROR, "Failed to download llama-cli from GitHub")
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @patch.object(backend, "ensure_llama_cli", side_effect=RuntimeError("boom"))
    def test_downloading_flag_cleared_even_if_ensure_llama_cli_raises(self, mock_ensure):
        backend.download_llama_cli_in_background()

        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)
        self.assertEqual(backend.LLAMA_CLI_ERROR, "boom")
        self.assertFalse(backend.LLAMA_CLI_READY)


class TestGetReleaseNotes(unittest.TestCase):
    DEFAULT_FALLBACK = {
        "version": "0.1.0",
        "date": "2026-07-26",
        "title": "What's New in UTGPT",
        "subtitle": "Version 0.1.0 Release Notes",
        "features": [],
    }

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def _patch_app_dir(self):
        return patch.object(backend, "APP_DIR", self.tmp_dir)

    def test_loads_real_bundled_asset_file(self):
        asset_path = os.path.join(ROOT_DIR, "assets", "release_notes.json")
        with open(asset_path, "r", encoding="utf-8") as f:
            expected = json.load(f)

        self.assertEqual(backend.get_release_notes(), expected)

    def test_returns_default_when_assets_directory_missing(self):
        with self._patch_app_dir():
            self.assertEqual(backend.get_release_notes(), self.DEFAULT_FALLBACK)

    def test_returns_default_when_file_missing_but_assets_dir_exists(self):
        os.makedirs(os.path.join(self.tmp_dir, "assets"))
        with self._patch_app_dir():
            self.assertEqual(backend.get_release_notes(), self.DEFAULT_FALLBACK)

    def test_returns_default_on_malformed_json(self):
        assets_dir = os.path.join(self.tmp_dir, "assets")
        os.makedirs(assets_dir)
        with open(os.path.join(assets_dir, "release_notes.json"), "w", encoding="utf-8") as f:
            f.write("{not valid json,,,")

        with self._patch_app_dir():
            self.assertEqual(backend.get_release_notes(), self.DEFAULT_FALLBACK)

    def test_loads_custom_valid_json_verbatim(self):
        custom = {
            "version": "9.9.9",
            "date": "2030-01-01",
            "title": "Custom Title",
            "subtitle": "Custom Subtitle",
            "features": [{"title": "T", "icon": "i", "description": "d"}],
        }
        assets_dir = os.path.join(self.tmp_dir, "assets")
        os.makedirs(assets_dir)
        with open(os.path.join(assets_dir, "release_notes.json"), "w", encoding="utf-8") as f:
            json.dump(custom, f)

        with self._patch_app_dir():
            self.assertEqual(backend.get_release_notes(), custom)


class TestInitialize(LlamaCliGlobalsResetMixin, unittest.TestCase):
    def _base_patches(self, is_binary_working_result, release_notes):
        return [
            patch.object(backend, "_ensure_models_dir", return_value="/fake/models"),
            patch.object(backend, "init_db"),
            patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli"),
            patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion"),
            patch.object(backend, "is_binary_working", return_value=is_binary_working_result),
            patch.object(backend, "get_release_notes", return_value=release_notes),
        ]

    def test_result_contains_version_and_release_notes_from_helper(self):
        release_notes = {
            "version": "1.2.3",
            "date": "2027-01-01",
            "title": "T",
            "subtitle": "S",
            "features": [],
        }
        patches = self._base_patches(True, release_notes)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.initialize()

        self.assertEqual(result["version"], "1.2.3")
        self.assertEqual(result["releaseNotes"], release_notes)
        self.assertTrue(result["llamaCliReady"])
        self.assertTrue(backend.LLAMA_CLI_READY)

    def test_version_defaults_to_0_1_0_when_release_notes_missing_version_key(self):
        release_notes = {"date": "2027-01-01", "title": "T", "subtitle": "S", "features": []}
        patches = self._base_patches(True, release_notes)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.initialize()

        self.assertEqual(result["version"], "0.1.0")

    def test_llama_cli_ready_false_when_binaries_not_working(self):
        release_notes = {"version": "0.1.0", "features": []}
        patches = self._base_patches(False, release_notes)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.initialize()

        self.assertFalse(result["llamaCliReady"])
        self.assertFalse(backend.LLAMA_CLI_READY)

    def test_result_shape_contains_all_expected_keys(self):
        release_notes = {"version": "0.1.0", "features": []}
        patches = self._base_patches(True, release_notes)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.initialize()

        expected_keys = {
            "ready", "modelsDir", "llamaCliPath", "llamaCliReady",
            "debug", "isDesktop", "version", "releaseNotes",
        }
        self.assertEqual(expected_keys, set(result.keys()))


class TestWebSearch(unittest.TestCase):
    def setUp(self):
        backend.WEB_SEARCH_CACHE.clear()

    def tearDown(self):
        backend.WEB_SEARCH_CACHE.clear()

    def test_search_web_parses_ddg_lite_html(self):
        sample_html = (
            '<html><body>'
            '<table>'
            '<tr><td><a class="result-link" href="https://ubports.com">UBports Foundation</a></td></tr>'
            '<tr><td class="result-snippet">Sample snippet for Ubuntu Touch</td></tr>'
            '</table>'
            '</body></html>'
        ).encode("utf-8")

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = sample_html
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch.object(backend, "_urlopen", return_value=mock_resp):
            results = backend.search_web("ubuntu touch", num_results=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "UBports Foundation")
        self.assertEqual(results[0]["url"], "https://ubports.com")
        self.assertIn("Ubuntu Touch", results[0]["snippet"])

    def test_search_web_uses_cached_results(self):
        sample_html = (
            '<html><body>'
            '<a class="result-link" href="https://example.com">Example</a>'
            '<td class="result-snippet">Test snippet</td>'
            '</body></html>'
        ).encode("utf-8")

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = sample_html
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch.object(backend, "_urlopen", return_value=mock_resp) as mock_url:
            first = backend.search_web("cache test", num_results=1)
            second = backend.search_web("cache test", num_results=1)

        self.assertEqual(first, second)
        self.assertEqual(mock_url.call_count, 1)

    def test_search_web_handles_network_failure(self):
        with patch.object(backend, "_urlopen", side_effect=Exception("network down")):
            results = backend.search_web("fail query")

        self.assertEqual(results, [])

    def test_emit_search_status_sends_transient_event(self):
        with patch.object(backend, "_send_event") as mock_send:
            backend._emit_search_status("req-123", "started")
            mock_send.assert_called_once_with("web_search_status", {
                "requestId": "req-123",
                "phase": "started"
            })

    def test_search_web_unquotes_ddg_redirect_url(self):
        sample_html = (
            '<html><body>'
            '<table>'
            '<tr><td><a class="result-link" href="/l/?kh=-1&uddg=https%3A%2F%2Fubports.com%2Fblog">UBports</a></td></tr>'
            '<tr><td class="result-snippet">Test blog</td></tr>'
            '</table>'
            '</body></html>'
        ).encode("utf-8")

        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = sample_html
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch.object(backend, "_urlopen", return_value=mock_resp):
            results = backend.search_web("ubports redirect", num_results=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://ubports.com/blog")


class TestSecurityAndStorageGuards(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.models_dir = os.path.join(self.tmp_dir, "models")
        os.makedirs(self.models_dir, exist_ok=True)
        self.patch_models = patch.object(backend, "MODELS_DIR", self.models_dir)
        self.patch_models.start()

    def tearDown(self):
        self.patch_models.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_delete_model_blocks_path_traversal(self):
        outside_file = os.path.join(self.tmp_dir, "outside.txt")
        with open(outside_file, "w") as f:
            f.write("secret")

        result = backend.delete_model("../outside.txt")
        self.assertFalse(result)
        self.assertTrue(os.path.exists(outside_file))

    def test_clear_partial_download_blocks_path_traversal(self):
        outside_file = os.path.join(self.tmp_dir, "outside.txt.part")
        with open(outside_file, "w") as f:
            f.write("partial")

        result = backend.clear_partial_download("../outside.txt")
        self.assertFalse(result)
        self.assertTrue(os.path.exists(outside_file))

    def test_truncate_session_messages_subquery(self):
        db_file = os.path.join(self.tmp_dir, "chat.db")
        with patch.object(backend, "DB_PATH", db_file):
            backend.DB_INITIALIZED = False
            backend.init_db()
            session_id = backend.add_chat_message("user", "msg 1", "test-session")
            backend.add_chat_message("assistant", "msg 2", session_id)
            backend.add_chat_message("user", "msg 3", session_id)
            backend.add_chat_message("assistant", "msg 4", session_id)

            success = backend.truncate_session_messages(session_id, 2)
            self.assertTrue(success)

            history = backend.load_chat_history(session_id)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["text"], "msg 1")
            self.assertEqual(history[1]["text"], "msg 2")


class TestPonytailBackendSimplifications(unittest.TestCase):
    def test_default_catalog_loaded_from_models_json(self):
        self.assertIsInstance(backend.DEFAULT_CATALOG, list)
        self.assertGreater(len(backend.DEFAULT_CATALOG), 0)
        first_model = backend.DEFAULT_CATALOG[0]
        self.assertIn("name", first_model)
        self.assertIn("filename", first_model)

    def test_import_local_model_thread_copies_file_and_emits_events(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_file = os.path.join(tmp_dir, "custom.gguf")
            with open(source_file, "wb") as f:
                f.write(b"model data content")

            models_dir = os.path.join(tmp_dir, "models")
            os.makedirs(models_dir, exist_ok=True)

            events = []
            def capture_event(name, payload):
                events.append((name, payload))

            with patch.object(backend, "MODELS_DIR", models_dir), \
                 patch.object(backend, "_send_event", side_effect=capture_event):
                backend.import_local_model_thread("file://" + source_file, "req-test-1")

            dest_file = os.path.join(models_dir, "custom.gguf")
            self.assertTrue(os.path.isfile(dest_file))
            with open(dest_file, "rb") as f:
                self.assertEqual(f.read(), b"model data content")

            event_names = [ev[0] for ev in events]
            self.assertIn("import_start", event_names)
            self.assertIn("import_complete", event_names)

    def test_system_metrics(self):
        ram = backend.get_total_ram_gb()
        self.assertIsInstance(ram, float)
        self.assertGreater(ram, 0.0)

        storage = backend.get_free_storage()
        self.assertIsInstance(storage, str)
        self.assertTrue(storage.endswith("GB free"))

    def test_run_inference_clean_arg_parsing(self):
        with patch.object(backend, "log_info") as mock_log, \
             patch.object(backend, "_ensure_models_dir", return_value="/nonexistent"):
            backend.run_inference("m.gguf", "hi", 0.7, 256, 8, 4096, "off", "q4_0", True, "tok_cb", "done_cb")
            matching = [call[0][0] for call in mock_log.call_args_list if "Entering run_inference" in call[0][0]]
            self.assertEqual(len(matching), 1)
            self.assertIn("threads=8", matching[0])
            self.assertIn("ctx_size=4096", matching[0])
            self.assertIn("flash_attn=off", matching[0])
            self.assertIn("web_search=True", matching[0])

    def test_db_auto_initializes_in_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = os.path.join(tmp_dir, "test_chat.db")
            with patch.object(backend, "DB_PATH", db_file):
                backend.DB_INITIALIZED = False
                self.assertFalse(backend.DB_INITIALIZED)
                with backend._get_db_context() as conn:
                    self.assertTrue(backend.DB_INITIALIZED)
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = {r[0] for r in cursor.fetchall()}
                    self.assertIn("sessions", tables)
                    self.assertIn("messages", tables)

    def test_inference_engine_status_event_emitted_on_completion(self):
        events = []
        with patch.object(backend, "ensure_llama_cli", return_value=True), \
             patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli"), \
             patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion"), \
             patch.object(backend, "is_binary_working", return_value=True), \
             patch.object(backend, "_send_event", side_effect=lambda ev, payload: events.append((ev, payload))):
            backend.download_llama_cli_in_background()

        status_events = [payload for ev, payload in events if ev == "inference_engine_status"]
        self.assertGreaterEqual(len(status_events), 1)
        final_event = status_events[-1]
        self.assertEqual(final_event["status"], "ready")
        self.assertEqual(final_event["error"], "")

    def test_prompt_formatting_clean_context(self):
        context_msgs = [
            {"role": "system", "text": "Web Search Results:\n1. Latest news"}
        ]
        prompt, boundary = backend.get_prompt_and_boundary(
            "qwen-2.5-3b.gguf",
            "What is today's headline?",
            [],
            context_msgs
        )
        self.assertIn("Web Search Results:\n1. Latest news", prompt)
        self.assertNotIn("Relevant facts and details from previous conversations", prompt)

    def test_stdout_streaming_batches_and_strips_markers(self):
        import io
        import threading
        tokens = []
        done_called = threading.Event()

        fake_stdout = io.StringIO("Hello world from UTGPT! [end of text]")
        mock_proc = MagicMock()
        mock_proc.stdout = fake_stdout
        mock_proc.stderr = io.StringIO("")
        mock_proc.wait.return_value = 0

        with tempfile.TemporaryDirectory() as tmp_dir:
            model_file = os.path.join(tmp_dir, "model.gguf")
            with open(model_file, "w") as f:
                f.write("fake model")
            cli_bin = os.path.join(tmp_dir, "llama-completion")
            with open(cli_bin, "w") as f:
                f.write("fake bin")

            with patch.object(backend, "get_llama_completion_path", return_value=cli_bin), \
                 patch.object(backend, "get_llama_cli_path", return_value=cli_bin), \
                 patch.object(backend, "is_binary_working", return_value=True), \
                 patch.object(backend, "_ensure_models_dir", return_value=tmp_dir), \
                 patch.object(backend.subprocess, "Popen", return_value=mock_proc):

                backend.run_inference(
                    "model.gguf",
                    "Hi",
                    0.7,
                    100,
                    4,
                    2048,
                    "off",
                    "f16",
                    False,
                    lambda t: tokens.append(t),
                    lambda ok, err: done_called.set()
                )
                self.assertTrue(done_called.wait(timeout=3.0))

        combined = "".join(tokens)
        self.assertIn("Hello world from UTGPT!", combined)
        self.assertNotIn("[end of text]", combined)

    def test_clean_search_query(self):
        self.assertEqual(backend.clean_search_query("Can you please search for Ubuntu Touch 24.04?"), "Ubuntu Touch 24.04")
        self.assertEqual(backend.clean_search_query("Hey what is the price of Bitcoin today?"), "the price of Bitcoin today")
        self.assertEqual(backend.clean_search_query("Tell me about quantum computing..."), "quantum computing")
        self.assertEqual(backend.clean_search_query("AI"), "AI")
        self.assertEqual(backend.clean_search_query(""), "")

    def test_emit_search_status_rich_payload(self):
        with patch.object(backend, "_send_event") as mock_send:
            sources = [{"title": "UBports", "url": "https://ubports.com"}]
            backend._emit_search_status("req-456", "found", query="ubuntu touch", count=1, sources=sources)
            mock_send.assert_called_once_with("web_search_status", {
                "requestId": "req-456",
                "phase": "found",
                "query": "ubuntu touch",
                "count": 1,
                "sources": sources
            })

    def test_add_and_load_chat_message_with_sources(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = os.path.join(tmp_dir, "test_sources.db")
            with patch.object(backend, "DB_PATH", db_file):
                backend.DB_INITIALIZED = False
                sources_json = '[{"title": "Doc", "url": "https://example.com"}]'
                sess_id = backend.add_chat_message("user", "Hello", "session-1")
                backend.add_chat_message("assistant", "Found answer", sess_id, sources=sources_json)

                history = backend.load_chat_history(sess_id)
                self.assertEqual(len(history), 2)
                self.assertEqual(history[0]["role"], "user")
                self.assertEqual(history[0]["sources"], "")
                self.assertEqual(history[1]["role"], "assistant")
                self.assertEqual(history[1]["sources"], sources_json)

    def test_run_inference_web_search_grounding_and_sources(self):
        events = []
        fake_stdout = io.StringIO("Response with grounded info.")
        mock_proc = MagicMock()
        mock_proc.stdout = fake_stdout
        mock_proc.stderr = io.StringIO("")
        mock_proc.wait.return_value = 0

        with tempfile.TemporaryDirectory() as tmp_dir:
            model_file = os.path.join(tmp_dir, "model.gguf")
            with open(model_file, "w") as f:
                f.write("fake")
            cli_bin = os.path.join(tmp_dir, "llama-completion")
            with open(cli_bin, "w") as f:
                f.write("fake")

            sample_search = [{"title": "UBports News", "snippet": "New release available", "url": "https://ubports.com"}]

            with patch.object(backend, "get_llama_completion_path", return_value=cli_bin), \
                 patch.object(backend, "get_llama_cli_path", return_value=cli_bin), \
                 patch.object(backend, "is_binary_working", return_value=True), \
                 patch.object(backend, "_ensure_models_dir", return_value=tmp_dir), \
                 patch.object(backend, "search_web", return_value=sample_search), \
                 patch.object(backend, "_send_event", side_effect=lambda ev, payload: events.append((ev, payload))), \
                 patch.object(backend.subprocess, "Popen", return_value=mock_proc):

                done_ev = threading.Event()
                backend.run_inference(
                    "model.gguf",
                    "Can you search for the latest ubuntu touch release?",
                    0.7,
                    50,
                    4,
                    2048,
                    "off",
                    "f16",
                    True,
                    "req-web-1",
                    lambda ok, err: done_ev.set()
                )
                self.assertTrue(done_ev.wait(timeout=3.0))

            ev_types = [ev[0] for ev in events]
            self.assertIn("web_search_status", ev_types)
            self.assertIn("web_search_sources", ev_types)
            sources_event = next(payload for ev, payload in events if ev == "web_search_sources")
            self.assertEqual(sources_event["sources"], [{"title": "UBports News", "url": "https://ubports.com"}])

    def test_should_search_web_triggers(self):
        self.assertTrue(backend.should_search_web("What is the latest release of Ubuntu Touch?"))
        self.assertTrue(backend.should_search_web("What is the weather in Berlin today?"))
        self.assertTrue(backend.should_search_web("Who won the World Series yesterday?"))
        self.assertTrue(backend.should_search_web("What happened in 2026?"))
        self.assertTrue(backend.should_search_web("Bitcoin price right now"))
        self.assertTrue(backend.should_search_web("https://ubports.com news"))
        self.assertTrue(backend.should_search_web("Search online for Lomiri updates"))

    def test_should_search_web_offline_queries(self):
        self.assertFalse(backend.should_search_web("Write a python function to sort a list"))
        self.assertFalse(backend.should_search_web("Explain how gravity works"))
        self.assertFalse(backend.should_search_web("Translate 'hello world' to German"))
        self.assertFalse(backend.should_search_web("Draft an email thanking my teacher"))
        self.assertFalse(backend.should_search_web(""))
        self.assertFalse(backend.should_search_web(None))

    def test_run_inference_auto_search_skips_offline_prompt(self):
        events = []
        fake_stdout = io.StringIO("Code response.")
        mock_proc = MagicMock()
        mock_proc.stdout = fake_stdout
        mock_proc.stderr = io.StringIO("")
        mock_proc.wait.return_value = 0

        with tempfile.TemporaryDirectory() as tmp_dir:
            model_file = os.path.join(tmp_dir, "m.gguf")
            with open(model_file, "w") as f:
                f.write("fake")
            cli_bin = os.path.join(tmp_dir, "llama-completion")
            with open(cli_bin, "w") as f:
                f.write("fake")

            with patch.object(backend, "get_llama_completion_path", return_value=cli_bin), \
                 patch.object(backend, "get_llama_cli_path", return_value=cli_bin), \
                 patch.object(backend, "is_binary_working", return_value=True), \
                 patch.object(backend, "_ensure_models_dir", return_value=tmp_dir), \
                 patch.object(backend, "search_web") as mock_search, \
                 patch.object(backend, "_send_event", side_effect=lambda ev, payload: events.append((ev, payload))), \
                 patch.object(backend.subprocess, "Popen", return_value=mock_proc):

                done_ev = threading.Event()
                backend.run_inference(
                    "m.gguf",
                    "Write a python function to add two numbers",
                    0.7,
                    50,
                    4,
                    2048,
                    "off",
                    "f16",
                    "auto",
                    "req-auto-1",
                    lambda ok, err: done_ev.set()
                )
                self.assertTrue(done_ev.wait(timeout=3.0))
                mock_search.assert_not_called()
                ev_types = [ev[0] for ev in events]
                self.assertNotIn("web_search_status", ev_types)


if __name__ == "__main__":
    unittest.main()