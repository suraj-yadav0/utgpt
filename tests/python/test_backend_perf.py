"""Backend performance-path tests: ctx capping, bounded doc RAG, search cache."""
import os
import sqlite3
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

import backend


def test_effective_ctx_size_caps_to_model_max():
    assert backend.effective_ctx_size(8192, {"maxContext": 2048}) == 2048
    assert backend.effective_ctx_size(2048, {"maxContext": 128000}) == 2048
    assert backend.effective_ctx_size(4096, {"maxContext": 8192}) == 4096


def test_effective_ctx_size_floor_and_fallbacks():
    assert backend.effective_ctx_size(100, {"maxContext": 2048}) == 512
    assert backend.effective_ctx_size(2048, None) == 2048
    assert backend.effective_ctx_size("bad", None) == 2048
    assert backend.effective_ctx_size(2048, {"maxContext": "bad"}) == 2048


@pytest.fixture()
def doc_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(backend, "DB_PATH", db_path)
    backend.init_db()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO sessions (title, created_at) VALUES ('S', 1)")
    session_id = cur.lastrowid
    cur.execute(
        "INSERT INTO documents (session_id, filename, file_path, file_size,"
        " char_count, created_at) VALUES (?,?,?,?,?,?)",
        (session_id, "doc.txt", "/x", 1, 1, time.time()),
    )
    document_id = cur.lastrowid
    chunks = [
        "",
        "[Image attached: foo]",
        "alpha",
        "[PDF Document attached]",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
    ]
    for index, content in enumerate(chunks):
        cur.execute(
            "INSERT INTO document_chunks (document_id, chunk_index, content)"
            " VALUES (?,?,?)",
            (document_id, index, content),
        )
    conn.commit()
    conn.close()
    return session_id


def test_retrieve_document_context_first_n_valid_chunks(doc_db):
    import re

    out = backend.retrieve_document_context("q", session_id=doc_db, limit=6)
    quoted = re.findall(r'"""\n(.*?)\n"""', out, re.S)
    assert quoted == ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]


def test_retrieve_document_context_respects_limit(doc_db):
    import re

    out = backend.retrieve_document_context("q", session_id=doc_db, limit=2)
    quoted = re.findall(r'"""\n(.*?)\n"""', out, re.S)
    assert quoted == ["alpha", "beta"]


def test_search_web_cache_hit_skips_network(monkeypatch):
    backend.WEB_SEARCH_CACHE.clear()
    backend.WEB_SEARCH_CACHE["hello"] = (
        time.time(),
        [{"title": "T", "snippet": "S", "url": "U"}],
    )

    def fail_if_called(req, timeout=0):
        raise AssertionError("network should not be touched on cache hit")

    monkeypatch.setattr(backend, "_urlopen", fail_if_called)
    assert backend.search_web("  HELLO ") == [
        {"title": "T", "snippet": "S", "url": "U"}
    ]


def test_search_web_expired_entry_goes_to_network(monkeypatch):
    backend.WEB_SEARCH_CACHE.clear()
    backend.WEB_SEARCH_CACHE["old"] = (
        time.time() - 4000,
        [{"title": "X", "snippet": "Y", "url": "Z"}],
    )
    monkeypatch.setattr(
        backend,
        "_urlopen",
        lambda req, timeout=0: (_ for _ in ()).throw(OSError("offline")),
    )
    assert backend.search_web("old") == []
