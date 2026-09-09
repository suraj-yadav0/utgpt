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
import platform
import tarfile
import io
import time
import sys
import shutil
import json
import sqlite3
from html.parser import HTMLParser

DEBUG_MODE = os.environ.get("UTGPT_DEBUG", "").lower() in ("1", "true", "yes")

def log_debug(msg):
    if DEBUG_MODE:
        print("UTGPT_LOG [DEBUG]: {0}".format(msg), file=sys.stderr, flush=True)

def log_info(msg):
    print("UTGPT_LOG [INFO]: {0}".format(msg), file=sys.stderr, flush=True)

def log_warn(msg):
    print("UTGPT_LOG [WARN]: {0}".format(msg), file=sys.stderr, flush=True)

def log_error(msg):
    print("UTGPT_LOG [ERROR]: {0}".format(msg), file=sys.stderr, flush=True)

def _urlopen(req, timeout=60):
    try:
        import ssl
        context = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=context)
    except Exception:
        return urllib.request.urlopen(req, timeout=timeout)


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
            self.current_result = {"url": attrs_dict.get("href")}
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


def search_web(query, num_results=3):
    """
    Performs a privacy-focused DuckDuckGo Lite search using standard Python libraries,
    returning structured web titles, snippets, and URLs.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with _urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
            parser = DDGLiteParser()
            parser.feed(html)
            return parser.results[:num_results]
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
ATTACHMENTS_DIR = os.path.expanduser("~/.local/share/utgpt.surajyadav/attachments")
LLAMA_CLI_PATH_BUNDLED = os.path.join(APP_DIR, "assets", "llama-cli")
LLAMA_CLI_PATH_WRITABLE = os.path.join(MODELS_DIR, "llama-cli")
LLAMA_COMPLETION_PATH_BUNDLED = os.path.join(APP_DIR, "assets", "llama-completion")
LLAMA_COMPLETION_PATH_WRITABLE = os.path.join(MODELS_DIR, "llama-completion")

def is_binary_working(path):
    if not os.path.exists(path):
        return False
    try:
        env = os.environ.copy()
        ld_library_paths = [MODELS_DIR, os.path.join(APP_DIR, "assets")]
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

TESSERACT_PATH_BUNDLED = os.path.join(APP_DIR, "assets", "tesseract")
TESSERACT_PATH_WRITABLE = os.path.join(MODELS_DIR, "tesseract")
TESSDATA_DIR_BUNDLED = os.path.join(APP_DIR, "assets", "tessdata")
TESSDATA_DIR_WRITABLE = os.path.join(MODELS_DIR, "tessdata")

TESSERACT_DOWNLOADING = False
TESSERACT_READY = False
TESSERACT_ERROR = None
_OCR_DL_LOCK = threading.Lock()

def _tessdata_has_lang(tessdata_path, lang="eng"):
    # True when the traineddata file is there and looks real.
    if not tessdata_path or not os.path.isdir(tessdata_path):
        return False
    trained = os.path.join(tessdata_path, lang + ".traineddata")
    try:
        return os.path.isfile(trained) and os.path.getsize(trained) > 100000
    except OSError:
        return False


def _tesseract_env(tessdata_path=None):
    # TESSDATA_PREFIX wants the parent of tessdata/, not tessdata/ itself.
    env = os.environ.copy()
    if tessdata_path and os.path.isdir(tessdata_path):
        parent = os.path.dirname(os.path.abspath(tessdata_path))
        env["TESSDATA_PREFIX"] = parent
    return env


def is_tesseract_working(bin_path, tessdata_path=None, lang="eng"):
    if not bin_path or not os.path.exists(bin_path):
        return False
    try:
        env = _tesseract_env(tessdata_path)
        res = subprocess.run([bin_path, "--version"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
        if res.returncode != 0:
            return False
        # --version passes even without traineddata, so check the language
        # data loads too. Otherwise OCR dies later with "Failed loading language".
        if tessdata_path and not _tessdata_has_lang(tessdata_path, lang):
            return False
        args = [bin_path, "--list-langs"]
        if tessdata_path:
            args += ["--tessdata-dir", tessdata_path]
        res = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if res.returncode == 0:
            out = (res.stdout or b"").decode("utf-8", errors="ignore")
            if lang in [l.strip() for l in out.splitlines()]:
                return True
            # --list-langs unsupported or lang missing: fall back to file check
            return _tessdata_has_lang(tessdata_path, lang) if tessdata_path else True
        return _tessdata_has_lang(tessdata_path, lang) if tessdata_path else True
    except Exception:
        return False

DOWNLOAD_CHUNK_SIZE = 64 * 1024
INFERENCE_LOCK = threading.Lock()
ACTIVE_PROCESSES = set()

DEFAULT_CATALOG = [
    {
        "name": "SmolLM2-1.7B",
        "filename": "smollm2-1.7b-instruct-q4_k_m.gguf",
        "size": "~1.0 GB",
        "description": "Fast general chat",
        "url": "https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF/resolve/main/smollm2-1.7b-instruct-q4_k_m.gguf",
        "developer": "Hugging Face",
        "context": "8,192 tokens",
        "maxContext": 8192,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Fast general chat, low resource devices",
        "promptTemplate": "chatml"
    },
    {
        "name": "Qwen2.5-1.5B",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size": "~1.0 GB",
        "description": "Great multilingual",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "developer": "Alibaba Group",
        "context": "32,768 tokens",
        "maxContext": 32768,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Excellent multilingual capabilities, coding & reasoning",
        "promptTemplate": "chatml"
    },
    {
        "name": "DeepSeek-R1-Distill-Qwen-1.5B",
        "filename": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "size": "~1.1 GB",
        "description": "Reasoning assistant (thinking step)",
        "url": "https://huggingface.co/unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "developer": "DeepSeek",
        "context": "32,768 tokens",
        "maxContext": 32768,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Distilled reasoning model, thinking step visualization, math/logic",
        "promptTemplate": "chatml"
    },
    {
        "name": "Llama-3.2-1B",
        "filename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size": "~800 MB",
        "description": "Ultra-fast Meta assistant",
        "url": "https://huggingface.co/unsloth/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "developer": "Meta",
        "context": "128,000 tokens",
        "maxContext": 128000,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Ultra-fast assistant, agentic tasks, long contexts",
        "promptTemplate": "llama3"
    },
    {
        "name": "Llama-3.2-3B",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size": "~2.0 GB",
        "description": "Meta's smart assistant",
        "url": "https://huggingface.co/unsloth/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "developer": "Meta",
        "context": "128,000 tokens",
        "maxContext": 128000,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Smart general assistant, high quality logic & reasoning",
        "promptTemplate": "llama3"
    },
    {
        "name": "Gemma-2-2B",
        "filename": "gemma-2-2b-it-Q4_K_M.gguf",
        "size": "~1.7 GB",
        "description": "Google's lightweight assistant",
        "url": "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
        "developer": "Google",
        "context": "8,192 tokens",
        "maxContext": 8192,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Lightweight high-quality chatting, instruction following",
        "promptTemplate": "gemma"
    },
    {
        "name": "Phi-3-mini-4K",
        "filename": "Phi-3-mini-4k-instruct-Q4_K_M.gguf",
        "size": "~2.2 GB",
        "description": "Microsoft reasoning model",
        "url": "https://huggingface.co/bartowski/Phi-3-mini-4k-instruct-GGUF/resolve/main/Phi-3-mini-4k-instruct-Q4_K_M.gguf",
        "developer": "Microsoft",
        "context": "4,096 tokens",
        "maxContext": 4096,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Reasoning, logical tasks, math and coding",
        "promptTemplate": "phi3"
    },
    {
        "name": "Granite-3.0-2B-Instruct",
        "filename": "granite-3.0-2b-instruct-Q4_K_M.gguf",
        "size": "~1.3 GB",
        "description": "IBM's lightweight instruction model",
        "url": "https://huggingface.co/bartowski/granite-3.0-2b-instruct-GGUF/resolve/main/granite-3.0-2b-instruct-Q4_K_M.gguf",
        "developer": "IBM",
        "context": "4,096 tokens",
        "maxContext": 4096,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Enterprise tasks, translation, coding",
        "promptTemplate": "llama3"
    },
    {
        "name": "Qwen2.5-0.5B",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size": "~390 MB",
        "description": "Ultra-lightweight multilingual assistant",
        "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "developer": "Alibaba Group",
        "context": "32,768 tokens",
        "maxContext": 32768,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Extremely lightweight, ultra-fast generation, low RAM usage",
        "promptTemplate": "chatml"
    },
    {
        "name": "TinyLlama-1.1B",
        "filename": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "size": "~700 MB",
        "description": "Fastest, basic",
        "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "developer": "TinyLlama Project",
        "context": "2,048 tokens",
        "maxContext": 2048,
        "quant": "Q4_K_M (4-bit)",
        "usage": "Extremely fast, simple chats on low-spec hardware",
        "promptTemplate": "zephyr"
    }
]

import json

def get_total_ram_gb():
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


def _emit_done(callback_ref, ok=True, error_message=""):
    if callable(callback_ref):
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
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


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
    stats = os.statvfs(models_dir)
    free_bytes = stats.f_bavail * stats.f_frsize
    free_gb = free_bytes / float(1024 ** 3)
    return "{0:.1f} GB free".format(free_gb)


def download_model_thread(name, url, progress_callback):
    models_dir = _ensure_models_dir()
    filename = os.path.basename(url.split("?", 1)[0]) or (name + ".gguf")
    destination = os.path.join(models_dir, filename)
    temp_destination = destination + ".part"

    bytes_written = 0
    if os.path.exists(temp_destination):
        bytes_written = os.path.getsize(temp_destination)

    total_size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
        
        try:
            if bytes_written > 0:
                request.add_header("Range", "bytes={0}-".format(bytes_written))
            response = _urlopen(request, timeout=60)
        except urllib.error.HTTPError as http_err:
            if bytes_written > 0:
                bytes_written = 0
                request = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
                response = _urlopen(request, timeout=60)
            else:
                raise http_err
        except Exception as err:
            if bytes_written > 0:
                bytes_written = 0
                request = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
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
    models_dir = _ensure_models_dir()
    filepath = os.path.join(models_dir, filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            return True
        except OSError:
            return False
    return False

def clear_partial_download(filename):
    models_dir = _ensure_models_dir()
    part_filepath = os.path.join(models_dir, filename + ".part")
    if os.path.exists(part_filepath):
        try:
            os.remove(part_filepath)
            return True
        except OSError:
            return False
    return False


DB_PATH = os.path.expanduser("~/.local/share/utgpt.surajyadav/chat_history.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
            timestamp REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            char_count INTEGER,
            created_at REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            session_id INTEGER,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
        )
    """)
    
    # Check if 'session_id' column exists in messages table
    cursor.execute("PRAGMA table_info(messages)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'session_id' not in columns:
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN session_id INTEGER")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Assign orphaned messages (from previous single-chat versions) to a default session
    cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id IS NULL")
    null_count = cursor.fetchone()[0]
    if null_count > 0:
        cursor.execute("INSERT INTO sessions (title, created_at) VALUES (?, ?)", ("Previous Chat", time.time()))
        default_session_id = cursor.lastrowid
        cursor.execute("UPDATE messages SET session_id = ? WHERE session_id IS NULL", (default_session_id,))
        conn.commit()

    # Prune corrupt entries from previous session implementations
    cursor.execute("DELETE FROM messages WHERE text LIKE '%Loading model%' OR text LIKE '%<start_of_turn>%' OR text LIKE '%<|im_start|>%' OR text LIKE '%<|start_header_id|>%'")
    conn.commit()
    conn.close()

def get_sessions():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]

