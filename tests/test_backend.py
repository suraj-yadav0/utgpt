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
import unittest
from unittest.mock import patch

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
        "version": "0.0.2",
        "date": "2026-07-26",
        "title": "What's New in UTGPT",
        "subtitle": "Version 0.0.2 Release Notes",
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

    def test_version_defaults_to_0_0_2_when_release_notes_missing_version_key(self):
        release_notes = {"date": "2027-01-01", "title": "T", "subtitle": "S", "features": []}
        patches = self._base_patches(True, release_notes)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.initialize()

        self.assertEqual(result["version"], "0.0.2")

    def test_llama_cli_ready_false_when_binaries_not_working(self):
        release_notes = {"version": "0.0.2", "features": []}
        patches = self._base_patches(False, release_notes)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = backend.initialize()

        self.assertFalse(result["llamaCliReady"])
        self.assertFalse(backend.LLAMA_CLI_READY)

    def test_result_shape_contains_all_expected_keys(self):
        release_notes = {"version": "0.0.2", "features": []}
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


if __name__ == "__main__":
    unittest.main()