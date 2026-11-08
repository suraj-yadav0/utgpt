#
# backend.py
#
# Provides the UTGPT Python bridge for model discovery, storage checks, model
# downloads, and llama.cpp inference streaming through PyOtherSide events.
#

import os
import subprocess
import threading
import urllib.request
import urllib.error
import urllib.parse
import platform
import tarfile
import io
import time
import sys
import sqlite3
import signal
import atexit
import ctypes
import ctypes.util
import json
import shutil
import re
from contextlib import contextmanager
from html.parser import HTMLParser

DEBUG_MODE = os.environ.get("UTGPT_DEBUG", "").lower() in ("1", "true", "yes")

def log_debug(msg):
    if DEBUG_MODE:
        print("UTGPT_LOG [DEBUG]: {0}".format(msg), file=sys.stderr, flush=True)

def log_info(msg):
    print("UTGPT_LOG [INFO]: {0}".format(msg), file=sys.stderr, flush=True)

def log_error(msg):
    print("UTGPT_LOG [ERROR]: {0}".format(msg), file=sys.stderr, flush=True)

def _preexec_set_pdeathsig():
    if sys.platform.startswith("linux"):
        try:
            libc_name = ctypes.util.find_library("c") or "libc.so.6"
            libc = ctypes.CDLL(libc_name)
            libc.prctl(1, signal.SIGTERM)
        except Exception:
            pass

def _urlopen(req, timeout=60):
    return urllib.request.urlopen(req, timeout=timeout)


def _clean_ddg_url(url):
    if not url:
        return ""
    try:
        if "uddg=" in url:
            parsed = urllib.parse.urlsplit(url)
            query = parsed.query
            if not query and "?" in url:
                query = url.split("?", 1)[1]
            params = urllib.parse.parse_qs(query)
            if "uddg" in params and params["uddg"]:
                return params["uddg"][0]
    except Exception:
        pass
    return url


class DDGLiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current_result = {}
        self.in_snippet = False
        self.in_link = False
        self.accumulated_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a" and attrs_dict.get("class") == "result-link":
            self.in_link = True
            raw_url = attrs_dict.get("href", "")
            self.current_result = {"url": _clean_ddg_url(raw_url)}
            self.accumulated_text = []
        elif tag == "td" and attrs_dict.get("class") == "result-snippet":
            self.in_snippet = True
            self.accumulated_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self.in_link:
            self.in_link = False
            self.current_result["title"] = "".join(self.accumulated_text).strip()
        elif tag == "td" and self.in_snippet:
            self.in_snippet = False
            self.current_result["snippet"] = "".join(self.accumulated_text).strip()
            if "title" in self.current_result and self.current_result["title"]:
                self.results.append(self.current_result)
                self.current_result = {}

    def handle_data(self, data):
        if self.in_link or self.in_snippet:
            self.accumulated_text.append(data)


WEB_SEARCH_CACHE = {}
WEB_SEARCH_CACHE_TTL = 1800.0
WEB_SEARCH_TIMEOUT = 3.5
WEB_SEARCH_CACHE_LOCK = threading.Lock()


def search_web(query, num_results=3):
    """
    Performs a privacy-focused DuckDuckGo Lite search using standard Python libraries,
    returning structured web titles, snippets, and URLs.

    Results are cached in memory (30 min TTL) so repeat questions answer instantly
    instead of paying DNS + TLS + DuckDuckGo latency on every request.
    """
    cache_key = (query or "").strip().lower()
    now = time.time()
    with WEB_SEARCH_CACHE_LOCK:
        cached = WEB_SEARCH_CACHE.get(cache_key)
        if cached and now - cached[0] < WEB_SEARCH_CACHE_TTL:
            return [dict(item) for item in cached[1][:num_results]]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with _urlopen(req, timeout=WEB_SEARCH_TIMEOUT) as response:
            html = response.read().decode("utf-8", errors="ignore")
            parser = DDGLiteParser()
            parser.feed(html)
            results = parser.results[:num_results]
            with WEB_SEARCH_CACHE_LOCK:
                if len(WEB_SEARCH_CACHE) > 200:
                    WEB_SEARCH_CACHE.clear()
                WEB_SEARCH_CACHE[cache_key] = (now, results)
            return [dict(item) for item in results]
    except Exception as e:
        log_error("Web search failed for query '{0}': {1}".format(query, e))
        return []


ACTIVE_DOWNLOADS = {}
DOWNLOADS_LOCK = threading.Lock()

try:
    import pyotherside
except ImportError:  # pragma: no cover - only unavailable outside the app runtime
    pyotherside = None


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODELS_DIR = os.path.expanduser("~/.local/share/utgpt.surajyadav/models")
PROMPT_CACHE_DIR = os.path.expanduser("~/.local/share/utgpt.surajyadav/prompt_cache")
LLAMA_CLI_PATH_BUNDLED = os.path.join(APP_DIR, "assets", "llama-cli")
LLAMA_CLI_PATH_WRITABLE = os.path.join(MODELS_DIR, "llama-cli")
LLAMA_COMPLETION_PATH_BUNDLED = os.path.join(APP_DIR, "assets", "llama-completion")
LLAMA_COMPLETION_PATH_WRITABLE = os.path.join(MODELS_DIR, "llama-completion")

