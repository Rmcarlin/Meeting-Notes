"""Capture and speech processing orchestration, independent of the desktop UI."""
from pathlib import Path
from datetime import datetime
import queue
import threading
import time

from audio_capture import AudioJob, Capture
from meeting_core import Entry, ROOT
from speech_recognition import load_model, transcription_options


def segment_entry(segment, job):
    """Use word times to avoid transcribing the previous chunk's context twice."""
    words = getattr(segment, "words", None)
    if words:
        words = [w for w in words if (w.start + w.end) / 2 >= job.trim_before
                 and (not job.duration or (w.start + w.end) / 2 < job.trim_before + job.duration)]
        if not words:
            return None
        text = "".join(w.word for w in words).strip()
        start, end = words[0].start, words[-1].end
    else:
        if segment.end <= job.trim_before or (job.duration and segment.start >= job.trim_before + job.duration):
            return None
        text = segment.text.strip()
        start, end = segment.start, segment.end
    if not text:
        return None
    return Entry(max(0, job.offset + max(start, job.trim_before)),
                 max(0, job.offset + end), job.source, text)


class SessionRunner:
    def __init__(self, events, stop_requested, cache, model_factory=None, capture_factory=Capture):
        self.events = events
        self.stop_requested = stop_requested
        self.cache = cache
        self.model_factory = model_factory
        self.capture_factory = capture_factory

    def run(self, meeting, model_name, selections, imported, vocabulary="", refine=True):
        jobs = queue.Queue()
        capture = None
        processor = None
        errors = []
        failed = threading.Event()
        canceled = threading.Event()
        started = time.monotonic()
        capture_duration = 0.0
        recording_started = None

        def emit(kind, value):
            self.events.put((kind, value))

        def report(message):
            # Driver callbacks can report the same interruption many times.
            if message not in errors:
                errors.append(message)
                emit("warning", message)

        def process():
            try:
                if model_name not in self.cache:
                    emit("status", "Loading speech model. First use may download it; live audio is already being saved."
                         if not imported else "Loading speech model for your imported recording.")
                    if self.model_factory is None:
                        model = load_model(model_name, lambda message: emit("status", message))
                    else:
                        model = self.model_factory(model_name, device="cpu", compute_type="int8",
                                                   download_root=str(ROOT / ".models"))
                    self.cache.clear()
                    self.cache[model_name] = model
                model = self.cache[model_name]
                meeting.details["recognition_device"] = getattr(getattr(model, "model", None), "device", "cpu")
                emit("status", "Transcribing locally. Audio and transcripts save automatically.")
                while True:
                    job = jobs.get()
                    if job is None:
                        break
                    if imported and self.stop_requested.is_set():
                        canceled.set()
                        break
                    emit("processing", jobs.qsize() + 1)
                    try:
                        segments, info = model.transcribe(
                            str(job.path), **transcription_options(model_name, vocabulary, bool(imported)))
                        for segment in segments:
                            if imported and self.stop_requested.is_set():
                                canceled.set()
                                break
                            entry = segment_entry(segment, job)
                            if entry:
                                meeting.add(entry)
                                emit("entry", entry)
                            if imported and info.duration:
                                emit("progress", min(99, segment.end / info.duration * 100))
                    except Exception as exc:
                        report(f"Could not transcribe {job.path.name}: {exc}. The original audio is available for retry.")
                    emit("processing", jobs.qsize())
                if not imported and refine:
                    review_recordings(model)
            except Exception as exc:
                report(f"Speech model could not load: {exc}. Any captured audio has been retained.")
                failed.set()

        def review_recordings(model):
            # Capture has stopped and all live jobs have drained before this runs.
            # Review each continuous track rather than stitching short clips.
            masters = []
            for audio_format in capture.formats:
                source = audio_format["source"]
                path = meeting.folder / "audio" / f"{source.replace(' ', '_')}_full.wav"
                if path.exists():
                    masters.append((source, path))
            if not masters:
                return
            emit("phase", "Refining")
            emit("status", "Improving the final transcript from the complete recordings. Live text is kept for recovery.")
            revised = list(meeting.entries)
            reviewed = []
            for index, (source, path) in enumerate(masters):
                try:
                    offset = getattr(capture, "source_offsets", {}).get(source, 0.0)
                    job = AudioJob(path, offset, source)
                    segments, info = model.transcribe(
                        str(path), **transcription_options(model_name, vocabulary, full_recording=True))
                    entries = []
                    for segment in segments:
                        entry = segment_entry(segment, job)
                        if entry:
                            entries.append(entry)
                        if info.duration:
                            emit("progress", min(99, (index + segment.end / info.duration) / len(masters) * 100))
                    if not entries and any(entry.source == source for entry in revised):
                        raise RuntimeError("Review found no speech; the live transcript has been kept")
                    revised = [entry for entry in revised if entry.source != source] + entries
                    reviewed.append(source)
                except Exception as exc:
                    report(f"Could not improve {source}: {exc}. Live text and audio have been kept.")
            if reviewed:
                try:
                    meeting.replace_entries(revised)
                    meeting.details["reviewed_sources"] = reviewed
                except Exception as exc:
                    report(f"Could not save the reviewed transcript: {exc}. Check the retained journals.")

        try:
            meeting.details.update({"model": model_name, "imported_path": str(imported) if imported else None,
                                    "vocabulary": vocabulary, "full_recording_review": bool(refine and not imported)})
            if imported:
                jobs.put(AudioJob(Path(imported), 0, "Imported recording"))
                emit("phase", "Transcribing")
            else:
                capture = self.capture_factory(selections, meeting.folder / "audio", jobs, report,
                                              levels=lambda source, rms, peak: emit("level", (source, rms, peak)))
                capture.start()
                recording_started = time.monotonic()
                meeting.details["audio_formats"] = capture.formats
                emit("recording_started", capture.started)
                emit("phase", "Recording")
            meeting.finish("transcribing" if imported else "recording")
            processor = threading.Thread(target=process, daemon=True)
            processor.start()
            if not imported:
                while not self.stop_requested.wait(0.1):
                    if capture.failed.is_set() or failed.is_set():
                        break
                    if any(not stream.is_active() for stream in capture.streams):
                        report("An audio device disconnected or stopped. Check the connection before starting another session.")
                        break
        except Exception as exc:
            report(f"Could not start recording: {exc}")
        finally:
            if capture:
                try:
                    capture.stop()
                except Exception as exc:
                    report(f"Audio shutdown: {exc}")
                if recording_started is not None:
                    capture_duration = time.monotonic() - recording_started
                emit("capture_stopped", capture_duration)
                meeting.details["source_start_offsets"] = getattr(capture, "source_offsets", {})
            if processor:
                if not imported or self.stop_requested.is_set():
                    emit("phase", "Finishing")
                jobs.put(None)
                processor.join()
            meeting.errors = errors
            meeting.details.update({"duration_seconds": capture_duration if not imported else time.monotonic() - started,
                                    "duration_kind": "recording" if not imported else "processing",
                                    "transcription_canceled": canceled.is_set(),
                                    "finished": datetime.now().astimezone().isoformat()})
            state = "completed_with_errors" if errors else "canceled" if canceled.is_set() else "completed"
            try:
                meeting.finish(state)
            except Exception as exc:
                report(f"Could not finish saving files: {exc}. Check available disk space; audio and journal may still be available.")
            emit("done", (meeting, errors))
