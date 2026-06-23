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

def get_llama_cli_path():
    if os.path.exists(LLAMA_CLI_PATH_BUNDLED):
        return LLAMA_CLI_PATH_BUNDLED
    return LLAMA_CLI_PATH_WRITABLE

def get_llama_completion_path():
    if os.path.exists(LLAMA_COMPLETION_PATH_BUNDLED):
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
        "usage": "Fast general chat, low resource devices"
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
        "usage": "Excellent multilingual capabilities, coding & reasoning"
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
        "usage": "Distilled reasoning model, thinking step visualization, math/logic"
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
        "usage": "Ultra-fast assistant, agentic tasks, long contexts"
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
        "usage": "Smart general assistant, high quality logic & reasoning"
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
        "usage": "Lightweight high-quality chatting, instruction following"
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
        "usage": "Reasoning, logical tasks, math and coding"
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
        "usage": "Enterprise tasks, translation, coding"
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
        "usage": "Extremely lightweight, ultra-fast generation, low RAM usage"
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
        "usage": "Extremely fast, simple chats on low-spec hardware"
    }
]

import json

def fetch_model_catalog():
    url = "https://raw.githubusercontent.com/surajyadav0/utgpt/main/assets/models.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                required_keys = {"name", "filename", "url"}
                if all(required_keys.issubset(item.keys()) for item in data):
                    return data
    except Exception as e:
        print("UTGPT_LOG: Failed to fetch remote model catalog, using fallback: " + str(e), file=sys.stderr, flush=True)
    return DEFAULT_CATALOG


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
        if filename.lower().endswith(".gguf"):
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

def ensure_llama_cli():
    cli_exists = os.path.exists(LLAMA_CLI_PATH_BUNDLED) or os.path.exists(LLAMA_CLI_PATH_WRITABLE)
    completion_exists = os.path.exists(LLAMA_COMPLETION_PATH_BUNDLED) or os.path.exists(LLAMA_COMPLETION_PATH_WRITABLE)
    if cli_exists and completion_exists:
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
        
    tag = "b9555"
    try:
        import json
        req = urllib.request.Request("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest", headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if "tag_name" in data:
                tag = data["tag_name"]
    except Exception:
        pass
        
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-ubuntu-{target_arch}.tar.gz"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
        with _urlopen(req, timeout=120) as response:
            tar_data = response.read()
            
        with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as tar:
            os.makedirs(MODELS_DIR, exist_ok=True)
            extracted_any = False
            for member in tar.getmembers():
                if member.isfile():
                    basename = os.path.basename(member.name)
                    dest_path = os.path.join(MODELS_DIR, basename)
                    f = tar.extractfile(member)
                    if f:
                        with open(dest_path, "wb") as dest_file:
                            dest_file.write(f.read())
                        if basename in ["llama-cli", "llama-completion"] or basename.endswith(".so") or ".so." in basename:
                            os.chmod(dest_path, 0o755)
                        extracted_any = True
            return extracted_any
    except Exception as e:
        global LLAMA_CLI_ERROR
        LLAMA_CLI_ERROR = str(e)
        return False
    return False

def download_llama_cli_in_background():
    global LLAMA_CLI_READY, LLAMA_CLI_ERROR
    try:
        if ensure_llama_cli():
            LLAMA_CLI_READY = True
        else:
            if not LLAMA_CLI_ERROR:
                LLAMA_CLI_ERROR = "Failed to download llama-cli from GitHub"
    except Exception as e:
        LLAMA_CLI_ERROR = str(e)

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
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    # Prune corrupt entries from previous session implementations
    cursor.execute("DELETE FROM messages WHERE text LIKE '%Loading model%' OR text LIKE '%<start_of_turn>%' OR text LIKE '%<|im_start|>%' OR text LIKE '%<|start_header_id|>%'")
    conn.commit()
    conn.close()

def load_chat_history():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT role, text FROM messages ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r, "text": t} for r, t in rows]

def add_chat_message(role, text):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages (role, text, timestamp) VALUES (?, ?, ?)", (role, text, time.time()))
    conn.commit()
    conn.close()
    return True

def clear_chat_history():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages")
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

def get_prompt_and_boundary(model_filename, current_query, recent_history, context_msgs):
    """
    Formats the conversation prompt using model-specific templates,
    integrating retrieved relevant history context (RAG) in the system prompt.
    """
    model_lower = model_filename.lower()
    
    context_str = ""
    if context_msgs:
        context_str = "Relevant context from previous conversations:\n"
        for msg in context_msgs:
            role_name = "User" if msg["role"] == "user" else "Assistant"
            context_str += f"- {role_name}: {msg['text']}\n"

    # 1. Llama-3 / Llama-3.2 / Granite
    if "llama-3" in model_lower or "granite" in model_lower:
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n\n{context_str}"
        prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_content}<|eot_id|>"
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>"
        prompt += f"<|start_header_id|>user<|end_header_id|>\n\n{current_query}<|eot_id|>"
        prompt += "<|start_header_id|>assistant<|end_header_id|>\n\n"
        return prompt, "<|start_header_id|>assistant<|end_header_id|>\n\n"

    # 2. Qwen2.5 / DeepSeek-R1-Distill-Qwen / SmolLM2 / TinyLlama
    elif "qwen" in model_lower or "deepseek" in model_lower or "smollm" in model_lower or "tinyllama" in model_lower:
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n\n{context_str}"
        prompt = f"<|im_start|>system\n{system_content}<|im_end|>\n"
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{current_query}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        return prompt, "<|im_start|>assistant\n"

    # 3. Gemma-2
    elif "gemma" in model_lower:
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n{context_str}"
        prompt = "<bos>"
        prompt += f"<start_of_turn>system\n{system_content}<end_of_turn>\n"
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<start_of_turn>{role}\n{content}<end_of_turn>\n"
        prompt += f"<start_of_turn>user\n{current_query}<end_of_turn>\n"
        prompt += "<start_of_turn>assistant\n"
        return prompt, "<start_of_turn>assistant\n"

    # 4. Phi-3
    elif "phi-3" in model_lower:
        system_content = "You are a helpful assistant."
        if context_str:
            system_content += f"\n{context_str}"
        prompt = "<s>"
        prompt += f"<|system|>\n{system_content}<|end|>\n"
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<|{role}|>\n{content}<|end|>\n"
        prompt += f"<|user|>\n{current_query}<|end|>\n"
        prompt += "<|assistant|>\n"
        return prompt, "<|assistant|>\n"

    # 5. Default Fallback
    else:
        prompt = ""
        if context_str:
            prompt += f"System: {context_str}\n"
        for msg in recent_history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            prompt += f"{role}: {content}\n"
        prompt += f"User: {current_query}\nAssistant:"
        return prompt, "Assistant:"