def is_binary_working(path):
    if not os.path.exists(path):
        return False
    try:
        env = os.environ.copy()
        ld_library_paths = [os.path.join(APP_DIR, "assets")]
        if "LD_LIBRARY_PATH" in env:
            env["LD_LIBRARY_PATH"] = os.path.pathsep.join(ld_library_paths + [env["LD_LIBRARY_PATH"]])
        else:
            env["LD_LIBRARY_PATH"] = os.path.pathsep.join(ld_library_paths)
            
        res = subprocess.run([path, "-h"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
        if res.returncode != 0:
            log_error("Binary check failed for {0} with return code {1}. Stderr: {2}".format(path, res.returncode, res.stderr))
            return False
        return True
    except Exception as e:
        log_error("Exception in is_binary_working for {0}: {1}".format(path, e))
        return False

def get_llama_cli_path():
    if is_binary_working(LLAMA_CLI_PATH_BUNDLED):
        return LLAMA_CLI_PATH_BUNDLED
    return LLAMA_CLI_PATH_WRITABLE

def get_llama_completion_path():
    if is_binary_working(LLAMA_COMPLETION_PATH_BUNDLED):
        return LLAMA_COMPLETION_PATH_BUNDLED
    return LLAMA_COMPLETION_PATH_WRITABLE

DOWNLOAD_CHUNK_SIZE = 64 * 1024
INFERENCE_LOCK = threading.Lock()
ACTIVE_PROCESSES = set()
ACTIVE_TOKENS = set()

MODELS_JSON_PATH = os.path.join(APP_DIR, "assets", "models.json")


def _load_default_catalog():
    if os.path.isfile(MODELS_JSON_PATH):
        try:
            with open(MODELS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error("Failed to load models.json: {0}".format(e))
    return []


DEFAULT_CATALOG = _load_default_catalog()

def get_total_ram_gb():
    try:
        return (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / (1024.0 ** 3)
    except Exception:
        pass
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_kb = int(line.split()[1])
                    return mem_kb / (1024.0 * 1024.0)
    except Exception:
        pass
    return 4.0

def get_model_compatibility(size_str, ram_gb):
    try:
        size_str = size_str.lower().replace("~", "").strip()
        if "gb" in size_str:
            size_gb = float(size_str.split("gb")[0].strip())
        elif "mb" in size_str:
            size_gb = float(size_str.split("mb")[0].strip()) / 1024.0
        else:
            size_gb = 1.5
    except Exception:
        size_gb = 1.5

    if ram_gb <= 2.2:
        if size_gb <= 0.45:
            return "green"
        elif size_gb <= 0.75:
            return "yellow"
        else:
            return "red"
    elif ram_gb <= 3.1:
        if size_gb <= 0.6:
            return "green"
        elif size_gb <= 1.2:
            return "yellow"
        else:
            return "red"
    elif ram_gb <= 4.2:
        if size_gb <= 1.1:
            return "green"
        elif size_gb <= 1.8:
            return "yellow"
        else:
            return "red"
    else:
        if size_gb <= 1.8:
            return "green"
        elif size_gb <= 2.5:
            return "yellow"
        else:
            return "red"

def fetch_model_catalog():
    """
    Returns the locally cached catalog or falls back to DEFAULT_CATALOG.
    Starts a background thread to fetch the latest catalog from GitHub.
    """
    ram_gb = get_total_ram_gb()
    cache_path = os.path.join(MODELS_DIR, "catalog.json")
    catalog_data = []

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                catalog_data = json.load(f)
        except Exception as e:
            log_error("Failed to load cached catalog: " + str(e))

    if not isinstance(catalog_data, list) or len(catalog_data) == 0:
        catalog_data = [item.copy() for item in DEFAULT_CATALOG]

    # Process compatibility for the immediate return
    for item in catalog_data:
        size_str = item.get("size", "1.5 GB")
        compat = get_model_compatibility(size_str, ram_gb)
        item["compatibility"] = compat
        if compat == "green":
            item["compatibilityText"] = "Highly Recommended"
        elif compat == "yellow":
            item["compatibilityText"] = "Runs Fine"
        else:
            item["compatibilityText"] = "Heavy (May lag/crash)"

    # Spawn background thread to fetch from Github without blocking PyOtherSide
    threading.Thread(target=_bg_fetch_catalog, args=(ram_gb,), daemon=True).start()

    return catalog_data


def _bg_fetch_catalog(ram_gb):
    """
    Background worker thread to pull model catalog from github,
    save it locally, and send a PyOtherSide event to refresh the UI.
    """
    url = "https://raw.githubusercontent.com/suraj-yadav0/utgpt/main/assets/models.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                required_keys = {"name", "filename", "url"}
                if all(required_keys.issubset(item.keys()) for item in data):
                    for item in data:
                        size_str = item.get("size", "1.5 GB")
                        compat = get_model_compatibility(size_str, ram_gb)
                        item["compatibility"] = compat
                        if compat == "green":
                            item["compatibilityText"] = "Highly Recommended"
                        elif compat == "yellow":
                            item["compatibilityText"] = "Runs Fine"
                        else:
                            item["compatibilityText"] = "Heavy (May lag/crash)"

                    _ensure_models_dir()
                    cache_path = os.path.join(MODELS_DIR, "catalog.json")
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)

                    if pyotherside:
                        pyotherside.send({"event": "catalog_updated", "payload": data})
                    log_info("Successfully updated remote model catalog and notified frontend.")
    except Exception as e:
        log_error("Failed to fetch remote model catalog in background: " + str(e))


def _ensure_models_dir():
    os.makedirs(MODELS_DIR, exist_ok=True)
    return MODELS_DIR


def _ensure_prompt_cache_dir():
    if not os.path.exists(PROMPT_CACHE_DIR):
        try:
            os.makedirs(PROMPT_CACHE_DIR, exist_ok=True)
        except OSError:
            pass
    return PROMPT_CACHE_DIR


def _clear_session_prompt_cache(session_id):
    if not session_id:
        return
    try:
        cache_dir = _ensure_prompt_cache_dir()
        safe_session = re.sub(r'[^a-zA-Z0-9_-]', '_', str(session_id))
        prefix = "{0}_".format(safe_session)
        for name in os.listdir(cache_dir):
            if name.startswith(prefix) and name.endswith(".bin"):
                try:
                    os.remove(os.path.join(cache_dir, name))
                except OSError:
                    pass
    except Exception:
        pass


def _clear_all_prompt_cache():
    try:
        cache_dir = _ensure_prompt_cache_dir()
        for name in os.listdir(cache_dir):
            if name.endswith(".bin"):
                try:
                    os.remove(os.path.join(cache_dir, name))
                except OSError:
                    pass
    except Exception:
        pass


def _clear_model_prompt_cache(model_filename):
    if not model_filename:
        return
    try:
        cache_dir = _ensure_prompt_cache_dir()
        safe_model = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(os.path.basename(model_filename))[0])
        suffix = "_{0}.bin".format(safe_model)
        for name in os.listdir(cache_dir):
            if name.endswith(suffix):
                try:
                    os.remove(os.path.join(cache_dir, name))
                except OSError:
                    pass
    except Exception:
        pass


def _send_event(event_name, payload):
    if pyotherside is not None:
        pyotherside.send({"event": event_name, "payload": payload})


def _emit_download_progress(callback_ref, name, filename, progress):
    if callable(callback_ref):
        callback_ref(progress)
        return
    if callback_ref:
        _send_event("download_progress", {
            "requestId": str(callback_ref),
            "name": name,
            "filename": filename,
            "progress": progress
        })


def _emit_download_complete(callback_ref, name, filename):
    if callback_ref and not callable(callback_ref):
        _send_event("download_complete", {
            "requestId": str(callback_ref),
            "name": name,
            "filename": filename
        })


def _emit_download_error(callback_ref, name, message):
    if callback_ref and not callable(callback_ref):
        _send_event("download_error", {
            "requestId": str(callback_ref),
            "name": name,
            "error": message
        })


def _emit_download_paused(callback_ref, name, filename, progress):
    if callback_ref and not callable(callback_ref):
        _send_event("download_paused", {
            "requestId": str(callback_ref),
            "name": name,
            "filename": filename,
            "progress": progress
        })


def _emit_token(callback_ref, text):
    if callable(callback_ref):
        callback_ref(text)
        return
    if callback_ref:
        _send_event("inference_token", {
            "requestId": str(callback_ref),
            "text": text
        })


def clean_search_query(query):
    if not query:
        return ""
    q = query.strip()
    patterns = [
        r"^(please\s+)?(can|could|would)\s+you\s+(please\s+)?(tell\s+me(\s+about)?|check(\s+for)?|search(\s+the\s+web)?(\s+for)?|find(\s+out)?|look\s+up)\s+",
        r"^(please\s+)?(tell\s+me(\s+about)?|search(\s+for|\s+the\s+web\s+for)?|look\s+up|find)\s+",
        r"^(hey\s+|hi\s+|hello\s+)?(can\s+you\s+)?(what\s+is|what\s+are|who\s+is|where\s+is)\s+",
    ]
    for p in patterns:
        q = re.sub(p, "", q, flags=re.IGNORECASE).strip()
    q = re.sub(r"[?!.]+$", "", q).strip()
    return q if len(q) >= 2 else query.strip()


def should_search_web(query):
    if not query:
        return False
    q = query.lower().strip()

    # Explicit lookup commands or URLs
    if re.search(r"\b(search(\s+the\s+web)?|look\s+up|google|check\s+online|find\s+online)\b", q) or "http://" in q or "https://" in q or "www." in q:
        return True

    # Temporal cues indicating real-time freshness
    if re.search(r"\b(today|yesterday|tomorrow|tonight|currently|current|latest|newest|recent|recently|upcoming|this\s+(week|month|year)|right\s+now|now)\b", q):
        return True

    # Recent and current calendar years
    if re.search(r"\b(202[4-9]|203[0-9])\b", q):
        return True

    # Real-time entities, financial, weather, and fast-moving topics
    if re.search(r"\b(weather|forecast|stock(\s+price)?|crypto|bitcoin|btc|eth|news|headlines?|breaking\s+news|release\s+date|changelog|patch\s+notes)\b", q):
        return True

    # Dynamic roles, scores, or event outcomes
    if re.search(r"\b(who\s+won|score\s+of|game\s+score|standings|who\s+is\s+the\s+(current|new)?\s*(ceo|president|prime\s+minister))\b", q):
        return True

    return False


def _emit_search_status(callback_ref, phase, query="", count=0, sources=None):
    # Transient UI status only (never part of the chat text).
    if callback_ref and not callable(callback_ref):
        payload = {
            "requestId": str(callback_ref),
            "phase": phase
        }
        if query:
            payload["query"] = query
        if count:
            payload["count"] = count
        if sources is not None:
            payload["sources"] = sources
        _send_event("web_search_status", payload)


def _emit_done(callback_ref, ok=True, error_message=""):
    if callable(callback_ref):
        try:
            callback_ref(ok, error_message)
        except TypeError:
            callback_ref()
        return
    if callback_ref:
        _send_event("inference_done", {
            "requestId": str(callback_ref),
            "ok": ok,
            "error": error_message
        })


def _register_process(process):
    with INFERENCE_LOCK:
        ACTIVE_PROCESSES.add(process)


def _unregister_process(process):
    with INFERENCE_LOCK:
        ACTIVE_PROCESSES.discard(process)


def _terminate_process(process):
    if process is None:
        return
    if process.poll() is not None:
        return

    def killer():
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=killer, daemon=True).start()


def list_models():
    models_dir = _ensure_models_dir()
    if not os.path.isdir(models_dir):
        return []

    entries = []
    for filename in os.listdir(models_dir):
        if filename.lower().endswith(".gguf") and not filename.lower().startswith("mmproj"):
            entries.append(filename)
    entries.sort()
    return entries


def get_free_storage():
    models_dir = _ensure_models_dir()
    free_gb = shutil.disk_usage(models_dir).free / float(1024 ** 3)
    return "{0:.1f} GB free".format(free_gb)


def download_model_thread(name, url, progress_callback):
    models_dir = os.path.realpath(_ensure_models_dir())
    clean_name = os.path.basename(name or "")
    url_str = (url or "").strip()
    parsed_url = urllib.parse.urlsplit(url_str)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        _emit_download_error(progress_callback, name, "Invalid download URL")
        return ""

    url_filename = os.path.basename(parsed_url.path)
    filename = url_filename or (clean_name + ".gguf" if clean_name else "model.gguf")
    filename = os.path.basename(filename)
    if not filename or filename in (".", ".."):
        filename = (clean_name + ".gguf") if clean_name and clean_name not in (".", "..") else "model.gguf"

    destination = os.path.realpath(os.path.join(models_dir, filename))
    if not destination.startswith(models_dir + os.sep):
        _emit_download_error(progress_callback, name, "Invalid destination path")
        return ""
    temp_destination = destination + ".part"

    bytes_written = 0
    if os.path.exists(temp_destination):
        bytes_written = os.path.getsize(temp_destination)

    total_size = 0
    try:
        request = urllib.request.Request(url_str, headers={"User-Agent": "UTGPT/0.1"})
        
        try:
            if bytes_written > 0:
                request.add_header("Range", "bytes={0}-".format(bytes_written))
            response = _urlopen(request, timeout=60)
        except urllib.error.HTTPError as http_err:
            if bytes_written > 0:
                bytes_written = 0
                request = urllib.request.Request(url_str, headers={"User-Agent": "UTGPT/0.1"})
                response = _urlopen(request, timeout=60)
            else:
                raise http_err
        except Exception as err:
            if bytes_written > 0:
                bytes_written = 0
                request = urllib.request.Request(url_str, headers={"User-Agent": "UTGPT/0.1"})
                response = _urlopen(request, timeout=60)
            else:
                raise err

        with DOWNLOADS_LOCK:
            if progress_callback in ACTIVE_DOWNLOADS:
                ACTIVE_DOWNLOADS[progress_callback]["response"] = response

        status = response.getcode()
        if status == 206 and bytes_written > 0:
            mode = "ab"
            content_range = response.headers.get("Content-Range", "")
            if "/" in content_range:
                try:
                    total_size = int(content_range.split("/")[-1])
                except ValueError:
                    pass
            if total_size <= 0:
                content_length = int(response.headers.get("Content-Length", "0") or "0")
                total_size = bytes_written + content_length
        else:
            mode = "wb"
            bytes_written = 0
            content_length = int(response.headers.get("Content-Length", "0") or "0")
            total_size = content_length

        _emit_download_progress(progress_callback, name, filename, float(bytes_written) / float(total_size) if total_size > 0 else 0.0)

        with open(temp_destination, mode) as output_file:
            while True:
                with DOWNLOADS_LOCK:
                    task = ACTIVE_DOWNLOADS.get(progress_callback)
                    if not task or task.get("paused") or task.get("canceled"):
                        break

                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                
                output_file.write(chunk)
                bytes_written += len(chunk)

                if total_size > 0:
                    progress = min(float(bytes_written) / float(total_size), 1.0)
                    _emit_download_progress(progress_callback, name, filename, progress)

        if total_size > 0 and bytes_written < total_size:
            with DOWNLOADS_LOCK:
                task = ACTIVE_DOWNLOADS.get(progress_callback)
            if not (task and (task.get("paused") or task.get("canceled"))):
                raise Exception("Connection closed prematurely ({0}/{1} bytes downloaded)".format(bytes_written, total_size))

        # Check exit cause
        with DOWNLOADS_LOCK:
            task = ACTIVE_DOWNLOADS.get(progress_callback)
            if task and task.get("paused"):
                _emit_download_paused(progress_callback, name, filename, float(bytes_written) / float(total_size) if total_size > 0 else 0.0)
                return
            elif not task or task.get("canceled"):
                if os.path.exists(temp_destination):
                    try:
                        os.remove(temp_destination)
                    except OSError:
                        pass
                _emit_download_error(progress_callback, name, "Download canceled")
                return

        os.replace(temp_destination, destination)
        _emit_download_progress(progress_callback, name, filename, 1.0)
        _emit_download_complete(progress_callback, name, filename)
        return filename
    except Exception as error:
        with DOWNLOADS_LOCK:
            task = ACTIVE_DOWNLOADS.get(progress_callback)
            if task and task.get("paused"):
                _emit_download_paused(progress_callback, name, filename, float(bytes_written) / float(total_size) if total_size > 0 else 0.0)
                return
        _emit_download_error(progress_callback, name, str(error))
        return ""
    finally:
        with DOWNLOADS_LOCK:
            if progress_callback in ACTIVE_DOWNLOADS:
                del ACTIVE_DOWNLOADS[progress_callback]


def download_model(name, url, progress_callback=None):
    with DOWNLOADS_LOCK:
        if progress_callback in ACTIVE_DOWNLOADS:
            task = ACTIVE_DOWNLOADS[progress_callback]
            if task.get("paused"):
                task["paused"] = False
                task["canceled"] = False
                thread = threading.Thread(target=download_model_thread, args=(name, url, progress_callback))
                thread.daemon = True
                thread.start()
                return True
            return False

        task = {
            "name": name,
            "url": url,
            "request_id": progress_callback,
            "paused": False,
            "canceled": False,
            "response": None
        }
        ACTIVE_DOWNLOADS[progress_callback] = task

    thread = threading.Thread(target=download_model_thread, args=(name, url, progress_callback))
    thread.daemon = True
    thread.start()
    return True


def pause_download(request_id):
    with DOWNLOADS_LOCK:
        task = ACTIVE_DOWNLOADS.get(request_id)
        if task:
            task["paused"] = True
            response = task.get("response")
            if response:
                try:
                    response.close()
                except Exception:
                    pass
            return True
    return False


def cancel_download(request_id):
    with DOWNLOADS_LOCK:
        task = ACTIVE_DOWNLOADS.get(request_id)
        if task:
            task["canceled"] = True
            response = task.get("response")
            if response:
                try:
                    response.close()
                except Exception:
                    pass
            return True
    return False


def get_download_states():
    models_dir = _ensure_models_dir()
    states = {}
    
    if os.path.isdir(models_dir):
        for filename in os.listdir(models_dir):
            if filename.lower().endswith(".gguf"):
                states[filename] = {"status": "ready"}
            elif filename.lower().endswith(".gguf.part"):
                base_name = filename[:-5]
                states[base_name] = {"status": "paused", "size": os.path.getsize(os.path.join(models_dir, filename))}

    with DOWNLOADS_LOCK:
        for request_id, task in ACTIVE_DOWNLOADS.items():
            filename = os.path.basename(task["url"].split("?", 1)[0]) or (task["name"] + ".gguf")
            if task.get("paused"):
                states[filename] = {"status": "paused", "requestId": request_id}
            elif task.get("canceled"):
                pass
            else:
                states[filename] = {"status": "downloading", "requestId": request_id}
                
    return states


LLAMA_CLI_READY = False
LLAMA_CLI_ERROR = None
LLAMA_CLI_DOWNLOADING = False

def _download_and_extract_tar(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=120) as response:
            tar_data = response.read()
            
        with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tar:
            os.makedirs(MODELS_DIR, exist_ok=True)
            extracted_any = False
            for member in tar.getmembers():
                basename = os.path.basename(member.name)
                dest_path = os.path.join(MODELS_DIR, basename)
                if member.isfile():
                    f = tar.extractfile(member)
                    if f:
                        with open(dest_path, "wb") as dest_file:
                            dest_file.write(f.read())
                        if basename in ["llama-cli", "llama-completion"] or basename.endswith(".so") or ".so." in basename:
                            os.chmod(dest_path, 0o755)
                        extracted_any = True
                elif member.islnk() or member.issym():
                    target_basename = os.path.basename(member.linkname)
                    if os.path.lexists(dest_path):
                        try:
                            os.remove(dest_path)
                        except OSError:
                            pass
                    try:
                        os.symlink(target_basename, dest_path)
                    except OSError:
                        pass
            return extracted_any
    except Exception as e:
        log_error("Failed to download and extract tar from {0}: {1}".format(url, e))
        return False


def ensure_llama_cli():
    cli_path = get_llama_cli_path()
    completion_path = get_llama_completion_path()
    if is_binary_working(cli_path) or is_binary_working(completion_path):
        return True
    
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    arch_map = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "x86_64": "x64",
        "amd64": "x64"
    }
    
    target_arch = arch_map.get(machine)
    if not target_arch:
        target_arch = "arm64" if "arm" in machine or "aarch" in machine else "x64"
        
    urls_to_try = []

    # For arm64 (Ubuntu Touch devices like OnePlus 6T), prioritize our verified base ARMv8-A GLIBC 2.31 compatible build
    if target_arch == "arm64":
        urls_to_try.append("https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-arm64.tar.gz")

    # Try resolving latest tag from GitHub API if available
    try:
        import json
        req = urllib.request.Request("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5", headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=10) as response:
            releases = json.loads(response.read().decode())
            expected_asset_suffix = f"-bin-ubuntu-{target_arch}.tar.gz"
            for release in releases:
                r_tag = release.get("tag_name")
                if not r_tag:
                    continue
                assets = release.get("assets", [])
                expected_asset_name = f"llama-{r_tag}{expected_asset_suffix}"
                if any(asset.get("name") == expected_asset_name for asset in assets):
                    api_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{r_tag}/llama-{r_tag}-bin-ubuntu-{target_arch}.tar.gz"
                    if api_url not in urls_to_try:
                        urls_to_try.append(api_url)
                    break
    except Exception as e:
        log_error("Error fetching latest release from GitHub API: {0}".format(e))
        
    if not urls_to_try:
        fallback_url = f"https://github.com/suraj-yadav0/utgpt/releases/download/v0.0.2/llama-compat-bin-ubuntu-{target_arch}.tar.gz"
        urls_to_try.append(fallback_url)

    for url in urls_to_try:
        log_info("Attempting to download llama-cli binary from: {0}".format(url))
        if _download_and_extract_tar(url):
            cli_path = get_llama_cli_path()
            completion_path = get_llama_completion_path()
            if is_binary_working(cli_path) or is_binary_working(completion_path):
                log_info("Successfully downloaded and verified working llama-cli binary.")
                return True
            else:
                log_error("Downloaded binary from {0} failed verification.".format(url))

    return False


