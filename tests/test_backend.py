"""
Unit tests for backend/backend.py changes introduced in this PR:

- ensure_llama_cli(): OR-based binary verification, multi-URL fallback chain
  (arm64 compat-binary priority, GitHub API tag resolution, generic fallback).
- download_llama_cli_in_background(): OR-based readiness check and error state
  handling around ensure_llama_cli().
- get_release_notes(): loading assets/release_notes.json with a safe default.
- initialize(): exposing "version" and "releaseNotes" in the bridge payload.

These tests use only the Python standard library (unittest + unittest.mock),
matching the fact that backend.py itself has no external dependencies besides
the optional "pyotherside" module (which is stubbed to None when unavailable,
exactly as backend.py already handles at import time).
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import backend  # noqa: E402  (import after sys.path manipulation)


class EnsureLlamaCliTests(unittest.TestCase):
    """Tests for backend.ensure_llama_cli()."""

    def setUp(self):
        patcher_download = mock.patch.object(backend, "_download_and_extract_tar")
        self.mock_download = patcher_download.start()
        self.addCleanup(patcher_download.stop)

        patcher_get_cli = mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli")
        self.mock_get_cli = patcher_get_cli.start()
        self.addCleanup(patcher_get_cli.stop)

        patcher_get_completion = mock.patch.object(
            backend, "get_llama_completion_path", return_value="/fake/llama-completion"
        )
        self.mock_get_completion = patcher_get_completion.start()
        self.addCleanup(patcher_get_completion.stop)

        patcher_is_working = mock.patch.object(backend, "is_binary_working")
        self.mock_is_working = patcher_is_working.start()
        self.addCleanup(patcher_is_working.stop)

        patcher_urlopen = mock.patch.object(backend, "_urlopen")
        self.mock_urlopen = patcher_urlopen.start()
        self.addCleanup(patcher_urlopen.stop)

    def _mock_platform(self, machine="x86_64", system="linux"):
        p1 = mock.patch.object(backend.platform, "machine", return_value=machine)
        p2 = mock.patch.object(backend.platform, "system", return_value=system)
        p1.start()
        self.addCleanup(p1.stop)
        p2.start()
        self.addCleanup(p2.stop)

    def _github_api_response(self, releases):
        payload = json.dumps(releases).encode("utf-8")
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = payload
        return cm

    # -- Already-working shortcuts (OR semantics) -------------------------

    def test_returns_true_immediately_if_cli_binary_already_working(self):
        self.mock_is_working.side_effect = [True]
        result = backend.ensure_llama_cli()
        self.assertTrue(result)
        self.mock_download.assert_not_called()

    def test_returns_true_if_only_completion_binary_working(self):
        # cli fails, completion works -> OR logic still reports success without downloading.
        self.mock_is_working.side_effect = [False, True]
        result = backend.ensure_llama_cli()
        self.assertTrue(result)
        self.mock_download.assert_not_called()

    # -- URL selection logic -----------------------------------------------

    def test_arm64_prioritizes_compat_url_first(self):
        self._mock_platform(machine="aarch64")
        self.mock_urlopen.side_effect = Exception("network down")
        self.mock_is_working.side_effect = [False, False, True]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz"
        )

    def test_x64_uses_resolved_github_release_when_api_succeeds(self):
        self._mock_platform(machine="x86_64")
        self.mock_urlopen.return_value = self._github_api_response(
            [{"tag_name": "b9999", "assets": [{"name": "llama-b9999-bin-ubuntu-x64.tar.gz"}]}]
        )
        self.mock_is_working.side_effect = [False, False, True]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.mock_download.assert_called_once_with(
            "https://github.com/ggml-org/llama.cpp/releases/download/b9999/llama-b9999-bin-ubuntu-x64.tar.gz"
        )

    def test_x64_falls_back_to_compat_url_when_api_fails(self):
        self._mock_platform(machine="x86_64")
        self.mock_urlopen.side_effect = Exception("network down")
        self.mock_is_working.side_effect = [False, False, True]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"
        )

    def test_x64_ignores_releases_without_matching_asset(self):
        self._mock_platform(machine="x86_64")
        self.mock_urlopen.return_value = self._github_api_response(
            [{"tag_name": "b9999", "assets": [{"name": "llama-b9999-bin-ubuntu-arm64.tar.gz"}]}]
        )
        self.mock_is_working.side_effect = [False, False, True]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        # No x64 asset in the release -> falls back to the generic compat URL.
        self.assertTrue(result)
        self.mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"
        )

    def test_unknown_machine_defaults_to_x64_arch(self):
        self._mock_platform(machine="riscv64")
        self.mock_urlopen.side_effect = Exception("network down")
        self.mock_is_working.side_effect = [False, False, True]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"
        )

    # -- Failure / fallback iteration behavior ------------------------------

    def test_returns_false_when_all_downloads_fail(self):
        self._mock_platform(machine="x86_64")
        self.mock_urlopen.side_effect = Exception("network down")
        self.mock_is_working.side_effect = [False, False]
        self.mock_download.return_value = False

        result = backend.ensure_llama_cli()

        self.assertFalse(result)

    def test_returns_false_when_downloaded_binary_fails_verification(self):
        self._mock_platform(machine="x86_64")
        self.mock_urlopen.side_effect = Exception("network down")
        self.mock_is_working.side_effect = [False, False, False, False]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        self.assertFalse(result)

    def test_tries_second_url_when_first_extraction_fails(self):
        self._mock_platform(machine="aarch64")
        self.mock_urlopen.return_value = self._github_api_response(
            [{"tag_name": "b1234", "assets": [{"name": "llama-b1234-bin-ubuntu-arm64.tar.gz"}]}]
        )
        self.mock_download.side_effect = [False, True]
        self.mock_is_working.side_effect = [False, False, True]

        result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.assertEqual(self.mock_download.call_count, 2)
        called_urls = [c.args[0] for c in self.mock_download.call_args_list]
        self.assertEqual(
            called_urls,
            [
                "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz",
                "https://github.com/ggml-org/llama.cpp/releases/download/b1234/llama-b1234-bin-ubuntu-arm64.tar.gz",
            ],
        )

    def test_releases_without_tag_name_are_skipped_without_error(self):
        self._mock_platform(machine="x86_64")
        self.mock_urlopen.return_value = self._github_api_response(
            [{"assets": [{"name": "llama-bin-ubuntu-x64.tar.gz"}]}]
        )
        self.mock_is_working.side_effect = [False, False, True]
        self.mock_download.return_value = True

        result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"
        )


class DownloadLlamaCliInBackgroundTests(unittest.TestCase):
    """Tests for backend.download_llama_cli_in_background()."""

    def setUp(self):
        self._orig_ready = backend.LLAMA_CLI_READY
        self._orig_error = backend.LLAMA_CLI_ERROR
        self._orig_downloading = backend.LLAMA_CLI_DOWNLOADING

    def tearDown(self):
        backend.LLAMA_CLI_READY = self._orig_ready
        backend.LLAMA_CLI_ERROR = self._orig_error
        backend.LLAMA_CLI_DOWNLOADING = self._orig_downloading

    @mock.patch.object(backend, "is_binary_working")
    @mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/completion")
    @mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/cli")
    @mock.patch.object(backend, "ensure_llama_cli")
    def test_ready_true_when_ensure_succeeds_and_binary_works(
        self, mock_ensure, mock_cli_path, mock_completion_path, mock_is_working
    ):
        mock_ensure.return_value = True
        mock_is_working.side_effect = [True]

        backend.download_llama_cli_in_background()

        self.assertTrue(backend.LLAMA_CLI_READY)
        self.assertIsNone(backend.LLAMA_CLI_ERROR)
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @mock.patch.object(backend, "is_binary_working")
    @mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/completion")
    @mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/cli")
    @mock.patch.object(backend, "ensure_llama_cli")
    def test_or_semantics_completion_binary_alone_is_sufficient(
        self, mock_ensure, mock_cli_path, mock_completion_path, mock_is_working
    ):
        # Regression test for the AND -> OR change: cli binary broken but the
        # completion binary works should still be reported as ready.
        mock_ensure.return_value = True
        mock_is_working.side_effect = [False, True]

        backend.download_llama_cli_in_background()

        self.assertTrue(backend.LLAMA_CLI_READY)
        self.assertIsNone(backend.LLAMA_CLI_ERROR)

    @mock.patch.object(backend, "is_binary_working", return_value=False)
    @mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/completion")
    @mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/cli")
    @mock.patch.object(backend, "ensure_llama_cli", return_value=True)
    def test_sets_error_when_ensure_succeeds_but_neither_binary_works(
        self, mock_ensure, mock_cli_path, mock_completion_path, mock_is_working
    ):
        backend.download_llama_cli_in_background()

        self.assertFalse(backend.LLAMA_CLI_READY)
        self.assertEqual(
            backend.LLAMA_CLI_ERROR,
            "Downloaded binary is incompatible with this device (Illegal instruction / crash).",
        )
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @mock.patch.object(backend, "ensure_llama_cli", return_value=False)
    def test_sets_generic_error_when_ensure_fails(self, mock_ensure):
        backend.LLAMA_CLI_READY = True  # pre-existing state must be left untouched on this path

        backend.download_llama_cli_in_background()

        self.assertTrue(backend.LLAMA_CLI_READY)
        self.assertEqual(backend.LLAMA_CLI_ERROR, "Failed to download llama-cli from GitHub")
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @mock.patch.object(backend, "ensure_llama_cli", side_effect=RuntimeError("boom"))
    def test_sets_error_message_from_raised_exception(self, mock_ensure):
        backend.download_llama_cli_in_background()

        self.assertEqual(backend.LLAMA_CLI_ERROR, "boom")
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    @mock.patch.object(backend, "ensure_llama_cli")
    def test_downloading_flag_is_true_during_execution_and_false_after(self, mock_ensure):
        observed = {}

        def fake_ensure():
            observed["downloading_while_running"] = backend.LLAMA_CLI_DOWNLOADING
            return True

        mock_ensure.side_effect = fake_ensure

        with mock.patch.object(backend, "is_binary_working", return_value=True):
            backend.download_llama_cli_in_background()

        self.assertTrue(observed["downloading_while_running"])
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)


class GetReleaseNotesTests(unittest.TestCase):
    """Tests for backend.get_release_notes()."""

    def setUp(self):
        self._orig_app_dir = backend.APP_DIR

    def tearDown(self):
        backend.APP_DIR = self._orig_app_dir

    def test_loads_valid_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets_dir = os.path.join(tmp, "assets")
            os.makedirs(assets_dir)
            data = {
                "version": "1.2.3",
                "date": "2030-01-01",
                "title": "T",
                "subtitle": "S",
                "features": [{"title": "F", "icon": "i", "description": "d"}],
            }
            with open(os.path.join(assets_dir, "release_notes.json"), "w", encoding="utf-8") as f:
                json.dump(data, f)

            backend.APP_DIR = tmp
            result = backend.get_release_notes()

            self.assertEqual(result, data)

    def test_returns_default_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend.APP_DIR = tmp  # no assets/release_notes.json present

            result = backend.get_release_notes()

            self.assertEqual(result["version"], "0.0.2")
            self.assertEqual(result["features"], [])
            self.assertIn("title", result)
            self.assertIn("subtitle", result)

    def test_returns_default_when_file_contains_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            assets_dir = os.path.join(tmp, "assets")
            os.makedirs(assets_dir)
            with open(os.path.join(assets_dir, "release_notes.json"), "w", encoding="utf-8") as f:
                f.write("{not valid json,,,")

            backend.APP_DIR = tmp
            result = backend.get_release_notes()

            self.assertEqual(result["version"], "0.0.2")
            self.assertEqual(result["features"], [])

    def test_real_shipped_release_notes_file_has_expected_schema(self):
        # Exercises the real assets/release_notes.json shipped in this repo
        # (backend.APP_DIR is left untouched here).
        result = backend.get_release_notes()

        self.assertEqual(result["version"], "0.0.2")
        self.assertEqual(result["date"], "2026-07-26")
        self.assertEqual(len(result["features"]), 4)
        for feature in result["features"]:
            self.assertIn("title", feature)
            self.assertIn("icon", feature)
            self.assertIn("description", feature)
            self.assertTrue(feature["title"])
            self.assertTrue(feature["description"])


class InitializeTests(unittest.TestCase):
    """Tests for the new version/releaseNotes fields returned by backend.initialize()."""

    def setUp(self):
        self._orig_ready = backend.LLAMA_CLI_READY

    def tearDown(self):
        backend.LLAMA_CLI_READY = self._orig_ready

    @mock.patch.object(backend, "get_release_notes")
    @mock.patch.object(backend, "is_binary_working", return_value=True)
    @mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/completion")
    @mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/cli")
    @mock.patch.object(backend, "init_db")
    @mock.patch.object(backend, "_ensure_models_dir")
    def test_includes_version_and_release_notes_from_get_release_notes(
        self, mock_ensure_dir, mock_init_db, mock_cli_path, mock_completion_path, mock_is_working, mock_get_notes
    ):
        mock_get_notes.return_value = {"version": "9.9.9", "features": []}

        result = backend.initialize()

        self.assertEqual(result["version"], "9.9.9")
        self.assertEqual(result["releaseNotes"], {"version": "9.9.9", "features": []})
        self.assertTrue(result["ready"])
        self.assertTrue(result["llamaCliReady"])
        mock_get_notes.assert_called_once()

    @mock.patch.object(backend, "get_release_notes")
    @mock.patch.object(backend, "is_binary_working", return_value=False)
    @mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/completion")
    @mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/cli")
    @mock.patch.object(backend, "init_db")
    @mock.patch.object(backend, "_ensure_models_dir")
    def test_falls_back_to_default_version_when_release_notes_missing_version_key(
        self, mock_ensure_dir, mock_init_db, mock_cli_path, mock_completion_path, mock_is_working, mock_get_notes
    ):
        mock_get_notes.return_value = {"features": []}  # no "version" key present

        result = backend.initialize()

        self.assertEqual(result["version"], "0.0.2")
        self.assertFalse(result["llamaCliReady"])


if __name__ == "__main__":
    unittest.main()