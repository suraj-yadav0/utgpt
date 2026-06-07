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

try:
    import pyotherside
except ImportError:  # pragma: no cover - only unavailable outside the app runtime
    pyotherside = None


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODELS_DIR = os.path.expanduser("~/Documents/UTGPT/models")
LLAMA_CLI_PATH = os.path.join(APP_DIR, "assets", "llama-cli")
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


def download_model(name, url, progress_callback=None):
    models_dir = _ensure_models_dir()
    filename = os.path.basename(url.split("?", 1)[0]) or (name + ".gguf")
    destination = os.path.join(models_dir, filename)
    temp_destination = destination + ".part"

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "UTGPT/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response, open(temp_destination, "wb") as output_file:
            total_size = int(response.headers.get("Content-Length", "0") or "0")
            bytes_written = 0
            _emit_download_progress(progress_callback, name, filename, 0.0)

            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                output_file.write(chunk)
                bytes_written += len(chunk)

                if total_size > 0:
                    progress = min(float(bytes_written) / float(total_size), 1.0)
                    _emit_download_progress(progress_callback, name, filename, progress)

        os.replace(temp_destination, destination)
        _emit_download_progress(progress_callback, name, filename, 1.0)
        _emit_download_complete(progress_callback, name, filename)
        return filename
    except Exception as error:  # pragma: no cover - exercised from app runtime
        if os.path.exists(temp_destination):
            os.remove(temp_destination)
        _emit_download_error(progress_callback, name, str(error))
        return ""


def run_inference(model_filename, user_message, temperature, max_tokens, token_callback=None, done_callback=None):
    prompt = "User: {0}\nAssistant:".format(user_message)
    model_path = os.path.join(_ensure_models_dir(), model_filename)

    if not model_filename:
        _emit_done(done_callback, ok=False, error_message="No model selected.")
        return False

    if not os.path.exists(model_path):
        _emit_done(done_callback, ok=False, error_message="Model file not found: {0}".format(model_filename))
        return False

    if not os.path.exists(LLAMA_CLI_PATH):
        _emit_done(done_callback, ok=False, error_message="Missing llama-cli at assets/llama-cli.")
        return False

    process = None
    try:
        process = subprocess.Popen(
            [
                LLAMA_CLI_PATH,
                "-m", model_path,
                "-p", prompt,
                "--temp", str(float(temperature)),
                "-n", str(int(max_tokens)),
                "--no-display-prompt"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        _register_process(process)

        for line in iter(process.stdout.readline, ""):
            text = line.rstrip()
            if text:
                _emit_token(token_callback, text)

        exit_code = process.wait()
        if exit_code != 0:
            _emit_done(done_callback, ok=False, error_message="llama-cli exited with status {0}".format(exit_code))
            return False

        _emit_done(done_callback, ok=True, error_message="")
        return True
    except Exception as error:  # pragma: no cover - exercised from app runtime
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
    return {
        "ready": True,
        "modelsDir": MODELS_DIR,
        "llamaCliPath": LLAMA_CLI_PATH
    }