def download_llama_cli_in_background():
    global LLAMA_CLI_READY, LLAMA_CLI_ERROR, LLAMA_CLI_DOWNLOADING
    LLAMA_CLI_DOWNLOADING = True
    LLAMA_CLI_ERROR = None
    _send_event("inference_engine_status", {"status": "downloading", "error": ""})
    try:
        if ensure_llama_cli():
            cli_path = get_llama_cli_path()
            completion_path = get_llama_completion_path()
            if is_binary_working(cli_path) or is_binary_working(completion_path):
                LLAMA_CLI_READY = True
            else:
                LLAMA_CLI_READY = False
                LLAMA_CLI_ERROR = "Downloaded binary is incompatible with this device (Illegal instruction / crash)."
        else:
            if not LLAMA_CLI_ERROR:
                LLAMA_CLI_ERROR = "Failed to download llama-cli from GitHub"
    except Exception as e:
        LLAMA_CLI_ERROR = str(e)
    finally:
        LLAMA_CLI_DOWNLOADING = False
        _send_event("inference_engine_status", {
            "status": "ready" if LLAMA_CLI_READY else "error",
            "error": LLAMA_CLI_ERROR or ""
        })

def start_inference_engine_download():
    global LLAMA_CLI_READY, LLAMA_CLI_DOWNLOADING
    if LLAMA_CLI_DOWNLOADING:
        return False
    if LLAMA_CLI_READY:
        return True
    thread = threading.Thread(target=download_llama_cli_in_background)
    thread.daemon = True
    thread.start()
    return True

