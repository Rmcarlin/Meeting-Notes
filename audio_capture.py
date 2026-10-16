"""WASAPI microphone/output capture. No devices open until start() is called."""
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import time
import wave
import numpy as np

import pyaudiowpatch as pa


@dataclass
class AudioJob:
    path: Path
    offset: float
    source: str
    trim_before: float = 0.0
    duration: float = 0.0


def devices():
    with pa.PyAudio() as audio:
        wasapi = audio.get_host_api_info_by_type(pa.paWASAPI)
        inputs = []
        for i in range(audio.get_device_count()):
            d = audio.get_device_info_by_index(i)
            if d["hostApi"] == wasapi["index"] and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
                inputs.append(d)
        outputs = list(audio.get_loopback_device_info_generator())
        try:
            default_output = audio.get_default_wasapi_loopback()["index"]
        except (OSError, LookupError):
            default_output = None
        return inputs, outputs, wasapi.get("defaultInputDevice"), default_output


class Capture:
    def __init__(self, selections, folder: Path, jobs: queue.Queue, report, levels=None,
                 overlap_seconds=2.0, chunk_seconds=20.0):
        self.selections = selections
        self.folder = folder
        self.jobs = jobs
        self.report = report
        self.audio = None
        self.streams = []
        self.workers = []
        self.buffers = []
        self.failed = threading.Event()
        self.started = 0.0
        self.levels = levels
        self.overlap_seconds = overlap_seconds
        self.chunk_seconds = chunk_seconds
        self.formats = []
        self.source_offsets = {}

    def start(self):
        self.audio = pa.PyAudio()
        try:
            for source, device in self.selections:
                rate = int(device["defaultSampleRate"])
                channels = min(2, int(device["maxInputChannels"]))
                self.formats.append({"source": source, "device": device["name"],
                                     "sample_rate": rate, "channels": channels, "bits": 16})
                buffer = queue.Queue(maxsize=512)
                self.buffers.append(buffer)

                def callback(data, count, info, status, target=buffer, label=source):
                    if status:
                        self.report(f"{label}: audio driver reported an interruption ({status}).")
                    try:
                        target.put_nowait((data, time.monotonic()))
                    except queue.Full:
                        self.failed.set()
                        self.report(f"{label}: capture could not keep up. Recording stopped; audio may be incomplete.")
                        return (None, pa.paAbort)
                    return (None, pa.paContinue)

                stream = self.audio.open(format=pa.paInt16, channels=channels, rate=rate,
                                         input=True, input_device_index=int(device["index"]),
                                         frames_per_buffer=1024, stream_callback=callback, start=False)
                self.streams.append(stream)
                worker = threading.Thread(target=self._write, args=(buffer, source, rate, channels), daemon=True)
                self.workers.append(worker)
            self.started = time.monotonic()
            for worker in self.workers:
                worker.start()
            for stream in self.streams:
                stream.start_stream()
        except Exception:
            self.stop()
            raise

    def _write(self, buffer, source, rate, channels):
        frames = bytearray()
        chunk_size = int(rate * self.chunk_seconds) * channels * 2
        offset = 0.0
        sequence = 0
        first = True
        context = b""
        frame_bytes = channels * 2
        overlap_size = int(rate * self.overlap_seconds) * frame_bytes
        last_level = 0.0
        master = None

        def save(data, primary_size=None):
            nonlocal sequence, offset, context
            if primary_size is None:
                primary_size = len(data)
            path = self.folder / f"{source.replace(' ', '_')}_{sequence:06}.wav"
            prefix = len(context) / (rate * frame_bytes)
            with wave.open(str(path), "wb") as out:
                out.setnchannels(channels)
                out.setsampwidth(2)
                out.setframerate(rate)
                out.writeframes(context + data)
            self.jobs.put(AudioJob(path, offset - prefix, source, prefix,
                                   primary_size / (rate * frame_bytes)))
            if overlap_size:
                context = (context + data[:primary_size])[-overlap_size:]
            offset += primary_size / (rate * channels * 2)
            sequence += 1

        try:
            master = wave.open(str(self.folder / f"{source.replace(' ', '_')}_full.wav"), "wb")
            master.setnchannels(channels)
            master.setsampwidth(2)
            master.setframerate(rate)
            while True:
                item = buffer.get()
                if item is None:
                    break
                data, arrived = item
                # Keep an immediately playable lossless master independent of inference.
                # Keep the WAV header current as blocks are written.
                master.writeframes(data)
                if self.levels and arrived - last_level >= 0.1:
                    samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
                    if samples.size:
                        peak = float(np.max(np.abs(samples))) / 32768
                        rms = float(np.sqrt(np.mean(samples * samples))) / 32768
                        self.levels(source, rms, peak)
                    last_level = arrived
                if first:
                    offset = max(0, arrived - self.started - len(data) / (rate * channels * 2))
                    self.source_offsets[source] = offset
                    first = False
                frames.extend(data)
                # Give boundary words context on both sides. Only the central
                # interval belongs to each job; the master never overlaps.
                while len(frames) >= chunk_size + overlap_size:
                    save(bytes(frames[:chunk_size + overlap_size]), chunk_size)
                    del frames[:chunk_size]
            if frames:
                save(bytes(frames))
        except Exception as exc:
            self.failed.set()
            self.report(f"Could not save {source} audio: {exc}")
        finally:
            if master is not None:
                try:
                    master.close()
                except Exception as exc:
                    self.failed.set()
                    self.report(f"Could not finish {source} recording: {exc}")

    def stop(self):
        for stream in self.streams:
            try:
                if stream.is_active():
                    stream.stop_stream()
            except Exception as exc:
                self.report(f"Could not stop an audio stream cleanly: {exc}")
            finally:
                try:
                    stream.close()
                except Exception as exc:
                    self.report(f"Could not close an audio stream cleanly: {exc}")
        self.streams.clear()
        for buffer, worker in zip(self.buffers, self.workers):
            if worker.is_alive():
                # A full queue whose writer failed must not block shutdown.
                while worker.is_alive():
                    try:
                        buffer.put(None, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        for worker in self.workers:
            if worker.is_alive():
                worker.join()
        if self.audio is not None:
            self.audio.terminate()
            self.audio = None
