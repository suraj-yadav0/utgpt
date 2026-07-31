"""
Unit tests for backend/backend.py.

Scope: this test module only covers the code paths touched by the
"release notes / v0.1.0" pull request:

  * ensure_llama_cli()              - changed AND -> OR check, multi-URL
                                        fallback download logic
  * download_llama_cli_in_background() - changed AND -> OR verification
  * get_release_notes()             - new function
  * initialize()                    - new "version"/"releaseNotes" fields

No third-party test runner (pytest, etc.) is available/installable in this
environment, so these tests rely solely on the Python standard library
(``unittest`` + ``unittest.mock``) and can be executed with:

    python3 -m unittest discover -s backend/tests
"""

import importlib.util
import json
import os
import sys
import tempfile
import shutil
import unittest
from unittest import mock

# Load backend/backend.py directly by file path (registered under a unique
# module name) rather than via a plain `import backend`, since the
# `backend/` directory has no __init__.py and would otherwise be resolved
# as an ambiguous namespace package when tests are run from the repo root.
_BACKEND_PY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend.py"))
_spec = importlib.util.spec_from_file_location("utgpt_backend_module", _BACKEND_PY_PATH)
backend = importlib.util.module_from_spec(_spec)
sys.modules["utgpt_backend_module"] = backend
_spec.loader.exec_module(backend)