def get_inference_engine_status():
    global LLAMA_CLI_READY, LLAMA_CLI_ERROR, LLAMA_CLI_DOWNLOADING
    cli_path = get_llama_cli_path()
    completion_path = get_llama_completion_path()
    
    if is_binary_working(cli_path) and is_binary_working(completion_path):
        LLAMA_CLI_READY = True
        status = "ready"
        err_msg = ""
    elif LLAMA_CLI_DOWNLOADING:
        status = "downloading"
        err_msg = ""
    else:
        status = "error" if LLAMA_CLI_ERROR else "not_started"
        err_msg = str(LLAMA_CLI_ERROR) if LLAMA_CLI_ERROR else ""
        
    return {
        "status": status,
        "error": err_msg
    }

def delete_model(filename):
    if not filename:
        return False
    _clear_model_prompt_cache(filename)
    models_dir = os.path.realpath(_ensure_models_dir())
    clean_name = os.path.basename(filename)
    if not clean_name or clean_name in (".", ".."):
        return False
    filepath = os.path.realpath(os.path.join(models_dir, clean_name))
    if not filepath.startswith(models_dir + os.sep):
        return False
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            return True
        except OSError:
            return False
    return False

def clear_partial_download(filename):
    if not filename:
        return False
    models_dir = os.path.realpath(_ensure_models_dir())
    clean_name = os.path.basename(filename)
    if not clean_name or clean_name in (".", ".."):
        return False
    part_filepath = os.path.realpath(os.path.join(models_dir, clean_name + ".part"))
    if not part_filepath.startswith(models_dir + os.sep):
        return False
    if os.path.exists(part_filepath):
        try:
            os.remove(part_filepath)
            return True
        except OSError:
            return False
    return False


