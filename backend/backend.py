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
import sqlite3

DEBUG_MODE = os.environ.get("UTGPT_DEBUG", "").lower() in ("1", "true", "yes")

def log_debug(msg):
    if DEBUG_MODE:
        print("UTGPT_LOG [DEBUG]: {0}".format(msg), file=sys.stderr, flush=True)

def log_info(msg):
    print("UTGPT_LOG [INFO]: {0}".format(msg), file=sys.stderr, flush=True)

def log_error(msg):
    print("UTGPT_LOG [ERROR]: {0}".format(msg), file=sys.stderr, flush=True)

def _urlopen(req, timeout=60):
    try:
        import ssl
        context = ssl._create_unverified_context()
        return urllib.request.urlopen(req, timeout=timeout, context=context)
    except Exception:
        return urllib.request.urlopen(req, timeout=timeout)


ACTIVE_DOWNLOADS = {}
DOWNLOADS_LOCK = threading.Lock()

try:
    import pyotherside
except ImportError:  # pragma: no cover - only unavailable outside the app runtime
    pyotherside = None


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODELS_DIR = os.path.expanduser("~/.local/share/utgpt.surajyadav/models")
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
        if b"error while loading shared libraries" in res.stderr:
            return False
        return True
    except Exception:
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

    if ram_gb <= 3.1:
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

def ensure_llama_cli():
    cli_path = get_llama_cli_path()
    completion_path = get_llama_completion_path()
    if is_binary_working(cli_path) and is_binary_working(completion_path):
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
        
    tag = "b9874"
    try:
        import json
        req = urllib.request.Request("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5", headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=10) as response:
            releases = json.loads(response.read().decode())
            expected_asset_suffix = f"-bin-ubuntu-{target_arch}.tar.gz"
            found_tag = None
            for release in releases:
                r_tag = release.get("tag_name")
                if not r_tag:
                    continue
                assets = release.get("assets", [])
                expected_asset_name = f"llama-{r_tag}{expected_asset_suffix}"
                if any(asset.get("name") == expected_asset_name for asset in assets):
                    found_tag = r_tag
                    break
            if found_tag:
                tag = found_tag
                log_info("Resolved latest llama.cpp release tag to: {0}".format(tag))
            else:
                log_info("No release with valid asset found in latest releases, using fallback tag: {0}".format(tag))
    except Exception as e:
        log_error("Error fetching latest release from GitHub API: {0}. Using fallback tag: {1}".format(e, tag))
        
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-ubuntu-{target_arch}.tar.gz"
    
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
        global LLAMA_CLI_ERROR
        LLAMA_CLI_ERROR = str(e)
        return False
    return False

def download_llama_cli_in_background():
    global LLAMA_CLI_READY, LLAMA_CLI_ERROR, LLAMA_CLI_DOWNLOADING
    LLAMA_CLI_DOWNLOADING = True
    LLAMA_CLI_ERROR = None
    try:
        if ensure_llama_cli():
            LLAMA_CLI_READY = True
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
    integrating retrieved relevant history context (RAG) in the system prompt.
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
        context_str = "Relevant facts and details from previous conversations:\n"
        for msg in allowed_context_msgs:
            # Strip any trailing newlines from stored messages to keep formatting clean
            text_cleaned = msg.get("text", "").strip()
            if text_cleaned:
                context_str += f"- {text_cleaned}\n"

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
    # Support backward compatible dynamic signatures
    threads = 4
    ctx_size = 2048
    flash_attn = "auto"
    kv_cache = "f16"
    token_callback = None
    done_callback = None

    if len(args) == 2:
        token_callback, done_callback = args
    elif len(args) == 5:
        threads, ctx_size, flash_attn, token_callback, done_callback = args
    elif len(args) == 6:
        threads, ctx_size, flash_attn, kv_cache, token_callback, done_callback = args
    elif len(args) > 0:
        if not isinstance(args[0], (str, callable)):
            try:
                threads = int(args[0])
                if len(args) > 1: ctx_size = int(args[1])
                if len(args) > 2: flash_attn = str(args[2])
                
                # Check if the 4th argument (args[3]) is a callback or kv_cache setting
                if len(args) > 3:
                    if args[3] in ["f16", "q8_0", "q4_0"]:
                        kv_cache = str(args[3])
                        if len(args) > 4: token_callback = args[4]
                        if len(args) > 5: done_callback = args[5]
                    else:
                        token_callback = args[3]
                        if len(args) > 4: done_callback = args[4]
            except Exception:
                pass
        else:
            token_callback = args[0]
            if len(args) > 1: done_callback = args[1]

    log_info("Entering run_inference with model={0}, threads={1}, ctx_size={2}, flash_attn={3}".format(model_filename, threads, ctx_size, flash_attn))
    if isinstance(user_message, list) and len(user_message) > 0:
        current_query = user_message[-1].get("content", "")
        recent_history = user_message[-5:-1] if len(user_message) > 1 else []
        exclude_texts = {current_query}
        for msg in recent_history:
            exclude_texts.add(msg.get("content", ""))
        context_msgs = retrieve_relevant_context(current_query, exclude_texts, limit=3)
        prompt, boundary = get_prompt_and_boundary(model_filename, current_query, recent_history, context_msgs)
    else:
        current_query = str(user_message)
        context_msgs = retrieve_relevant_context(current_query, {current_query}, limit=3)
        prompt, boundary = get_prompt_and_boundary(model_filename, current_query, [], context_msgs)
    log_debug("Constructed prompt: {0}".format(repr(prompt)))
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
            parsed = urllib.parse.urlparse(file_url)
            source_path = url2pathname(parsed.path)
        else:
            source_path = file_url

        if not os.path.exists(source_path):
            _send_event("import_error", {
                "requestId": request_id,
                "error": "Source file does not exist"
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
        
    return {
        "ready": True,
        "modelsDir": MODELS_DIR,
        "llamaCliPath": get_llama_cli_path(),
        "llamaCliReady": LLAMA_CLI_READY,
        "debug": DEBUG_MODE
    }

