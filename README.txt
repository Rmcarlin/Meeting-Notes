MEETING NOTES FOR WINDOWS

START
Double-click "Meeting Notes" (the shortcut with the teal microphone icon).
The icon also appears in the app header, window title and Windows taskbar.
If you move this folder, recreate the shortcut by running
"Create Meeting Notes Shortcut.ps1" from PowerShell in this folder.
The original launcher below also remains available.
Double-click "Start Meeting Notes.cmd" in this folder.
The first setup needs Python 3.13 and internet access. The first use of
each speech model downloads it into .models. Afterward, transcription
runs locally. No API key or paid transcription account is required.
Restart an already-open copy of the app to use this update.

RECORD A MEETING
1. Connect your headset before opening the app, or click Refresh audio devices.
2. Choose your mode:
   Online meeting + microphone: capture playback and your microphone.
   Room / microphone only: capture people the selected microphone can hear.
   Computer audio only: capture playback without your microphone.
3. For an online call, select the SAME playback device your call uses.
   Wear headphones to reduce duplicated sound entering the microphone.
4. Enter a title and click Start recording.
   Capture starts as soon as the devices open, before the speech model loads.
   Watch the timer and the source meters to confirm recording has started.
5. Click Stop & finish notes. Audio capture stops promptly while transcription
   finishes the saved audio, including the final partial chunk.
6. Open this folder to review your transcript, notes, subtitles and recordings.

QUALITY AND PERFORMANCE
Base (the default): balanced everyday transcription, with a wider search.
Small: a larger recognition model; uses more memory and CPU time.
Tiny: fastest recognition for slower computers, with lower accuracy.
The chosen model, mode and audio devices are remembered across restarts.
The recognition model changes transcript accuracy, not the recorded WAV quality.

Audio saves as lossless 16-bit PCM WAV at each device's reported native sample
rate, with up to two channels. Microphone and playback stay on separate tracks.
The app does not alter the saved sound with gain boosts or noise processing.
For better source audio, move the microphone closer, reduce background noise,
and avoid Bluetooth headset microphone mode when a better microphone is available.

The meters show digital signal levels during recording. Red means the signal
is near clipping: lower the microphone level in Windows or move it farther away.
Quiet playback is normal when nobody is speaking. A silent source cannot produce
a useful transcript. Recognition uses voice activity detection to skip silence.

Transcript jobs cover eight seconds with up to one second of surrounding audio
on either side. Word timestamps exclude context from neighboring jobs. The
first live text appears after about nine seconds plus model processing time.
If processing falls behind, the queue count shows the backlog; audio continues
to save independently. Stop waits for that saved speech to finish processing.

WORKSPACE
Live transcript: timestamps and audio source labels, updated during the meeting.
Follow live transcript: turn off to read older text without automatic scrolling.
Meeting notes: draft excerpts update during the meeting and are finalized on stop.
Copy text / Export: copy or export the currently visible transcript, notes or
library preview. Export to a location outside the meetings library.
Saved meetings: search by title or creation date, preview transcripts or notes,
open session folders, and delete a selected meeting after confirmation.
Ctrl+Enter starts/stops a session. Ctrl+E exports the current text.
The setup panel scrolls on smaller windows; the save location remains visible.
Closing an active session stops capture, finishes saving, then closes the window.
If a problem occurs, the window stays open so you can review it.

FILES AND AUTOMATIC SAVE
All meetings save under the "meetings" folder beside this program.
Each session has a folder with its date, time and title:
  transcript.txt   - Readable transcript sorted by timestamp after processing.
  transcript.jsonl - Append-only transcript journal, saved as speech arrives.
  transcript.srt   - Timed subtitles, generated when the session is finalized.
  notes.md         - Draft excerpts for actions, decisions and dates.
  meeting.json     - Status, model, devices, format, duration and reported issues.
  audio\Microphone_full.wav    - Continuous microphone track, if selected.
  audio\Meeting_audio_full.wav - Continuous playback track, if selected.
  audio\*_000000.wav, etc.     - Recognition chunks, with surrounding context.
Double-click a *_full.wav file in the folder to play that source's recording.
The continuous recordings do not repeat the overlapping recognition context.
Keeping both masters and recognition chunks uses a little over twice the audio
storage; allow about 3 GB per hour for two stereo 48 kHz sources.
Finished transcripts, notes, subtitles and metadata use atomic file replacement.
Saving remains automatic; no Save button is needed.

IMPORT A RECORDING
Import accepts WAV, MP3, M4A, MP4, FLAC and OGG. Progress updates as speech is
processed. Stop saves partial text after the current model operation returns.
A model download cannot be interrupted by Stop. The imported original is kept
at its existing location and is not copied into the session folder. meeting.json
records that location so you can find it later.

REVIEW AND RECOVERY
Draft notes contain matching transcript excerpts, not an AI-written summary.
Review them against the transcript; they can miss or misclassify commitments.
English recognition is supported. Individual speakers are not identified:
Microphone and Meeting audio label sources, not people. Noise, overlapping
speech and poor microphone placement still affect accuracy.
Sessions marked Interrupted / active may still be open in another app window,
or may have been interrupted. Check their audio and transcript journal.
Needs review means meeting.json contains errors. If recognition fails, retained
audio can be imported again. Older meetings remain accessible in the library.

DELETE A SAVED MEETING
Select a saved meeting and click Delete meeting. Confirmation identifies the
folder; accepting moves that entire session to the Windows Recycle Bin.
Restore it there and refresh the library if needed. Imported original recordings
outside the session folder are kept. Active sessions cannot be deleted.

BLUETOOTH / AUDIO TROUBLESHOOTING
Refresh devices after connecting a headset. Bluetooth devices may switch audio
profiles when their microphone is used. Try the laptop microphone with headset
playback, then match the meeting application's selected output again.
If no microphone is available, check Windows microphone privacy settings.
If a device disconnects, capture stops and any saved audio is finished and kept.
If you change playback devices mid-meeting, stop and start a new session.
Computer capture includes all apps using the selected playback device.
The app records only when you start a session; it does not join your call.

DEVELOPER SETUP
  py -3.13 -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  .venv\Scripts\python.exe app.py
  .venv\Scripts\python.exe -m unittest discover -s tests -v

Libraries/documentation:
https://github.com/SYSTRAN/faster-whisper
https://github.com/s0d3s/PyAudioWPatch