DB_PATH = os.path.expanduser("~/.local/share/utgpt.surajyadav/chat_history.db")
DB_INITIALIZED = False
DB_INIT_LOCK = threading.Lock()

@contextmanager
def _get_db_context():
    if not DB_INITIALIZED:
        init_db()
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def init_db():
    global DB_INITIALIZED
    with DB_INIT_LOCK:
        if DB_INITIALIZED:
            return
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        sources TEXT DEFAULT ''
                    )
                """)

                cursor.execute("PRAGMA table_info(messages)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'session_id' not in columns:
                    try:
                        cursor.execute("ALTER TABLE messages ADD COLUMN session_id INTEGER")
                    except sqlite3.OperationalError:
                        pass
                if 'sources' not in columns:
                    try:
                        cursor.execute("ALTER TABLE messages ADD COLUMN sources TEXT DEFAULT ''")
                    except sqlite3.OperationalError:
                        pass

                cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id IS NULL")
                null_count = cursor.fetchone()[0]
                if null_count > 0:
                    cursor.execute("INSERT INTO sessions (title, created_at) VALUES (?, ?)", ("Previous Chat", time.time()))
                    default_session_id = cursor.lastrowid
                    cursor.execute("UPDATE messages SET session_id = ? WHERE session_id IS NULL", (default_session_id,))

                cursor.execute("DELETE FROM messages WHERE text LIKE '%Loading model%' OR text LIKE '%<start_of_turn>%' OR text LIKE '%<|im_start|>%' OR text LIKE '%<|start_header_id|>%'")
            DB_INITIALIZED = True
        finally:
            conn.close()

def get_sessions():
    with _get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]

def get_latest_session_id():
    with _get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None

def delete_session(session_id):
    if not session_id:
        return False
    _clear_session_prompt_cache(session_id)
    with _get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True

def rename_session(session_id, title):
    if not session_id or not title:
        return False
    with _get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (title.strip(), session_id))
        return True

def load_chat_history(session_id=None):
    with _get_db_context() as conn:
        cursor = conn.cursor()
        if not session_id:
            cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return []
            session_id = row[0]

        cursor.execute("SELECT role, text, sources FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
        rows = cursor.fetchall()
        return [{"role": r, "text": t, "sources": s or ""} for r, t, s in rows]

def add_chat_message(role, text, session_id=None, sources=""):
    with _get_db_context() as conn:
        cursor = conn.cursor()
        if not session_id:
            title = text.strip()
            title = " ".join(title.split())
            if len(title) > 30:
                title = title[:27] + "..."
            if not title:
                title = "New Chat"

            cursor.execute("INSERT INTO sessions (title, created_at) VALUES (?, ?)", (title, time.time()))
            session_id = cursor.lastrowid

        cursor.execute("INSERT INTO messages (session_id, role, text, timestamp, sources) VALUES (?, ?, ?, ?, ?)", 
                       (session_id, role, text, time.time(), sources or ""))
        return session_id

def clear_chat_history():
    _clear_all_prompt_cache()
    with _get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM sessions")
        return True

def truncate_session_messages(session_id, keep_count):
    if not session_id:
        return False
    _clear_session_prompt_cache(session_id)
    keep_count = max(0, int(keep_count))
    with _get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM messages
            WHERE session_id = ?
              AND id NOT IN (
                  SELECT id FROM messages
                  WHERE session_id = ?
                  ORDER BY id ASC
                  LIMIT ?
              )
        """, (session_id, session_id, keep_count))
        return True

