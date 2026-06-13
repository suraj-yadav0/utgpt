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

def get_llama_cli_path():
    if os.path.exists(LLAMA_CLI_PATH_BUNDLED):
        return LLAMA_CLI_PATH_BUNDLED
    return LLAMA_CLI_PATH_WRITABLE

DOWNLOAD_CHUNK_SIZE = 64 * 1024
INFERENCE_LOCK = threading.Lock()
ACTIVE_PROCESSES = set()

HARDCODED_MODELS = {
    "SmolLM2-1.7B": "https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF/resolve/main/smollm2-1.7b-instruct-q4_k_m.gguf",
    "Qwen2.5-1.5B": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "TinyLlama-1.1B": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
}


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
    if os.path.exists(LLAMA_CLI_PATH_BUNDLED) or os.path.exists(LLAMA_CLI_PATH_WRITABLE):
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
            member_to_extract = None
            for member in tar.getmembers():
                if member.name.endswith("llama-cli"):
                    member_to_extract = member
                    break
                    
            if member_to_extract:
                os.makedirs(MODELS_DIR, exist_ok=True)
                f = tar.extractfile(member_to_extract)
                if f:
                    with open(LLAMA_CLI_PATH_WRITABLE, "wb") as dest_file:
                        dest_file.write(f.read())
                    os.chmod(LLAMA_CLI_PATH_WRITABLE, 0o755)
                    return True
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


def run_inference(model_filename, user_message, temperature, max_tokens, token_callback=None, done_callback=None):
    print("UTGPT_LOG: Entering run_inference with model={0}, prompt={1}".format(model_filename, user_message), file=sys.stderr, flush=True)
    prompt = "User: {0}\nAssistant:".format(user_message)
    model_path = os.path.join(_ensure_models_dir(), model_filename)

    if not model_filename:
        print("UTGPT_LOG: Error - No model selected", file=sys.stderr, flush=True)
        _emit_done(done_callback, ok=False, error_message="No model selected.")
        return False

    if not os.path.exists(model_path):
        print("UTGPT_LOG: Error - Model file not found at {0}".format(model_path), file=sys.stderr, flush=True)
        _emit_done(done_callback, ok=False, error_message="Model file not found: {0}".format(model_filename))
        return False

    cli_path = get_llama_cli_path()
    if not os.path.exists(cli_path):
        if LLAMA_CLI_ERROR:
            error_msg = "Missing llama-cli. Downloader error: " + str(LLAMA_CLI_ERROR)
        else:
            error_msg = "Inference engine is still downloading. Please try again in a moment."
        print("UTGPT_LOG: Error - llama-cli not found: {0}".format(error_msg), file=sys.stderr, flush=True)
        _emit_done(done_callback, ok=False, error_message=error_msg)
        return False

    process = None
    try:
        print("UTGPT_LOG: Launching llama-cli: {0}".format(cli_path), file=sys.stderr, flush=True)
        process = subprocess.Popen(
            [
                cli_path,
                "-m", model_path,
                "-p", prompt,
                "--temp", str(float(temperature)),
                "-n", str(int(max_tokens)),
                "--no-display-prompt",
                "-st",
                "--simple-io"
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        _register_process(process)
        print("UTGPT_LOG: llama-cli launched successfully, starting stdout read loop", file=sys.stderr, flush=True)

        output_buffer = ""
        started = False
        has_emitted_content = False
        
        while True:
            char = process.stdout.read(1)
            if not char:
                break
            
            output_buffer += char
            
            if not started:
                if "Assistant:" in output_buffer:
                    print("UTGPT_LOG: Detected 'Assistant:' boundary, starting token stream", file=sys.stderr, flush=True)
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

        if started and output_buffer:
            remaining = output_buffer.split("[ Prompt:")[0]
            if not has_emitted_content:
                remaining = remaining.lstrip()
            if remaining:
                print("UTGPT_LOG: Emitting remaining buffer content: {0}".format(repr(remaining)), file=sys.stderr, flush=True)
                _emit_token(token_callback, remaining)

        print("UTGPT_LOG: Waiting for llama-cli process to exit", file=sys.stderr, flush=True)
        exit_code = process.wait()
        print("UTGPT_LOG: llama-cli exited with code {0}".format(exit_code), file=sys.stderr, flush=True)
        if exit_code != 0:
            _emit_done(done_callback, ok=False, error_message="llama-cli exited with status {0}".format(exit_code))
            return False

        _emit_done(done_callback, ok=True, error_message="")
        return True
    except Exception as error:  # pragma: no cover - exercised from app runtime
        print("UTGPT_LOG: Exception in run_inference: {0}".format(error), file=sys.stderr, flush=True)
        _terminate_process(process)
        _emit_done(done_callback, ok=False, error_message=str(error))
        return False
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()
        _unregister_process(process)


def get_hardcoded_models():
    return HARDCODED_MODELS


def stop_all_inference():
    with INFERENCE_LOCK:
        processes = list(ACTIVE_PROCESSES)

    for process in processes:
        _terminate_process(process)


def initialize():
    _ensure_models_dir()
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