def get_latest_session_id():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def delete_session(session_id):
    init_db()
    if session_id is None or session_id == "" or session_id == 0:
        return False
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return True

def rename_session(session_id, title):
    init_db()
    if session_id is None or session_id == "" or session_id == 0 or not title:
        return False
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (title.strip(), session_id))
    conn.commit()
    conn.close()
    return True

def load_chat_history(session_id=None):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # If no session_id provided, default to the latest session (if any)
    if session_id is None or session_id == "" or session_id == 0:
        cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            conn.close()
            return []
        session_id = row[0]

    cursor.execute("SELECT role, text FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r, "text": t} for r, t in rows]

def add_chat_message(role, text, session_id=None):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Auto-create session if none active/provided
    if session_id is None or session_id == "" or session_id == 0:
        title = text.strip()
        title = " ".join(title.split())  # Collapse whitespaces/newlines
        if len(title) > 30:
            title = title[:27] + "..."
        if not title:
            title = "New Chat"
            
        cursor.execute("INSERT INTO sessions (title, created_at) VALUES (?, ?)", (title, time.time()))
        session_id = cursor.lastrowid
        
    cursor.execute("INSERT INTO messages (session_id, role, text, timestamp) VALUES (?, ?, ?, ?)", 
                   (session_id, role, text, time.time()))
    conn.commit()
    conn.close()
    return session_id

def clear_chat_history():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    return True

def truncate_session_messages(session_id, keep_count):
    if not session_id:
        return False
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cursor.fetchall()
    
    if len(rows) > keep_count:
        ids_to_delete = [row[0] for row in rows[keep_count:]]
        placeholders = ",".join("?" for _ in ids_to_delete)
        cursor.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", ids_to_delete)
        conn.commit()
        
    conn.close()
    return True

def retrieve_relevant_context(query, exclude_texts, limit=3):
    init_db()
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "and", "or", 
        "who", "what", "how", "why", "where", "you", "me", "my", "i", "do", "does", 
        "did", "have", "has", "had", "for", "with", "this", "that", "it", "he", "she", 
        "they", "we", "about", "your", "mine", "am", "go", "get", "can", "could", "would",
        "here", "there", "when", "then", "which", "whoever", "whose", "whom"
    }
    
    # Extract keywords
    words = [w.strip("?,.:;!\"'()[]{}<>-_+=|\\/`~@#$%^&*").lower() for w in query.split()]
    keywords = [w for w in words if w and w not in stopwords and len(w) > 2]
    
    if not keywords:
        return []
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    matches = {}
    for kw in keywords:
        cursor.execute("SELECT id, role, text, timestamp FROM messages WHERE text LIKE ?", (f"%{kw}%",))
        for row in cursor.fetchall():
            msg_id, role, text, timestamp = row
            if text in exclude_texts:
                continue
            if msg_id not in matches:
                matches[msg_id] = {
                    "id": msg_id,
                    "role": role,
                    "text": text,
                    "timestamp": timestamp,
                    "score": 0
                }
            matches[msg_id]["score"] += 1
            
    conn.close()
    
    if not matches:
        return []
        
    sorted_matches = sorted(matches.values(), key=lambda x: (x["score"], x["timestamp"]), reverse=True)
    relevant_msgs = sorted_matches[:limit]
    relevant_msgs = sorted(relevant_msgs, key=lambda x: x["timestamp"])
    
    return [{"role": m["role"], "text": m["text"]} for m in relevant_msgs]