def get_model_metadata(model_filename):
    # Try local models.json first
    try:
        if os.path.exists(MODELS_JSON_PATH):
            with open(MODELS_JSON_PATH, "r", encoding="utf-8") as f:
                catalog = json.load(f)
                for item in catalog:
                    if item.get("filename") == model_filename:
                        return item
    except Exception:
        pass

    # Fallback to DEFAULT_CATALOG
    for item in DEFAULT_CATALOG:
        if item.get("filename") == model_filename:
            return item

    return None

def get_prompt_and_boundary(model_filename, current_query, recent_history, context_msgs):
    """
    Formats the conversation prompt using model-specific templates,
    integrating real-time context (such as web search) in the system prompt.
    Includes context window budgeting to prevent leakage and out-of-token crashes.
    """
    model_lower = model_filename.lower()
    metadata = get_model_metadata(model_filename)
    
    max_context = 2048
    template_type = None
    if metadata:
        max_context = metadata.get("maxContext", 2048)
        template_type = metadata.get("promptTemplate")

    if not template_type:
        if "base" in model_lower:
            template_type = "default"
        elif "llama-3" in model_lower or "granite" in model_lower:
            template_type = "llama3"
        elif "qwen" in model_lower or "deepseek" in model_lower or "smollm" in model_lower:
            template_type = "chatml"
        elif "gemma" in model_lower:
            template_type = "gemma"
        elif "phi-3" in model_lower:
            template_type = "phi3"
        elif "tinyllama" in model_lower:
            template_type = "zephyr"
        else:
            template_type = "default"

    # Context budgeting: reserve 25% of context window for generation
    safe_token_budget = int(max_context * 0.75)
    query_tokens = len(current_query) // 4
    
    allowed_recent_history = []
    allowed_context_msgs = []
    current_tokens = query_tokens + 50  # buffer for system prompt structure

    # 1. Budget recent chat history first (newest to oldest)
    for msg in reversed(recent_history):
        content = msg.get("content", "")
        msg_tok = len(content) // 4
        if current_tokens + msg_tok < safe_token_budget:
            allowed_recent_history.insert(0, msg)
            current_tokens += msg_tok

    # 2. Budget RAG context next
    for msg in context_msgs:
        text = msg.get("text", "")
        msg_tok = len(text) // 4
        if current_tokens + msg_tok < safe_token_budget:
            allowed_context_msgs.append(msg)
            current_tokens += msg_tok

    context_str = ""
    if allowed_context_msgs:
        for msg in allowed_context_msgs:
            text_cleaned = msg.get("text", "").strip()
            if text_cleaned:
                context_str += f"{text_cleaned}\n\n"

    # Format using resolved template_type
    prompt = ""
    boundary = ""
    if template_type == "llama3":
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n\n{context_str}"
        prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_content}<|eot_id|>"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>"
        prompt += f"<|start_header_id|>user<|end_header_id|>\n\n{current_query}<|eot_id|>"
        prompt += "<|start_header_id|>assistant<|end_header_id|>\n\n"
        boundary = "<|start_header_id|>assistant<|end_header_id|>\n\n"

    elif template_type == "chatml":
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n\n{context_str}"
        prompt = f"<|im_start|>system\n{system_content}<|im_end|>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{current_query}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        boundary = "<|im_start|>assistant\n"

    elif template_type == "zephyr":
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n\n{context_str}"
        prompt = f"<|system|>\n{system_content}</s>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|{role}|>\n{content}</s>\n"
        prompt += f"<|user|>\n{current_query}</s>\n"
        prompt += "<|assistant|>\n"
        boundary = "<|assistant|>\n"

    elif template_type == "gemma":
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n{context_str}"
        prompt = "<bos>"
        prompt += f"<start_of_turn>system\n{system_content}<end_of_turn>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<start_of_turn>{role}\n{content}<end_of_turn>\n"
        prompt += f"<start_of_turn>user\n{current_query}<end_of_turn>\n"
        prompt += "<start_of_turn>assistant\n"
        boundary = "<start_of_turn>assistant\n"

    elif template_type == "phi3":
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n{context_str}"
        prompt = "<s>"
        prompt += f"<|system|>\n{system_content}<|end|>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|{role}|>\n{content}<|end|>\n"
        prompt += f"<|user|>\n{current_query}<|end|>\n"
        prompt += "<|assistant|>\n"
        boundary = "<|assistant|>\n"

    else:
        prompt = ""
        if context_str:
            prompt += f"System: {context_str}\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            prompt += f"{role}: {content}\n"
        prompt += f"User: {current_query}\nAssistant:"
        boundary = "Assistant:"

    if "deepseek-r1" in model_lower:
        prompt += "<think>\n"

    return prompt, boundary

