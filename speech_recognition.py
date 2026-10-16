"""Local recognition settings and optional NVIDIA acceleration."""
import ctypes
import os
from pathlib import Path
import sys

from meeting_core import ROOT

DEFAULT_MODEL = "large-v3-turbo"
MODEL_CHOICES = ("large-v3-turbo", "medium.en", "small.en", "base.en", "tiny.en")
RECOGNITION_VERSION = 2
_dll_directories = []


def gpu_available():
    import ctranslate2

    try:
        if not ctranslate2.get_cuda_device_count():
            return False
        if os.name == "nt":
            # Keep handles alive: closing them removes the DLL search directories.
            libraries = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
            if not _dll_directories:
                for directory in libraries.glob("*/bin"):
                    _dll_directories.append(os.add_dll_directory(str(directory)))
            for name in ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll"):
                ctypes.WinDLL(name)
        return True
    except (OSError, RuntimeError):
        return False


def load_model(name, status):
    # Keep model downloads and their cache beside the application.
    os.environ.setdefault("HF_HOME", str(ROOT / ".models" / "cache"))
    os.environ.setdefault("HF_XET_CACHE", str(ROOT / ".models" / "cache" / "xet"))
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    # A downloaded model should start without contacting the model host.
    try:
        model_path = download_model(name, cache_dir=str(ROOT / ".models"), local_files_only=True)
    except OSError:
        model_path = name
    options = dict(cpu_threads=max(1, min(8, (os.cpu_count() or 4) - 2)),
                   download_root=str(ROOT / ".models"))
    if gpu_available():
        try:
            status("Loading speech recognition on the NVIDIA GPU.")
            return WhisperModel(model_path, device="cuda", compute_type="int8_float16", **options)
        except (OSError, RuntimeError):
            status("GPU recognition unavailable. Loading the same model on the CPU; this may take longer.")
    return WhisperModel(model_path, device="cpu", compute_type="int8", **options)


def transcription_options(model_name, vocabulary="", full_recording=False):
    return dict(
        language="en", beam_size=1 if model_name == "tiny.en" else 5,
        vad_filter=True,
        vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 2000,
                        "speech_pad_ms": 400},
        word_timestamps=True,
        condition_on_previous_text=full_recording,
        hotwords=vocabulary.strip()[:1000] or None,
    )