def _extract_pdf_text(file_path):
    try:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        if text_parts:
            return "\n".join(text_parts)
    except Exception:
        pass

    try:
        import fitz
        doc = fitz.open(file_path)
        text_parts = [page.get_text() for page in doc]
        if text_parts:
            return "\n".join(text_parts)
    except Exception:
        pass

    import zlib
    import re
    text_parts = []
    try:
        with open(file_path, "rb") as f:
            content = f.read()

        stream_matches = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", content, re.DOTALL)
        for raw_stream in stream_matches:
            decompressed = None
            try:
                decompressed = zlib.decompress(raw_stream)
            except Exception:
                decompressed = raw_stream

            if b"BT" in decompressed and b"ET" in decompressed:
                text_matches = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
                if text_matches:
                    for tm in text_matches:
                        text_parts.append(tm.decode("utf-8", errors="ignore"))

                tj_matches = re.findall(rb"\[(.*?)\]\s*TJ", decompressed, re.DOTALL)
                for tjm in tj_matches:
                    sub_strings = re.findall(rb"\((.*?)\)", tjm)
                    for ss in sub_strings:
                        text_parts.append(ss.decode("utf-8", errors="ignore"))
    except Exception as e:
        log_error(f"Fallback PDF parsing error: {e}")

    result = " ".join(text_parts).strip()
    return result if result else "[PDF Document attached]"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".ico", ".svg"}