def run_inference(model_filename, user_message, temperature, max_tokens, *args):
    defaults = [4, 2048, "auto", "f16", False, None, None, ""]
    if len(args) == 2 and (callable(args[0]) or (isinstance(args[0], str) and not str(args[0]).isdigit())):
        threads, ctx_size, flash_attn, kv_cache, web_search_enabled = defaults[:5]
        token_callback, done_callback = args
        session_id = defaults[7]
    elif len(args) == 3 and (callable(args[0]) or (isinstance(args[0], str) and not str(args[0]).isdigit())):
        threads, ctx_size, flash_attn, kv_cache, web_search_enabled = defaults[:5]
        token_callback, done_callback, session_id = args
    else:
        values = list(args) + defaults[len(args):]
        threads, ctx_size, flash_attn, kv_cache, web_search_enabled, token_callback, done_callback, session_id = values[:8]

    try:
        threads = int(threads)
    except (ValueError, TypeError):
        threads = 4
    try:
        ctx_size = int(ctx_size)
    except (ValueError, TypeError):
        ctx_size = 2048
    session_id = str(session_id or "").strip()
    if session_id in ("null", "undefined"):
        session_id = ""
    flash_attn = str(flash_attn or "auto")
    kv_cache = str(kv_cache or "f16")
    web_search_val = web_search_enabled
    web_search_str = str(web_search_val).lower().strip()
    if web_search_str in ("auto", "smart"):
        web_search_mode = "auto"
    elif web_search_str in ("true", "1", "on"):
        web_search_mode = "on"
    else:
        web_search_mode = "off"

    log_info("Entering run_inference with model={0}, threads={1}, ctx_size={2}, flash_attn={3}, web_search={4}, session_id={5}".format(
        model_filename, threads, ctx_size, flash_attn, web_search_val, session_id or "none"))
    
    if isinstance(user_message, list) and len(user_message) > 0:
        current_query = user_message[-1].get("content", "")
        recent_history = user_message[-5:-1] if len(user_message) > 1 else []
    else:
        current_query = str(user_message)
        recent_history = []

    model_path = os.path.join(_ensure_models_dir(), model_filename)

    if not model_filename:
        log_error("No model selected")
        _emit_done(done_callback, ok=False, error_message="No model selected.")
        return False

    if not os.path.exists(model_path):
        log_error("Model file not found at {0}".format(model_path))
        _emit_done(done_callback, ok=False, error_message="Model file not found: {0}".format(model_filename))
        return False

    cli_path = get_llama_completion_path() if os.path.exists(get_llama_completion_path()) else get_llama_cli_path()
    if not os.path.exists(cli_path):
        global LLAMA_CLI_ERROR, LLAMA_CLI_DOWNLOADING
        if LLAMA_CLI_ERROR:
            error_msg = "Missing inference engine. Downloader error: " + str(LLAMA_CLI_ERROR)
        elif LLAMA_CLI_DOWNLOADING:
            error_msg = "Inference engine is still downloading. Please try again in a moment."
        else:
            error_msg = "Inference engine has not been downloaded yet. Please go to Settings to download it."
        log_error("inference engine not found: {0}".format(error_msg))
        _emit_done(done_callback, ok=False, error_message=error_msg)
        return False

    cancel_token = threading.Event()
    with INFERENCE_LOCK:
        ACTIVE_TOKENS.add(cancel_token)

    def worker():
        process = None
        try:
            if cancel_token.is_set():
                _emit_done(done_callback, ok=False, error_message="Inference canceled")
                return

            web_context_msgs = []
            should_search = False
            if web_search_mode == "on":
                should_search = True
            elif web_search_mode == "auto":
                should_search = should_search_web(current_query)

            if should_search:
                search_query = clean_search_query(current_query)
                log_info("Performing web search (mode={0}) for query: {1} (raw: {2})".format(web_search_mode, search_query, current_query))
                _emit_search_status(token_callback, "started", query=search_query)
                try:
                    search_results = search_web(search_query, num_results=3)
                    if search_results:
                        sources = [{"title": res.get("title", ""), "url": res.get("url", "")} for res in search_results]
                        _emit_search_status(token_callback, "found", query=search_query, count=len(sources), sources=sources)
                        if token_callback and not callable(token_callback):
                            _send_event("web_search_sources", {
                                "requestId": str(token_callback),
                                "sources": sources
                            })
                        formatted_web = (
                            "Real-time Web Search Results:\n"
                            "Answer the user query accurately using these search results where relevant.\n\n"
                        )
                        for idx, res in enumerate(search_results, 1):
                            title = res.get('title', '')
                            snippet = res.get('snippet', '')
                            url = res.get('url', '')
                            formatted_web += f"[{idx}] Title: {title}\n    Snippet: {snippet}\n    Source: {url}\n\n"
                        web_context_msgs = [{"role": "system", "text": formatted_web}]
                    else:
                        log_info("Web search returned no results, relying on model knowledge.")
                finally:
                    _emit_search_status(token_callback, "finished")

            if cancel_token.is_set():
                _emit_done(done_callback, ok=False, error_message="Inference canceled")
                return

            context_msgs = web_context_msgs
            prompt, boundary = get_prompt_and_boundary(model_filename, current_query, recent_history, context_msgs)
            log_debug("Constructed prompt: {0}".format(repr(prompt)))

            is_completion = "llama-completion" in cli_path
            log_info("Launching inference engine: {0}".format(cli_path))

            # Determine template type to pass correct reverse prompts/stop tokens
            metadata = get_model_metadata(model_filename)
            template_type = None
            if metadata:
                template_type = metadata.get("promptTemplate")
            if not template_type:
                model_lower = model_filename.lower()
                if "base" in model_lower:
                    template_type = "default"
                elif "llama-3" in model_lower or "granite" in model_lower:
                    template_type = "llama3"
                elif "qwen" in model_lower or "deepseek" in model_lower or "smollm" in model_lower:
                    template_type = "chatml"
                elif "gemma" in model_lower:
                    template_type = "gemma"
                elif "phi-3" in model_lower:
                    template_type = "phi3"
                elif "tinyllama" in model_lower:
                    template_type = "zephyr"

            stop_tokens = []
            if template_type == "llama3":
                stop_tokens = ["<|eot_id|>", "<|start_header_id|>"]
            elif template_type == "chatml":
                stop_tokens = ["<|im_end|>", "<|im_start|>", "</im_end>"]
            elif template_type == "zephyr":
                stop_tokens = ["</s>", "<|user|>"]
            elif template_type == "gemma":
                stop_tokens = ["<end_of_turn>", "<start_of_turn>"]
            elif template_type == "phi3":
                stop_tokens = ["<|end|>", "<|user|>"]
            elif template_type == "default":
                stop_tokens = ["\nUser:", "\nAssistant:", "\nSystem:"]

            batch_size = min(512, max(32, ctx_size))
            ubatch_size = min(256, batch_size)
            additional_args = [
                "-t", str(int(threads)),
                "-tb", str(int(threads)),
                "-c", str(int(ctx_size)),
                "-b", str(batch_size),
                "-ub", str(ubatch_size),
                "-fa", str(flash_attn)
            ]
            if kv_cache in ["q8_0", "q4_0"]:
                additional_args.extend(["-ctk", kv_cache, "-ctv", kv_cache])
            for token in stop_tokens:
                additional_args.extend(["-r", token])

            if is_completion and session_id:
                cache_dir = _ensure_prompt_cache_dir()
                safe_session = re.sub(r'[^a-zA-Z0-9_-]', '_', str(session_id))
                safe_model = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(os.path.basename(model_filename))[0])
                cache_file = os.path.join(cache_dir, "{0}_{1}.bin".format(safe_session, safe_model))
                if os.path.exists(cache_file) and os.path.getsize(cache_file) == 0:
                    try:
                        os.remove(cache_file)
                    except OSError:
                        pass
                additional_args.extend(["--prompt-cache", cache_file, "--prompt-cache-all"])
            
            if is_completion:
                args = [
                    cli_path,
                    "-m", model_path,
                    "-p", prompt,
                    "--temp", str(float(temperature)),
                    "-n", str(int(max_tokens)),
                    "-no-cnv",
                    "--no-display-prompt",
                    "--simple-io"
                ]
            else:
                args = [
                    cli_path,
                    "-m", model_path,
                    "-p", prompt,
                    "--temp", str(float(temperature)),
                    "-n", str(int(max_tokens)),
                    "--no-display-prompt",
                    "-st",
                    "--simple-io"
                ]
            args.extend(additional_args)

            env = os.environ.copy()
            ld_library_paths = [os.path.join(APP_DIR, "assets")]
            if "LD_LIBRARY_PATH" in env:
                env["LD_LIBRARY_PATH"] = os.path.pathsep.join(ld_library_paths + [env["LD_LIBRARY_PATH"]])
            else:
                env["LD_LIBRARY_PATH"] = os.path.pathsep.join(ld_library_paths)

            if cancel_token.is_set():
                _emit_done(done_callback, ok=False, error_message="Inference canceled")
                return

            preexec = _preexec_set_pdeathsig if sys.platform.startswith("linux") else None
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                env=env,
                preexec_fn=preexec,
                encoding="utf-8",
                errors="replace"
            )
            _register_process(process)
            log_info("Inference engine launched successfully, starting stdout read loop")

            stderr_lines = []
            def log_stderr():
                try:
                    for line in process.stderr:
                        stderr_lines.append(line)
                except Exception:
                    pass

            stderr_thread = threading.Thread(target=log_stderr)
            stderr_thread.daemon = True
            stderr_thread.start()

            output_buffer = ""
            has_emitted_content = False

            if "deepseek-r1" in model_filename.lower():
                _emit_token(token_callback, "<think>\n")
                has_emitted_content = True

            chunk_buffer = ""
            while True:
                if cancel_token.is_set():
                    break
                char = process.stdout.read(1)
                if not char:
                    break

                output_buffer += char

                if len(output_buffer) > 20:
                    safe_char = output_buffer[0]
                    output_buffer = output_buffer[1:]
                    if not has_emitted_content:
                        if safe_char.strip() == "":
                            continue
                        has_emitted_content = True
                    chunk_buffer += safe_char
                    should_emit = (
                        len(chunk_buffer) >= 20 or
                        safe_char in ("\n", "\r") or
                        (safe_char in (".", "!", "?", ":", ";") and len(chunk_buffer) >= 6) or
                        (safe_char in (" ", "\t") and len(chunk_buffer) >= 12)
                    )
                    if should_emit:
                        _emit_token(token_callback, chunk_buffer)
                        chunk_buffer = ""

            if not cancel_token.is_set():
                if chunk_buffer:
                    _emit_token(token_callback, chunk_buffer)
                    chunk_buffer = ""

                if output_buffer:
                    if not has_emitted_content:
                        output_buffer = output_buffer.lstrip()
                    for marker in (" [end of text]", "[end of text]", "<|im_end|>", "</im_end>", "<|eot_id|>", "<end_of_turn>", "<|end|>", "</s>"):
                        output_buffer = output_buffer.replace(marker, "")
                    if output_buffer:
                        log_debug("Emitting remaining buffer content: {0}".format(repr(output_buffer)))
                        _emit_token(token_callback, output_buffer)

            log_debug("Waiting for process to exit")
            exit_code = process.wait()
            stderr_thread.join(timeout=1.0)
            log_info("Process exited with code {0}".format(exit_code))
            if exit_code != 0:
                error_msg = "".join(stderr_lines).strip()
                if not error_msg:
                    error_msg = "Process exited with status {0}".format(exit_code)
                _emit_done(done_callback, ok=False, error_message=error_msg)
                return

            _emit_done(done_callback, ok=True, error_message="")
        except Exception as error:  # pragma: no cover - exercised from app runtime
            log_error("Exception in run_inference: {0}".format(error))
            _terminate_process(process)
            _emit_done(done_callback, ok=False, error_message=str(error))
        finally:
            with INFERENCE_LOCK:
                ACTIVE_TOKENS.discard(cancel_token)
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            _unregister_process(process)

    thread = threading.Thread(target=worker)
    thread.daemon = True
    thread.start()
    return True