def run_inference(model_filename, user_message, temperature, max_tokens, token_callback=None, done_callback=None):
    print("UTGPT_LOG: Entering run_inference with model={0}".format(model_filename), file=sys.stderr, flush=True)
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
    print("UTGPT_LOG: Constructed prompt: {0}".format(repr(prompt)), file=sys.stderr, flush=True)
    model_path = os.path.join(_ensure_models_dir(), model_filename)

    if not model_filename:
        print("UTGPT_LOG: Error - No model selected", file=sys.stderr, flush=True)
        _emit_done(done_callback, ok=False, error_message="No model selected.")
        return False

    if not os.path.exists(model_path):
        print("UTGPT_LOG: Error - Model file not found at {0}".format(model_path), file=sys.stderr, flush=True)
        _emit_done(done_callback, ok=False, error_message="Model file not found: {0}".format(model_filename))
        return False

    cli_path = get_llama_completion_path() if os.path.exists(get_llama_completion_path()) else get_llama_cli_path()
    if not os.path.exists(cli_path):
        if LLAMA_CLI_ERROR:
            error_msg = "Missing inference engine. Downloader error: " + str(LLAMA_CLI_ERROR)
        else:
            error_msg = "Inference engine is still downloading. Please try again in a moment."
        print("UTGPT_LOG: Error - inference engine not found: {0}".format(error_msg), file=sys.stderr, flush=True)
        _emit_done(done_callback, ok=False, error_message=error_msg)
        return False

    def worker():
        process = None
        try:
            is_completion = "llama-completion" in cli_path
            print("UTGPT_LOG: Launching inference engine: {0}".format(cli_path), file=sys.stderr, flush=True)
            
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

            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            _register_process(process)
            print("UTGPT_LOG: Inference engine launched successfully, starting stdout read loop", file=sys.stderr, flush=True)

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

            if is_completion:
                print("UTGPT_LOG: Using simplified completion stdout read loop", file=sys.stderr, flush=True)
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
                        print("UTGPT_LOG: Emitting remaining completion buffer: {0}".format(repr(output_buffer)), file=sys.stderr, flush=True)
                        _emit_token(token_callback, output_buffer)
            else:
                print("UTGPT_LOG: Using legacy cli boundary detection stdout read loop", file=sys.stderr, flush=True)
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
                                print("UTGPT_LOG: Detected interactive banner, waiting for boundary", file=sys.stderr, flush=True)
                            else:
                                print("UTGPT_LOG: No interactive banner detected, starting stream immediately", file=sys.stderr, flush=True)
                                started = True
                            checked_banner = True
                    
                    if not started:
                        if boundary in output_buffer or "Assistant:" in output_buffer or "<|im_start|>assistant" in output_buffer or "<|start_header_id|>assistant" in output_buffer or "<start_of_turn>assistant" in output_buffer or "<|assistant|>" in output_buffer:
                            print("UTGPT_LOG: Detected boundary, starting token stream", file=sys.stderr, flush=True)
                            output_buffer = ""
                            started = True
                        continue
                        
                    if "[ Prompt:" in output_buffer:
                        print("UTGPT_LOG: Detected '[ Prompt:' footer boundary", file=sys.stderr, flush=True)
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
                        print("UTGPT_LOG: Emitting remaining buffer content: {0}".format(repr(remaining)), file=sys.stderr, flush=True)
                        _emit_token(token_callback, remaining)

            print("UTGPT_LOG: Waiting for process to exit", file=sys.stderr, flush=True)
            exit_code = process.wait()
            stderr_thread.join(timeout=1.0)
            print("UTGPT_LOG: Process exited with code {0}".format(exit_code), file=sys.stderr, flush=True)
            if exit_code != 0:
                error_msg = "".join(stderr_lines).strip()
                if not error_msg:
                    error_msg = "Process exited with status {0}".format(exit_code)
                _emit_done(done_callback, ok=False, error_message=error_msg)
                return

            _emit_done(done_callback, ok=True, error_message="")
        except Exception as error:  # pragma: no cover - exercised from app runtime
            print("UTGPT_LOG: Exception in run_inference: {0}".format(error), file=sys.stderr, flush=True)
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


def initialize():
    _ensure_models_dir()
    init_db()
    global LLAMA_CLI_READY
    
    if os.path.exists(LLAMA_CLI_PATH_BUNDLED) or os.path.exists(LLAMA_CLI_PATH_WRITABLE):
        LLAMA_CLI_READY = True
    else:
        thread = threading.Thread(target=download_llama_cli_in_background)
        thread.daemon = True
        thread.start()
        
    return {
        "ready": True,
        "modelsDir": MODELS_DIR,
        "llamaCliPath": get_llama_cli_path()
    }