def _get_tesseract_path_and_tessdata(lang="eng"):
    # Only trust a tessdata dir that actually has the traineddata.
    tesseract_candidates = [
        TESSERACT_PATH_WRITABLE,
        TESSERACT_PATH_BUNDLED,
        os.path.join(APP_DIR, "assets", "bin", "tesseract"),
        os.path.join(APP_DIR, "bin", "tesseract"),
        shutil.which("tesseract"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract"
    ]
    tesseract_bin = None
    for cand in tesseract_candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            tesseract_bin = cand
            break

    tessdata_candidates = [
        TESSDATA_DIR_WRITABLE,
        TESSDATA_DIR_BUNDLED,
        os.path.join(APP_DIR, "tessdata"),
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tessdata",
        "/usr/local/share/tessdata"
    ]
    tessdata_dir = None
    fallback_dir = None
    for cand in tessdata_candidates:
        if cand and os.path.isdir(cand):
            if fallback_dir is None:
                fallback_dir = cand
            if _tessdata_has_lang(cand, lang):
                tessdata_dir = cand
                break

    # Prefer a dir with the language data; fall back to the first dir
    # around so callers can report "traineddata missing" precisely.
    return tesseract_bin, tessdata_dir or fallback_dir

def ensure_tesseract_ocr():
    """Ensures a working static Tesseract OCR binary and English traineddata exist."""
    global TESSERACT_READY, TESSERACT_ERROR
    tesseract_bin, tessdata_dir = _get_tesseract_path_and_tessdata()
    if tesseract_bin and is_tesseract_working(tesseract_bin, tessdata_dir):
        TESSERACT_READY = True
        TESSERACT_ERROR = None
        return True

    # Log what's missing so the UI can say something useful.
    if not tesseract_bin:
        log_info("No working Tesseract binary found; will download a static build.")
    elif not tessdata_dir or not _tessdata_has_lang(tessdata_dir):
        log_info("Tesseract binary present but eng.traineddata missing; will fetch traineddata.")

    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(TESSDATA_DIR_WRITABLE, exist_ok=True)

    machine = platform.machine().lower()
    target_arch = "aarch64" if ("arm" in machine or "aarch" in machine) else "x86_64"

    bin_url = f"https://github.com/DanielMYT/tesseract-static/releases/download/tesseract-5.5.3/tesseract.{target_arch}"
    tessdata_url = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata"

    if not os.path.exists(TESSERACT_PATH_WRITABLE) or not os.access(TESSERACT_PATH_WRITABLE, os.X_OK):
        log_info(f"Downloading static Tesseract OCR binary ({target_arch}) from {bin_url}...")
        try:
            req = urllib.request.Request(bin_url, headers={"User-Agent": "UTGPT/0.1"})
            with _urlopen(req, timeout=120) as resp, open(TESSERACT_PATH_WRITABLE, "wb") as out:
                shutil.copyfileobj(resp, out)
            os.chmod(TESSERACT_PATH_WRITABLE, 0o755)
            if os.path.getsize(TESSERACT_PATH_WRITABLE) < 1000000:
                raise Exception("Downloaded binary is suspiciously small ({0} bytes); likely an error page.".format(os.path.getsize(TESSERACT_PATH_WRITABLE)))
        except Exception as e:
            log_error(f"Failed to download Tesseract binary: {e}")
            TESSERACT_ERROR = f"Binary download error: {e}"
            try:
                if os.path.exists(TESSERACT_PATH_WRITABLE):
                    os.remove(TESSERACT_PATH_WRITABLE)
            except OSError:
                pass
            return False

    eng_path = os.path.join(TESSDATA_DIR_WRITABLE, "eng.traineddata")
    if not os.path.exists(eng_path) or os.path.getsize(eng_path) < 100000:
        log_info(f"Downloading OCR English traineddata from {tessdata_url}...")
        try:
            req = urllib.request.Request(tessdata_url, headers={"User-Agent": "UTGPT/0.1"})
            with _urlopen(req, timeout=120) as resp, open(eng_path, "wb") as out:
                shutil.copyfileobj(resp, out)
            if os.path.getsize(eng_path) < 100000:
                raise Exception("Downloaded traineddata is suspiciously small; likely an error page.")
        except Exception as e:
            log_error(f"Failed to download eng.traineddata: {e}")
            TESSERACT_ERROR = f"Tessdata download error: {e}"
            return False

    if is_tesseract_working(TESSERACT_PATH_WRITABLE, TESSDATA_DIR_WRITABLE):
        log_info("Successfully downloaded and verified working Tesseract OCR engine.")
        TESSERACT_READY = True
        TESSERACT_ERROR = None
        return True
    else:
        TESSERACT_ERROR = "Tesseract binary verification failed (binary runs but eng language data did not load)."
        log_error(TESSERACT_ERROR)
        return False

def download_tesseract_in_background():
    global TESSERACT_DOWNLOADING, TESSERACT_READY, TESSERACT_ERROR
    # No early return here: the starter holds single-flight under the lock,
    # and skipping the finally would wedge TESSERACT_DOWNLOADING on True.
    try:
        ensure_tesseract_ocr()
    except Exception as e:
        TESSERACT_ERROR = str(e)
    finally:
        with _OCR_DL_LOCK:
            TESSERACT_DOWNLOADING = False

def start_ocr_engine_download():
    global TESSERACT_DOWNLOADING
    with _OCR_DL_LOCK:
        if TESSERACT_DOWNLOADING:
            return
        # Flip the flag here, not in the thread: otherwise callers checking
        # it right after this call miss the download in progress.
        TESSERACT_DOWNLOADING = True
    thread = threading.Thread(target=download_tesseract_in_background)
    thread.daemon = True
    thread.start()


def _extract_svg_text(file_path):
    # SVGs with real <text> nodes give exact text, better than OCR.
    # Returns "" for outlined paths so callers try rasterize + OCR.
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(file_path)
        parts = []
        for el in tree.getroot().iter():
            tag = el.tag
            if isinstance(tag, str) and tag.lower().endswith("text"):
                txt = "".join(el.itertext()).strip()
                if txt:
                    parts.append(txt)
        return "\n".join(parts).strip()
    except Exception as e:
        log_error(f"SVG text extraction failed: {e}")
        return ""


def _rasterize_svg(file_path):
    # PIL can't read SVG, so try whatever renderer exists. (None, None) if none.
    out = file_path + ".raster.png"
    try:
        import cairosvg
        cairosvg.svg2png(url=file_path, write_to=out, scale=3.0)
        return out, out
    except ImportError:
        pass
    except Exception as e:
        log_error(f"cairosvg rasterization failed: {e}")
    for cmd in (["rsvg-convert", "-w", "1200", "-o", out, file_path],
                ["convert", "-density", "300", "-background", "white", "-flatten", file_path, out]):
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if res.returncode == 0 and os.path.exists(out):
                return out, out
        except FileNotFoundError:
            continue
        except Exception as e:
            log_error(f"SVG rasterizer {' '.join(cmd[:1])} failed: {e}")
    return None, None


def _prepare_image_for_ocr(file_path):
    # Tesseract can't read some formats and ignores EXIF orientation, so
    # normalize first: transpose, flatten, and cap size. Returns (path, tmp).
    ext = os.path.splitext(file_path)[1].lower()
    needs_convert = ext in (".svg", ".ico", ".gif", ".webp")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return file_path, None

    try:
        img = Image.open(file_path)
    except Exception as e:
        log_error(f"Could not open image for OCR preprocessing: {e}")
        return file_path, None

    try:
        # Flatten transparency / palettes; take first frame of animations.
        try:
            img.seek(0)
        except Exception:
            pass
        if getattr(img, "is_animated", False):
            try:
                img.seek(0)
            except Exception:
                pass
        # EXIF first: portrait phone shots reach Tesseract sideways otherwise.
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            try:
                background.paste(img, mask=img.split()[-1])
            except Exception:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        # Big photos only slow OCR down, cap at 2000px.
        max_dim = max(w, h)
        if max_dim > 2000:
            scale = 2000.0 / float(max_dim)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            w, h = img.size
        # Tiny images need ~300 DPI equivalent, scale up.
        min_dim = min(w, h)
        if 0 < min_dim < 1000:
            scale = min(3.0, 1000.0 / float(min_dim))
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            min_dim = min(img.size)

        if needs_convert or min_dim < 1000 or max_dim > 2000 or ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
            tmp = file_path + ".ocr.png"
            img.save(tmp, "PNG")
            return tmp, tmp
        return file_path, None
    except Exception as e:
        log_error(f"Image preprocessing failed, using original file: {e}")
        return file_path, None


# Word list to tell real OCR text apart from rotation garbage. Lenient on
# purpose: ties keep the original orientation, so other languages are safe.
_COMMON_OCR_WORDS = frozenset(
    "the be to of and a in that have i it for not on with he as you do at "
    "this but his by from they we say her she or an will my one all would "
    "there their what so up out if about who get which go me when make can "
    "like time no just him know take people into year your good some could "
    "them see other than then now look only come its over think also back "
    "after use two how our work first well way even new want because any "
    "these give day most us is are was were has had hello please price total "
    "date name address phone email street road park hotel menu open".split()
)

def _text_quality_score(text):
    # Share of alpha words found in the common list, plus word count.
    import re
    if not text:
        return 0.0, 0
    words = re.findall(r"[A-Za-z]{2,}", text.lower())
    if not words:
        return 0.0, 0
    good = sum(1 for w in words if w in _COMMON_OCR_WORDS)
    return good / len(words), len(words)


def _run_tesseract(bin_path, image_path, tessdata_dir, lang="eng", psm=3):
    # One tesseract pass. Returns (returncode, stdout, stderr).
    env = _tesseract_env(tessdata_dir)
    cmd = [bin_path, image_path, "stdout", "-l", lang]
    if tessdata_dir:
        cmd += ["--tessdata-dir", tessdata_dir]
    # LSTM engine + automatic page segmentation; caller may retry with psm 6.
    cmd += ["--oem", "1", "--psm", str(psm)]
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=60
    )
    return res.returncode, res.stdout, res.stderr