def stop_all_inference():
    with INFERENCE_LOCK:
        for token in ACTIVE_TOKENS:
            token.set()
        processes = list(ACTIVE_PROCESSES)

    for process in processes:
        _terminate_process(process)

atexit.register(stop_all_inference)


def import_local_model_thread(file_url, request_id):
    try:
        parsed = urllib.parse.urlparse(file_url)
        source_path = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else file_url

        if not os.path.exists(source_path):
            log_error("Import local model failed: source path '{0}' does not exist (original url: '{1}')".format(source_path, file_url))
            _send_event("import_error", {
                "requestId": request_id,
                "error": "Source file does not exist at: {0}".format(source_path)
            })
            return

        if not source_path.lower().endswith(".gguf"):
            _send_event("import_error", {
                "requestId": request_id,
                "error": "Only .gguf files are supported"
            })
            return

        filename = os.path.basename(source_path)
        if filename.lower().startswith("mmproj"):
            _send_event("import_error", {
                "requestId": request_id,
                "error": "Multimodal projector files (mmproj-*.gguf) cannot be loaded as standalone language models. Please download an instruct or chat model."
            })
            return
        dest_dir = _ensure_models_dir()
        dest_path = os.path.join(dest_dir, filename)

        if os.path.exists(dest_path):
            _send_event("import_error", {
                "requestId": request_id,
                "error": "Model with this filename already exists in application storage"
            })
            return

        total_size = os.path.getsize(source_path)

        _send_event("import_start", {
            "requestId": request_id,
            "filename": filename,
            "totalSize": total_size
        })

        shutil.copyfile(source_path, dest_path)

        # Cleanup if the file is in incoming/temp directory (from Content Hub)
        is_incoming = "incoming" in source_path or "/tmp/" in source_path
        if is_incoming:
            try:
                os.remove(source_path)
            except OSError:
                pass

        _send_event("import_complete", {
            "requestId": request_id,
            "filename": filename
        })

    except Exception as e:
        log_error("Error importing model: " + str(e))
        _send_event("import_error", {
            "requestId": request_id,
            "error": str(e)
        })


def import_local_model(file_url):
    request_id = "import-" + str(int(time.time()))
    thread = threading.Thread(
        target=import_local_model_thread,
        args=(file_url, request_id),
        daemon=True
    )
    thread.start()
    return request_id


def get_release_notes():
    import json
    rel_notes_path = os.path.join(APP_DIR, "assets", "release_notes.json")
    if os.path.isfile(rel_notes_path):
        try:
            with open(rel_notes_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_error("Failed to load release notes: {0}".format(e))

    return {
        "version": "0.1.0",
        "date": "2026-07-26",
        "title": "What's New in UTGPT",
        "subtitle": "Version 0.1.0 Release Notes",
        "features": []
    }


def initialize():
    _ensure_models_dir()
    init_db()
    global LLAMA_CLI_READY
    
    cli_path = get_llama_cli_path()
    completion_path = get_llama_completion_path()
    if is_binary_working(cli_path) and is_binary_working(completion_path):
        LLAMA_CLI_READY = True
    else:
        LLAMA_CLI_READY = False
        
    is_desktop = True
    if os.environ.get("APP_ID") or os.environ.get("LOMIRI_APP_LAUNCH_ENV"):
        is_desktop = False

    rel_notes = get_release_notes()
    app_version = rel_notes.get("version", "0.1.0")

    return {
        "ready": True,
        "modelsDir": MODELS_DIR,
        "llamaCliPath": get_llama_cli_path(),
        "llamaCliReady": LLAMA_CLI_READY,
        "debug": DEBUG_MODE,
        "isDesktop": is_desktop,
        "version": app_version,
        "releaseNotes": rel_notes
    }