class ReleaseNotesTestCase(unittest.TestCase):
    """Tests for backend.get_release_notes()."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)
        self.assets_dir = os.path.join(self.tmp_dir, "assets")
        os.makedirs(self.assets_dir)
        self.notes_path = os.path.join(self.assets_dir, "release_notes.json")
        self.app_dir_patch = mock.patch.object(backend, "APP_DIR", self.tmp_dir)
        self.app_dir_patch.start()
        self.addCleanup(self.app_dir_patch.stop)

    def _write_notes(self, content):
        with open(self.notes_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_returns_parsed_json_when_file_exists_and_valid(self):
        payload = {
            "version": "1.2.3",
            "date": "2030-01-01",
            "title": "Custom Title",
            "subtitle": "Custom Subtitle",
            "features": [{"title": "A", "icon": "icon-a", "description": "desc"}],
        }
        self._write_notes(json.dumps(payload))

        result = backend.get_release_notes()

        self.assertEqual(result, payload)

    def test_returns_default_when_file_missing(self):
        # Note: notes_path is never written in this test.
        result = backend.get_release_notes()

        self.assertEqual(result["version"], "0.0.2")
        self.assertEqual(result["date"], "2026-07-26")
        self.assertEqual(result["title"], "What's New in UTGPT")
        self.assertEqual(result["subtitle"], "Version 0.0.2 Release Notes")
        self.assertEqual(result["features"], [])

    def test_returns_default_when_json_is_malformed(self):
        self._write_notes("{not valid json,,,")

        with mock.patch.object(backend, "log_error") as mock_log_error:
            result = backend.get_release_notes()

        self.assertEqual(result["version"], "0.0.2")
        self.assertEqual(result["features"], [])
        mock_log_error.assert_called_once()
        self.assertIn("Failed to load release notes", mock_log_error.call_args[0][0])

    def test_returns_default_when_file_is_empty(self):
        self._write_notes("")

        result = backend.get_release_notes()

        self.assertEqual(result["version"], "0.0.2")
        self.assertEqual(result["features"], [])

    def test_default_dict_is_independent_between_calls(self):
        # Mutating the result of one call must not affect subsequent calls.
        first = backend.get_release_notes()
        first["features"].append({"title": "mutated"})

        second = backend.get_release_notes()

        self.assertEqual(second["features"], [])


class EnsureLlamaCliTestCase(unittest.TestCase):
    """Tests for backend.ensure_llama_cli()."""

    def setUp(self):
        patchers = [
            mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/llama-cli"),
            mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/llama-completion"),
            mock.patch.object(backend, "log_info"),
            mock.patch.object(backend, "log_error"),
        ]
        self.mocks = {}
        for p in patchers:
            name = p.attribute
            self.mocks[name] = p.start()
            self.addCleanup(p.stop)

    def test_returns_true_immediately_when_cli_binary_already_working(self):
        with mock.patch.object(backend, "is_binary_working", side_effect=[True, False]) as mock_working, \
             mock.patch.object(backend, "_download_and_extract_tar") as mock_download:
            result = backend.ensure_llama_cli()

        self.assertTrue(result)
        mock_download.assert_not_called()
        # Because of Python's `or` short-circuiting, only the first check runs.
        self.assertEqual(mock_working.call_count, 1)

    def test_returns_true_immediately_when_only_completion_binary_working(self):
        """Regression test for the AND -> OR change: cli broken but
        completion working should still short-circuit as ready."""
        with mock.patch.object(backend, "is_binary_working", side_effect=[False, True]), \
             mock.patch.object(backend, "_download_and_extract_tar") as mock_download:
            result = backend.ensure_llama_cli()

        self.assertTrue(result)
        mock_download.assert_not_called()

    def test_arm64_tries_compat_url_first_when_github_api_fails(self):
        with mock.patch.object(backend.platform, "machine", return_value="aarch64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", side_effect=Exception("network down")), \
             mock.patch.object(backend, "is_binary_working", side_effect=[False, False, True]), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=True) as mock_download:
            result = backend.ensure_llama_cli()

        self.assertTrue(result)
        mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz"
        )

    def test_x64_uses_github_api_resolved_url_when_available(self):
        releases_payload = json.dumps([
            {
                "tag_name": "b9999",
                "assets": [{"name": "llama-b9999-bin-ubuntu-x64.tar.gz"}],
            }
        ]).encode("utf-8")

        mock_response = mock.MagicMock()
        mock_response.read.return_value = releases_payload
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_response
        mock_ctx.__exit__.return_value = False

        with mock.patch.object(backend.platform, "machine", return_value="x86_64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", return_value=mock_ctx), \
             mock.patch.object(backend, "is_binary_working", side_effect=[False, False, True]), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=True) as mock_download:
            result = backend.ensure_llama_cli()

        self.assertTrue(result)
        mock_download.assert_called_once_with(
            "https://github.com/ggml-org/llama.cpp/releases/download/b9999/llama-b9999-bin-ubuntu-x64.tar.gz"
        )

    def test_falls_back_to_compat_url_when_no_api_match_and_not_arm(self):
        with mock.patch.object(backend.platform, "machine", return_value="x86_64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", side_effect=Exception("network down")), \
             mock.patch.object(backend, "is_binary_working", return_value=False), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=False) as mock_download:
            result = backend.ensure_llama_cli()

        self.assertFalse(result)
        mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"
        )

    def test_returns_false_when_all_download_urls_fail(self):
        with mock.patch.object(backend.platform, "machine", return_value="aarch64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", side_effect=Exception("network down")), \
             mock.patch.object(backend, "is_binary_working", return_value=False), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=False):
            result = backend.ensure_llama_cli()

        self.assertFalse(result)

    def test_tries_second_url_when_first_download_fails(self):
        releases_payload = json.dumps([
            {
                "tag_name": "b1111",
                "assets": [{"name": "llama-b1111-bin-ubuntu-arm64.tar.gz"}],
            }
        ]).encode("utf-8")
        mock_response = mock.MagicMock()
        mock_response.read.return_value = releases_payload
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_response
        mock_ctx.__exit__.return_value = False

        expected_api_url = "https://github.com/ggml-org/llama.cpp/releases/download/b1111/llama-b1111-bin-ubuntu-arm64.tar.gz"
        expected_compat_url = "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz"

        with mock.patch.object(backend.platform, "machine", return_value="aarch64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", return_value=mock_ctx), \
             mock.patch.object(backend, "is_binary_working", side_effect=[False, False, True]), \
             mock.patch.object(backend, "_download_and_extract_tar", side_effect=[False, True]) as mock_download:
            result = backend.ensure_llama_cli()

        self.assertTrue(result)
        self.assertEqual(
            [call.args[0] for call in mock_download.call_args_list],
            [expected_compat_url, expected_api_url],
        )

    def test_returns_false_when_download_succeeds_but_binary_still_broken(self):
        with mock.patch.object(backend.platform, "machine", return_value="aarch64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", side_effect=Exception("network down")), \
             mock.patch.object(backend, "is_binary_working", return_value=False), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=True):
            result = backend.ensure_llama_cli()

        self.assertFalse(result)

    def test_unknown_arm_machine_string_defaults_to_arm64(self):
        with mock.patch.object(backend.platform, "machine", return_value="armv7l"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", side_effect=Exception("network down")), \
             mock.patch.object(backend, "is_binary_working", return_value=False), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=False) as mock_download:
            backend.ensure_llama_cli()

        mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz"
        )

    def test_unknown_non_arm_machine_string_defaults_to_x64(self):
        with mock.patch.object(backend.platform, "machine", return_value="riscv64"), \
             mock.patch.object(backend.platform, "system", return_value="linux"), \
             mock.patch.object(backend, "_urlopen", side_effect=Exception("network down")), \
             mock.patch.object(backend, "is_binary_working", return_value=False), \
             mock.patch.object(backend, "_download_and_extract_tar", return_value=False) as mock_download:
            backend.ensure_llama_cli()

        mock_download.assert_called_once_with(
            "https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-x64.tar.gz"
        )


class DownloadLlamaCliInBackgroundTestCase(unittest.TestCase):
    """Tests for backend.download_llama_cli_in_background()."""

    def setUp(self):
        self.orig_ready = backend.LLAMA_CLI_READY
        self.orig_error = backend.LLAMA_CLI_ERROR
        self.orig_downloading = backend.LLAMA_CLI_DOWNLOADING

        def restore():
            backend.LLAMA_CLI_READY = self.orig_ready
            backend.LLAMA_CLI_ERROR = self.orig_error
            backend.LLAMA_CLI_DOWNLOADING = self.orig_downloading

        self.addCleanup(restore)

        patchers = [
            mock.patch.object(backend, "get_llama_cli_path", return_value="cli_path"),
            mock.patch.object(backend, "get_llama_completion_path", return_value="completion_path"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_ready_true_when_both_binaries_working(self):
        with mock.patch.object(backend, "ensure_llama_cli", return_value=True), \
             mock.patch.object(backend, "is_binary_working", return_value=True):
            backend.download_llama_cli_in_background()

        self.assertTrue(backend.LLAMA_CLI_READY)
        self.assertIsNone(backend.LLAMA_CLI_ERROR)
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    def test_ready_true_when_only_completion_binary_working(self):
        """Regression test for the AND -> OR change."""
        def working(path):
            return path == "completion_path"

        with mock.patch.object(backend, "ensure_llama_cli", return_value=True), \
             mock.patch.object(backend, "is_binary_working", side_effect=working):
            backend.download_llama_cli_in_background()

        self.assertTrue(backend.LLAMA_CLI_READY)
        self.assertIsNone(backend.LLAMA_CLI_ERROR)

    def test_ready_false_with_error_when_binaries_not_working_after_success(self):
        with mock.patch.object(backend, "ensure_llama_cli", return_value=True), \
             mock.patch.object(backend, "is_binary_working", return_value=False):
            backend.download_llama_cli_in_background()

        self.assertFalse(backend.LLAMA_CLI_READY)
        self.assertEqual(
            backend.LLAMA_CLI_ERROR,
            "Downloaded binary is incompatible with this device (Illegal instruction / crash).",
        )
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    def test_error_set_when_ensure_llama_cli_returns_false(self):
        with mock.patch.object(backend, "ensure_llama_cli", return_value=False):
            backend.download_llama_cli_in_background()

        self.assertEqual(backend.LLAMA_CLI_ERROR, "Failed to download llama-cli from GitHub")
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)

    def test_downloading_flag_reset_when_exception_raised(self):
        with mock.patch.object(backend, "ensure_llama_cli", side_effect=RuntimeError("boom")):
            backend.download_llama_cli_in_background()

        self.assertEqual(backend.LLAMA_CLI_ERROR, "boom")
        self.assertFalse(backend.LLAMA_CLI_DOWNLOADING)


class InitializeTestCase(unittest.TestCase):
    """Tests for the new fields returned by backend.initialize()."""

    def setUp(self):
        patchers = [
            mock.patch.object(backend, "_ensure_models_dir"),
            mock.patch.object(backend, "init_db"),
            mock.patch.object(backend, "get_llama_cli_path", return_value="/fake/cli"),
            mock.patch.object(backend, "get_llama_completion_path", return_value="/fake/completion"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_includes_version_and_release_notes_from_get_release_notes(self):
        fake_notes = {"version": "1.2.3", "features": [{"title": "X", "icon": "i", "description": "d"}]}
        with mock.patch.object(backend, "is_binary_working", return_value=True), \
             mock.patch.object(backend, "get_release_notes", return_value=fake_notes), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = backend.initialize()

        self.assertEqual(result["version"], "1.2.3")
        self.assertEqual(result["releaseNotes"], fake_notes)

    def test_version_defaults_to_0_0_2_when_release_notes_missing_version_key(self):
        with mock.patch.object(backend, "is_binary_working", return_value=True), \
             mock.patch.object(backend, "get_release_notes", return_value={"features": []}), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = backend.initialize()

        self.assertEqual(result["version"], "0.0.2")

    def test_is_desktop_false_when_app_id_env_var_set(self):
        with mock.patch.object(backend, "is_binary_working", return_value=True), \
             mock.patch.object(backend, "get_release_notes", return_value={"version": "0.0.2"}), \
             mock.patch.dict(os.environ, {"APP_ID": "utgpt.surajyadav"}, clear=True):
            result = backend.initialize()

        self.assertFalse(result["isDesktop"])

    def test_is_desktop_true_when_no_app_launch_env_vars_set(self):
        with mock.patch.object(backend, "is_binary_working", return_value=True), \
             mock.patch.object(backend, "get_release_notes", return_value={"version": "0.0.2"}), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = backend.initialize()

        self.assertTrue(result["isDesktop"])

    def test_result_contains_ready_and_models_dir(self):
        with mock.patch.object(backend, "is_binary_working", return_value=True), \
             mock.patch.object(backend, "get_release_notes", return_value={"version": "0.0.2"}), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = backend.initialize()

        self.assertTrue(result["ready"])
        self.assertEqual(result["modelsDir"], backend.MODELS_DIR)


if __name__ == "__main__":
    unittest.main()