def _extract_image_ocr(file_path, lang="eng"):
    # Image -> text via Tesseract. Returns "" on failure: placeholders must
    # never land in document_chunks, they'd end up in the prompt as fake text.
    if not file_path or not os.path.exists(file_path):
        log_error(f"Image file for OCR not found: {file_path}")
        return ""

    filename = os.path.basename(file_path)
    ext = os.path.splitext(file_path)[1].lower()

    # SVG is markup, not pixels: grab <text> nodes first, OCR the rendering after.
    if ext == ".svg":
        svg_text = _extract_svg_text(file_path)
        if svg_text:
            log_info(f"SVG text extraction yielded {len(svg_text)} characters from '{filename}'.")
            return svg_text
        raster, raster_tmp = _rasterize_svg(file_path)
        if raster:
            try:
                result = _extract_image_ocr(raster, lang)
                return result
            finally:
                if raster_tmp and os.path.exists(raster_tmp):
                    try:
                        os.remove(raster_tmp)
                    except OSError:
                        pass
        log_info(f"SVG '{filename}' has no extractable text and no rasterizer is available.")
        return ""

    tesseract_bin, tessdata_dir = _get_tesseract_path_and_tessdata(lang)

    if not tesseract_bin or not is_tesseract_working(tesseract_bin, tessdata_dir, lang):
        start_ocr_engine_download()
        # Wait up to ~30s for the download, bail early once it's done.
        for _ in range(60):
            time.sleep(0.5)
            tesseract_bin, tessdata_dir = _get_tesseract_path_and_tessdata(lang)
            if tesseract_bin and is_tesseract_working(tesseract_bin, tessdata_dir, lang):
                break
            if not TESSERACT_DOWNLOADING:
                break

    tesseract_bin, tessdata_dir = _get_tesseract_path_and_tessdata(lang)
    if tesseract_bin and is_tesseract_working(tesseract_bin, tessdata_dir, lang):
        ocr_path, tmp_path = _prepare_image_for_ocr(file_path)
        temp_files = [tmp_path] if tmp_path else []
        try:
            log_info(f"Running OCR on '{filename}' using binary '{tesseract_bin}' (lang={lang})...")

            def _ocr_single(path, psm):
                rc, out, err = _run_tesseract(tesseract_bin, path, tessdata_dir, lang, psm)
                if rc != 0:
                    log_error(f"Tesseract OCR (psm={psm}) failed on '{filename}' (code {rc}): {(err or '').strip()[:300]}")
                    return ""
                return (out or "").strip()

            # Try upright first, that's the common case.
            extracted = _ocr_single(ocr_path, 3) or _ocr_single(ocr_path, 6)
            score, nwords = _text_quality_score(extracted)

            # Garbage text usually means a rotated photo EXIF didn't fix, so
            # try the other orientations and keep the best. Needs enough
            # words to judge; ties keep the original.
            if extracted and nwords >= 8 and score < 0.12:
                log_info(f"OCR quality low for '{filename}' (score={score:.2f}); trying rotated orientations...")
                try:
                    from PIL import Image
                    base = Image.open(ocr_path)
                    best_text, best_score, best_len = extracted, score, len(extracted)
                    for angle in (90, 180, 270):
                        rot_path = ocr_path + f".rot{angle}.png"
                        try:
                            base.rotate(angle, expand=True).save(rot_path, "PNG")
                            temp_files.append(rot_path)
                        except Exception as e:
                            log_error(f"Rotation {angle} failed for '{filename}': {e}")
                            continue
                        cand = _ocr_single(rot_path, 3)
                        cs, _ = _text_quality_score(cand)
                        if cand and (cs > best_score + 0.02 or (abs(cs - best_score) <= 0.02 and len(cand) > best_len)):
                            best_text, best_score, best_len = cand, cs, len(cand)
                    if best_text is not extracted:
                        log_info(f"OCR orientation fix for '{filename}': score {score:.2f} -> {best_score:.2f}.")
                    extracted = best_text
                except ImportError:
                    pass
                except Exception as e:
                    log_error(f"OCR rotation retry failed for '{filename}': {e}")

            if extracted:
                log_info(f"OCR successfully extracted {len(extracted)} characters from '{filename}'.")
                return extracted
            log_info(f"OCR finished for '{filename}' with no detectable text.")
            return ""
        except Exception as e:
            log_error(f"Failed to execute Tesseract binary on {filename}: {e}")
        finally:
            for tmp in temp_files:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

    # Fallback to pytesseract if installed in python environment
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(file_path)
        extracted = pytesseract.image_to_string(img, lang=lang).strip()
        if extracted:
            log_info(f"pytesseract successfully extracted {len(extracted)} characters from '{filename}'.")
            return extracted
        return ""
    except ImportError:
        pass
    except Exception as e:
        log_error(f"pytesseract extraction error on {filename}: {e}")

    log_warn(f"No OCR engine available to extract text from '{filename}'.")
    return ""

def get_ocr_info():
    """Returns OCR availability status and engine details."""
    tesseract_bin, tessdata_dir = _get_tesseract_path_and_tessdata()
    has_bin = bool(tesseract_bin and is_tesseract_working(tesseract_bin, tessdata_dir))
    has_pytesseract = False
    try:
        import pytesseract
        has_pytesseract = True
    except ImportError:
        pass

    available = has_bin or has_pytesseract
    return {
        "available": available,
        "binary_path": tesseract_bin or "",
        "tessdata_path": tessdata_dir or "",
        "downloading": TESSERACT_DOWNLOADING,
        "error": TESSERACT_ERROR,
        "engine": "tesseract" if has_bin else ("pytesseract" if has_pytesseract else "none")
    }

def extract_text_from_file(file_path):
    if not file_path:
        return ""
    if file_path.startswith("file://"):
        file_path = urllib.parse.unquote(file_path[7:])
    if not os.path.exists(file_path):
        log_error(f"Document file not found: {file_path}")
        return ""

    ext = os.path.splitext(file_path)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return _extract_image_ocr(file_path)
    elif ext == ".pdf":
        return _extract_pdf_text(file_path)

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        log_error(f"Error reading file {file_path}: {e}")
        try:
            with open(file_path, "r", encoding="latin-1", errors="replace") as f:
                return f.read()
        except Exception:
            return ""

def chunk_text(text, chunk_size=600, overlap=100):
    if not text:
        return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
        if start >= text_len or chunk_size <= overlap:
            break
    return chunks

def attach_document(file_path, session_id=None):
    if not file_path:
        return None
    if file_path.startswith("file://"):
        file_path = urllib.parse.unquote(file_path[7:])
        if file_path.startswith("localhost/"):
            file_path = file_path[9:]
        if not file_path.startswith("/"):
            file_path = "/" + file_path

    if not os.path.exists(file_path):
        log_error(f"attach_document: file does not exist: {file_path}")
        return None

    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    filename = os.path.basename(file_path)

    # Save a permanent copy in attachments directory so Content Hub cleanup doesn't delete it
    dest_filename = f"{int(time.time())}_{filename}"
    dest_path = os.path.join(ATTACHMENTS_DIR, dest_filename)
    try:
        shutil.copy2(file_path, dest_path)
        stored_path = dest_path
    except Exception as copy_err:
        log_error(f"Could not copy attachment to persistent storage: {copy_err}")
        stored_path = file_path

    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if not session_id or str(session_id).strip() == "" or str(session_id) == "null":
        cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            session_id = row[0]
        else:
            cursor.execute("INSERT INTO sessions (title, created_at) VALUES (?, ?)", ("New Chat", time.time()))
            session_id = cursor.lastrowid
            conn.commit()

    file_size = os.path.getsize(stored_path)
    ext = os.path.splitext(stored_path)[1].lower()
    is_image = ext in IMAGE_EXTENSIONS
    file_type = "image" if is_image else ("pdf" if ext == ".pdf" else "document")

    extracted_text = extract_text_from_file(stored_path)
    extracted_text = (extracted_text or "").strip()
    char_count = len(extracted_text)
    ocr_success = is_image and char_count > 0
    ocr_chars = char_count if ocr_success else 0
    ocr_error = ""
    if is_image and not ocr_success:
        ocr_info = get_ocr_info()
        if ocr_info.get("downloading"):
            ocr_error = "downloading"
        elif not ocr_info.get("available"):
            ocr_error = "engine_not_ready"
        else:
            ocr_error = "no_text"

    cursor.execute("""
        INSERT INTO documents (session_id, filename, file_path, file_size, char_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, filename, stored_path, file_size, char_count, time.time()))
    doc_id = cursor.lastrowid

    chunks = chunk_text(extracted_text)
    if not chunks and extracted_text:
        chunks = [extracted_text]
    # Empty text stores zero chunks. Fake placeholder text must never be
    # indexed (old rows with it get skipped when reading back).

    for idx, c in enumerate(chunks):
        cursor.execute("""
            INSERT INTO document_chunks (document_id, session_id, chunk_index, content)
            VALUES (?, ?, ?, ?)
        """, (doc_id, session_id, idx, c))

    conn.commit()
    conn.close()

    log_info(f"Attached {file_type} '{filename}' (ID: {doc_id}) to session {session_id} with {len(chunks)} chunks, {char_count} chars.")
    return {
        "id": doc_id,
        "session_id": session_id,
        "filename": filename,
        "file_path": stored_path,
        "file_size": file_size,
        "char_count": char_count,
        "chunk_count": len(chunks),
        "file_type": file_type,
        "is_image": is_image,
        "ocr_success": ocr_success,
        "ocr_chars": ocr_chars,
        "ocr_error": ocr_error,
        "ocr_downloading": TESSERACT_DOWNLOADING or ocr_error == "downloading"
    }

def get_session_documents(session_id=None):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if not session_id or str(session_id).strip() == "" or str(session_id) == "null":
        cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            session_id = row[0]
        else:
            conn.close()
            return []

    cursor.execute("""
        SELECT id, session_id, filename, file_path, file_size, char_count, created_at
        FROM documents
        WHERE session_id = ?
        ORDER BY id ASC
    """, (session_id,))
    rows = cursor.fetchall()
    doc_ids = [r[0] for r in rows]
    chunk_counts = {}
    if doc_ids:
        placeholders = ",".join("?" for _ in doc_ids)
        cursor.execute(
            f"SELECT document_id, COUNT(*) FROM document_chunks WHERE document_id IN ({placeholders}) GROUP BY document_id",
            doc_ids,
        )
        chunk_counts = {r[0]: r[1] for r in cursor.fetchall()}
    conn.close()

    result = []
    for r in rows:
        fname = r[2]
        fpath = r[3]
        ext = os.path.splitext(fpath or fname)[1].lower()
        is_image = ext in IMAGE_EXTENSIONS
        file_type = "image" if is_image else ("pdf" if ext == ".pdf" else "document")
        result.append({
            "id": r[0],
            "session_id": r[1],
            "filename": r[2],
            "file_path": r[3],
            "file_size": r[4],
            "char_count": r[5],
            "created_at": r[6],
            "chunk_count": chunk_counts.get(r[0], 0),
            "file_type": file_type,
            "is_image": is_image
        })
    return result

def delete_session_document(document_id):
    if not document_id:
        return False
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM documents WHERE id = ?", (document_id,))
    row = cursor.fetchone()
    if row and row[0]:
        fp = row[0]
        if fp.startswith(ATTACHMENTS_DIR) and os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError:
                pass
    cursor.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    cursor.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()
    conn.close()
    return True

def retrieve_document_context(query, session_id=None, limit=6):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if not session_id or str(session_id).strip() == "" or str(session_id) == "null":
        cursor.execute("SELECT session_id FROM documents ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row and row[0]:
            session_id = row[0]
        else:
            cursor.execute("SELECT session_id FROM messages WHERE session_id IS NOT NULL ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row and row[0]:
                session_id = row[0]
            else:
                cursor.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    session_id = row[0]
                else:
                    conn.close()
                    return ""

    cursor.execute("SELECT id, filename, char_count FROM documents WHERE session_id = ? ORDER BY id ASC", (session_id,))
    doc_rows = cursor.fetchall()
    if not doc_rows:
        conn.close()
        return ""

    selected_chunks = []
    for d_id, fname, c_count in doc_rows:
        ext = os.path.splitext(fname)[1].lower()
        is_img = ext in IMAGE_EXTENSIONS
        cursor.execute("""
            SELECT d.filename, dc.chunk_index, dc.content
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.document_id = ?
            ORDER BY dc.chunk_index ASC
        """, (d_id,))
        chunks_for_doc = cursor.fetchall()
        for row in chunks_for_doc:
            content = (row[2] or "").strip()
            if not content:
                continue
            # Leftovers from before the fix, e.g. "[Image attached: ...]".
            # Those would reach the model as fake transcript text.
            if content.startswith("[Image attached:") or content.startswith("[PDF Document attached]"):
                continue
            selected_chunks.append({
                "filename": row[0],
                "chunk_index": row[1],
                "content": content,
                "is_image": is_img
            })

    conn.close()

    if not selected_chunks:
        return ""

    context_str = "Attached Context (Local Documents & Transcribed Images):\n"
    for item in selected_chunks[:limit]:
        fname = item['filename']
        ext = os.path.splitext(fname)[1].lower()
        is_img = item.get('is_image', ext in IMAGE_EXTENSIONS)
        if is_img:
            context_str += f"[Attached file: '{fname}' (text extracted from the file)]:\n\"\"\"\n{item['content']}\n\"\"\"\n\n"
        else:
            context_str += f"[Attached Document: '{fname}' (Part {item['chunk_index'] + 1})]:\n\"\"\"\n{item['content']}\n\"\"\"\n\n"

    return context_str.strip()

def get_model_metadata(model_filename):
    # Try local models.json first
    try:
        models_json_path = os.path.join(APP_DIR, "assets", "models.json")
        if os.path.exists(models_json_path):
            with open(models_json_path, "r") as f:
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
    integrating retrieved relevant history context (RAG) and OCR image transcripts in the system prompt.
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

    # Keep 25% of the window free for generation. Doc context goes in the
    # system prompt once (never duplicated into the user turn), history
    # fills what's left.
    safe_token_budget = int(max_context * 0.75)
    query_tokens = len(current_query) // 4

    doc_context_str = ""
    web_context_str = ""
    history_rag_str = ""
    for msg in context_msgs:
        text_cleaned = (msg.get("text", "") or "").strip()
        if not text_cleaned:
            continue
        if text_cleaned.startswith("Web Search Results"):
            web_context_str += f"{text_cleaned}\n\n"
        elif text_cleaned.startswith("Attached Context"):
            doc_context_str += f"{text_cleaned}\n\n"
        else:
            history_rag_str += f"- {text_cleaned}\n"

    doc_context_str = doc_context_str.strip()
    web_context_str = web_context_str.strip()
    history_rag_str = history_rag_str.strip()

    system_instruction_parts = ["You are a helpful, knowledgeable AI assistant."]

    if doc_context_str:
        system_instruction_parts.append(
            "The user has provided the text content of their file(s) below — it was extracted from the files and shown to you in full. "
            "This text IS the file content and you CAN read and use it. "
            "Answer the user's questions directly from this text (translate, summarize, quote, or extract details as requested). "
            "Never claim you cannot access attached files or images, even if the user asks about an 'image': the extracted text below is its content, so just use it:\n\n"
            + doc_context_str
        )

    if web_context_str:
        system_instruction_parts.append(web_context_str)

    if history_rag_str:
        system_instruction_parts.append("Relevant facts and details from previous conversations:\n" + history_rag_str)

    system_content = "\n\n".join(system_instruction_parts)

    # Budget: system (incl. full doc context) + query first, then history.
    current_tokens = len(system_content) // 4 + query_tokens
    allowed_recent_history = []
    for msg in reversed(recent_history):
        content = msg.get("content", "")
        msg_tok = len(content) // 4
        if current_tokens + msg_tok < safe_token_budget:
            allowed_recent_history.insert(0, msg)
            current_tokens += msg_tok

    # Attached text lives in the system prompt only. It used to be copied
    # into the user turn too, which blew the context budget on small models.
    user_turn_content = current_query

    # Format using resolved template_type
    prompt = ""
    boundary = ""
    if template_type == "llama3":
        prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_content}<|eot_id|>"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>"
        prompt += f"<|start_header_id|>user<|end_header_id|>\n\n{user_turn_content}<|eot_id|>"
        prompt += "<|start_header_id|>assistant<|end_header_id|>\n\n"
        boundary = "<|start_header_id|>assistant<|end_header_id|>\n\n"

    elif template_type == "chatml":
        prompt = f"<|im_start|>system\n{system_content}<|im_end|>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{user_turn_content}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        boundary = "<|im_start|>assistant\n"

    elif template_type == "zephyr":
        prompt = f"<|system|>\n{system_content}</s>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|{role}|>\n{content}</s>\n"
        prompt += f"<|user|>\n{user_turn_content}</s>\n"
        prompt += "<|assistant|>\n"
        boundary = "<|assistant|>\n"

    elif template_type == "gemma":
        prompt = "<bos>"
        prompt += f"<start_of_turn>system\n{system_content}<end_of_turn>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<start_of_turn>{role}\n{content}<end_of_turn>\n"
        prompt += f"<start_of_turn>user\n{user_turn_content}<end_of_turn>\n"
        prompt += "<start_of_turn>assistant\n"
        boundary = "<start_of_turn>assistant\n"

    elif template_type == "phi3":
        prompt = "<s>"
        prompt += f"<|system|>\n{system_content}<|end|>\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|{role}|>\n{content}<|end|>\n"
        prompt += f"<|user|>\n{user_turn_content}<|end|>\n"
        prompt += "<|assistant|>\n"
        boundary = "<|assistant|>\n"

    else:
        prompt = f"System: {system_content}\n\n"
        for msg in allowed_recent_history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            prompt += f"{role}: {content}\n"
        prompt += f"User: {user_turn_content}\nAssistant:"
        boundary = "Assistant:"

    if "deepseek-r1" in model_lower:
        prompt += "<think>\n"

    return prompt, boundary

def run_inference(model_filename, user_message, temperature, max_tokens, *args):
    # session_id is optional and comes right before the two callbacks:
    # [..., web_search_enabled, (session_id,) token_callback, done_callback]
    threads = 4
    ctx_size = 2048
    flash_attn = "auto"
    kv_cache = "f16"
    web_search_enabled = False
    session_id = None
    token_callback = None
    done_callback = None

    def _take_trailing_callbacks(rem):
        # Pulls out [.., (session_id,) tok, done]. "chat-<ts>" style ids are
        # callbacks, plain numbers are session ids.
        nonlocal token_callback, done_callback, session_id
        if len(rem) == 2:
            token_callback, done_callback = rem
            return None
        elif len(rem) >= 3:
            *maybe_session, tok, done = rem
            first = maybe_session[0] if maybe_session else None
            if first is None or first == "" or (isinstance(first, (int, float)) and not isinstance(first, bool)):
                session_id = first
                token_callback, done_callback = tok, done
                return session_id
            try:
                # Numeric strings ("12") are session ids; "chat-..." is a request id.
                int(str(first))
                session_id = first
                token_callback, done_callback = tok, done
                return session_id
            except (ValueError, TypeError):
                token_callback, done_callback = tok, done
                return None
        elif len(rem) == 1:
            token_callback = rem[0]
        return None

    if len(args) == 2:
        token_callback, done_callback = args
    elif len(args) == 5:
        threads, ctx_size, flash_attn, token_callback, done_callback = args
    elif len(args) == 6:
        threads, ctx_size, flash_attn, kv_cache, token_callback, done_callback = args
    elif len(args) >= 7:
        threads, ctx_size, flash_attn, kv_cache, web_search_enabled = args[:5]
        session_id = _take_trailing_callbacks(list(args[5:]))
    elif len(args) > 0:
        if not isinstance(args[0], (str, callable)):
            try:
                threads = int(args[0])
                if len(args) > 1: ctx_size = int(args[1])
                if len(args) > 2: flash_attn = str(args[2])
                if len(args) > 3:
                    if args[3] in ["f16", "q8_0", "q4_0"]:
                        kv_cache = str(args[3])
                        if len(args) > 4:
                            if isinstance(args[4], bool) or str(args[4]).lower() in ("true", "false", "1", "0"):
                                web_search_enabled = str(args[4]).lower() in ("true", "1")
                                if len(args) > 5: token_callback = args[5]
                                if len(args) > 6: done_callback = args[6]
                            else:
                                token_callback = args[4]
                                if len(args) > 5: done_callback = args[5]
                    else:
                        token_callback = args[3]
                        if len(args) > 4: done_callback = args[4]
            except Exception:
                pass
        else:
            token_callback = args[0]
            if len(args) > 1: done_callback = args[1]

    web_search_enabled = bool(web_search_enabled)
    log_info("Entering run_inference with model={0}, threads={1}, ctx_size={2}, flash_attn={3}, web_search={4}, session={5}".format(model_filename, threads, ctx_size, flash_attn, web_search_enabled, session_id))
    
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

    def worker():
        process = None
        try:
            web_context_msgs = []
            if web_search_enabled:
                log_info("Performing web search for query: {0}".format(current_query))
                _emit_token(token_callback, "*Searching the web for latest info...*\n\n")
                search_results = search_web(current_query, num_results=3)
                if search_results:
                    formatted_web = "Web Search Results (Current Real-time Info):\n"
                    for idx, res in enumerate(search_results, 1):
                        title = res.get('title', '')
                        snippet = res.get('snippet', '')
                        url = res.get('url', '')
                        formatted_web += f"{idx}. Title: {title}\n   Snippet: {snippet}\n   Source: {url}\n"
                    web_context_msgs = [{"role": "system", "text": formatted_web}]
                else:
                    _emit_token(token_callback, "*Web search returned no results, relying on model knowledge...*\n\n")

            exclude_texts = {current_query}
            for msg in recent_history:
                exclude_texts.add(msg.get("content", ""))

            doc_context = retrieve_document_context(current_query, session_id=session_id)
            doc_context_msgs = [{"role": "system", "text": doc_context}] if doc_context else []

            context_msgs = web_context_msgs + doc_context_msgs + retrieve_relevant_context(current_query, exclude_texts, limit=3)
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

            additional_args = [
                "-t", str(int(threads)),
                "-tb", str(int(threads)),
                "-c", str(int(ctx_size)),
                "-fa", str(flash_attn)
            ]
            if kv_cache in ["q8_0", "q4_0"]:
                additional_args.extend(["-ctk", kv_cache, "-ctv", kv_cache])
            for token in stop_tokens:
                additional_args.extend(["-r", token])
            
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
            ld_library_paths = [MODELS_DIR, os.path.join(APP_DIR, "assets")]
            if "LD_LIBRARY_PATH" in env:
                env["LD_LIBRARY_PATH"] = os.path.pathsep.join(ld_library_paths + [env["LD_LIBRARY_PATH"]])
            else:
                env["LD_LIBRARY_PATH"] = os.path.pathsep.join(ld_library_paths)

            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                env=env
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

            if is_completion:
                log_debug("Using simplified completion stdout read loop")
                while True:
                    char = process.stdout.read(1)
                    if not char:
                        break
                    
                    output_buffer += char
                    
                    if len(output_buffer) > 20:
                        emit_char = output_buffer[0]
                        output_buffer = output_buffer[1:]
                        if not has_emitted_content:
                            if emit_char.strip() == "":
                                continue
                            else:
                                has_emitted_content = True
                        _emit_token(token_callback, emit_char)
                
                if output_buffer:
                    if not has_emitted_content:
                        output_buffer = output_buffer.lstrip()
                    # Clean up llama-completion's end-of-text markers
                    output_buffer = output_buffer.replace(" [end of text]", "").replace("[end of text]", "")
                    if output_buffer:
                        log_debug("Emitting remaining completion buffer: {0}".format(repr(output_buffer)))
                        _emit_token(token_callback, output_buffer)
            else:
                log_debug("Using legacy cli boundary detection stdout read loop")
                started = False
                checked_banner = False
                
                while True:
                    char = process.stdout.read(1)
                    if not char:
                        break
                    
                    output_buffer += char
                    
                    if not checked_banner:
                        if len(output_buffer) >= 15:
                            if "Loading model" in output_buffer:
                                log_debug("Detected interactive banner, waiting for boundary")
                            else:
                                log_debug("No interactive banner detected, starting stream immediately")
                                started = True
                            checked_banner = True
                    
                    if not started:
                        if boundary in output_buffer or "Assistant:" in output_buffer or "<|im_start|>assistant" in output_buffer or "<|start_header_id|>assistant" in output_buffer or "<start_of_turn>assistant" in output_buffer or "<|assistant|>" in output_buffer:
                            log_debug("Detected boundary, starting token stream")
                            output_buffer = ""
                            started = True
                        continue
                        
                    if "[ Prompt:" in output_buffer:
                        log_debug("Detected '[ Prompt:' footer boundary")
                        break
                        
                    if len(output_buffer) > 20:
                        emit_char = output_buffer[0]
                        output_buffer = output_buffer[1:]
                        if not has_emitted_content:
                            if emit_char.strip() == "":
                                continue
                            else:
                                has_emitted_content = True
                        _emit_token(token_callback, emit_char)

                if not started and "Loading model" not in output_buffer:
                    started = True

                if started and output_buffer:
                    remaining = output_buffer.split("[ Prompt:")[0]
                    if not has_emitted_content:
                        remaining = remaining.lstrip()
                    if remaining:
                        log_debug("Emitting remaining buffer content: {0}".format(repr(remaining)))
                        _emit_token(token_callback, remaining)

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


def get_hardcoded_models():
    return {item["name"]: item["url"] for item in DEFAULT_CATALOG}


def stop_all_inference():
    with INFERENCE_LOCK:
        processes = list(ACTIVE_PROCESSES)

    for process in processes:
        _terminate_process(process)


def import_local_model_thread(file_url, request_id):
    try:
        import urllib.parse
        from urllib.request import url2pathname

        if file_url.startswith("file://"):
            path = file_url[7:]
            if path.startswith("localhost/"):
                path = path[9:]
            if not path.startswith("/"):
                path = "/" + path
            source_path = urllib.parse.unquote(path)
        else:
            source_path = file_url

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
        bytes_copied = 0
        chunk_size = 4 * 1024 * 1024  # 4MB chunks

        _send_event("import_start", {
            "requestId": request_id,
            "filename": filename,
            "totalSize": total_size
        })

        with open(source_path, "rb") as fsrc:
            with open(dest_path, "wb") as fdst:
                while True:
                    chunk = fsrc.read(chunk_size)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    bytes_copied += len(chunk)
                    progress = int((bytes_copied / total_size) * 100) if total_size > 0 else 0
                    _send_event("import_progress", {
                        "requestId": request_id,
                        "filename": filename,
                        "progress": progress
                    })

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
        "version": "0.0.2",
        "date": "2026-07-26",
        "title": "What's New in UTGPT",
        "subtitle": "Version 0.0.2 Release Notes",
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

    tesseract_bin, tessdata_dir = _get_tesseract_path_and_tessdata()
    if not tesseract_bin or not is_tesseract_working(tesseract_bin, tessdata_dir):
        start_ocr_engine_download()
        
    is_desktop = True
    if os.environ.get("APP_ID") or os.environ.get("LOMIRI_APP_LAUNCH_ENV"):
        is_desktop = False

    rel_notes = get_release_notes()
    app_version = rel_notes.get("version", "0.0.2")

    return {
        "ready": True,
        "modelsDir": MODELS_DIR,
        "llamaCliPath": get_llama_cli_path(),
        "llamaCliReady": LLAMA_CLI_READY,
        "debug": DEBUG_MODE,
        "isDesktop": is_desktop,
        "version": app_version,
        "releaseNotes": rel_notes,
        "ocr": get_ocr_info()
    }


