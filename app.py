"""Standalone Windows meeting transcription, with a Tk desktop interface."""
import os
import json
import math
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from meeting_core import Meeting, MEETINGS_DIR, ROOT, atomic_text, draft_notes, saved_meetings, timestamp


class App(tk.Tk):
    def __init__(self):
        if os.name == "nt":
            import ctypes
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MeetingNotes.Desktop")
            except (AttributeError, OSError):
                pass
        super().__init__()
        self.title("Meeting Notes")
        icon = ROOT / "assets" / "meeting-notes.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon), default=str(icon))
            except tk.TclError:
                pass
        self.geometry("1240x880")
        self.minsize(520, 400)
        self.configure(bg="#f2f5f8")
        self.events = queue.Queue()
        self.stop_requested = threading.Event()
        self.busy = False
        self.meeting = None
        self.model_cache = {}
        self.inputs = []
        self.outputs = []
        self.session_started = None
        self.segment_count = 0
        self.word_count = 0
        self.saved_paths = {}
        self.selected_folder = None
        self.closing = False
        self.imported = False
        self.latest_levels = {}
        self.last_notes_update = 0
        try:
            self.settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
            if not isinstance(self.settings, dict):
                self.settings = {}
        except (OSError, ValueError):
            self.settings = {}
        self.meeting_title = tk.StringVar(value="My meeting")
        self.mode = tk.StringVar(value=self.settings.get("mode", "Online meeting + microphone"))
        self.model_name = tk.StringVar(value=self.settings.get("model", "base.en"))
        if self.mode.get() not in ("Online meeting + microphone", "Room / microphone only", "Computer audio only"):
            self.mode.set("Online meeting + microphone")
        if self.model_name.get() not in ("tiny.en", "base.en", "small.en"):
            self.model_name.set("base.en")
        self.follow_live = tk.BooleanVar(value=True)
        self.library_search = tk.StringVar()
        self.queue_label = tk.StringVar(value="No audio queued")
        self.model_hint = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Choose your audio sources, then start.")
        self.phase = tk.StringVar(value="Ready")
        self.elapsed = tk.StringVar(value="00:00:00")
        self.segment_label = tk.StringVar(value="0 words")
        self.workspace_title = tk.StringVar(value="Your meeting workspace")
        self.save_path = tk.StringVar(value=str(MEETINGS_DIR))
        self.library_path = tk.StringVar(value="Select a saved meeting to preview its transcript.")
        self._layout()
        self.mode.trace_add("write", lambda *_: self.update_mode())
        self.model_name.trace_add("write", lambda *_: self.update_model_hint())
        self.library_search.trace_add("write", lambda *_: self.refresh_library())
        self.update_mode()
        self.update_model_hint()
        self.refresh_devices()
        self.refresh_library()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Control-Return>", lambda e: self.stop() if self.busy else self.start())
        self.bind("<Control-e>", lambda e: self.export_current())
        self.after(100, self.poll)

    def _layout(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f2f5f8")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="#f2f5f8", foreground="#20334b", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="white")
        style.configure("Muted.TLabel", background="white", foreground="#627185", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7), background="#e9eef3", borderwidth=0)
        style.map("TButton", background=[("active", "#dce6ed")], foreground=[("disabled", "#8a96a4")])
        style.configure("Accent.TButton", background="#176b60", foreground="white")
        style.map("Accent.TButton", background=[("disabled", "#b9cec9"), ("active", "#12584f")], foreground=[("disabled", "#ffffff")])
        style.configure("Stop.TButton", background="#f9e9e7", foreground="#a33c32")
        style.configure("TCheckbutton", background="white", foreground="#627185", font=("Segoe UI", 9))
        style.configure("Level.Horizontal.TProgressbar", troughcolor="#e9eef3", background="#218577", borderwidth=0, thickness=7)
        style.configure("Clip.Horizontal.TProgressbar", troughcolor="#e9eef3", background="#c1503e", borderwidth=0, thickness=7)
        style.configure("TEntry", padding=6, fieldbackground="#f8fafc", bordercolor="#dce3ea")
        style.configure("TCombobox", padding=5, fieldbackground="#f8fafc", bordercolor="#dce3ea")
        style.map("TCombobox", fieldbackground=[("readonly", "#f8fafc")], selectbackground=[("readonly", "#f8fafc")], selectforeground=[("readonly", "#20334b")])
        style.configure("TNotebook", background="white", borderwidth=0)
        style.configure("TNotebook.Tab", width=18, padding=(22, 12),
                        background="#eaf0f5", font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "white")],
                  foreground=[("selected", "#176b60")],
                  expand=[("selected", (0, 0, 0, 0))], padding=[("selected", (22, 12))])
        # Remove the dotted focus outline that makes the clicked tab look different.
        style.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
        style.configure("TLabelframe", background="white", bordercolor="#e2e9ef", relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background="white", foreground="#20334b",
                        font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=34, font=("Segoe UI", 10), background="white", fieldbackground="white", borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=8, background="#f1f5f8")
        style.map("Treeview", background=[("selected", "#dceee8")], foreground=[("selected", "#16493f")])

        page = ttk.Frame(self)
        page.pack(fill="both", expand=True)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        canvas = tk.Canvas(page, highlightthickness=0, bd=0, background=self.cget("background"))
        vbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        hbar = ttk.Scrollbar(page, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        shell = ttk.Frame(canvas, padding=20)
        shell_window = canvas.create_window(0, 0, window=shell, anchor="nw")

        def fit_shell(_event=None):
            # Fill the window when it is large; keep the content's own size and scroll when it is small.
            width = max(canvas.winfo_width(), shell.winfo_reqwidth())
            height = max(canvas.winfo_height(), shell.winfo_reqheight())
            canvas.itemconfigure(shell_window, width=width, height=height)
            canvas.configure(scrollregion=(0, 0, width, height))
            for bar, size, req in ((vbar, canvas.winfo_height(), shell.winfo_reqheight()),
                                   (hbar, canvas.winfo_width(), shell.winfo_reqwidth())):
                bar.state(["!disabled"] if req > size else ["disabled"])

        def wheel(event):
            if isinstance(event.widget, (tk.Text, ttk.Treeview)):
                return
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

        canvas.bind("<Configure>", fit_shell)
        shell.bind("<Configure>", fit_shell)
        self.bind_all("<MouseWheel>", wheel, add="+")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        try:
            self.brandmark = tk.PhotoImage(file=str(ROOT / "assets" / "meeting-notes-48.png"))
            ttk.Label(header, image=self.brandmark).pack(side="left", padx=(0, 10))
        except tk.TclError:
            self.brandmark = None
        ttk.Label(header, text="Meeting Notes", font=("Segoe UI", 23, "bold")).pack(side="left")
        ttk.Label(header, text="LOCAL AUDIO  /  AUTOMATIC SAVE", font=("Segoe UI", 9, "bold"), foreground="#627185").pack(side="right")
        body = ttk.Frame(shell)
        body.grid(row=1, column=0, sticky="nsew")
        main = ttk.Frame(body)
        main.pack(fill="both", expand=True)
        workspace_header = ttk.Frame(main)
        workspace_header.pack(fill="x", pady=(0, 10))
        ttk.Label(workspace_header, textvariable=self.workspace_title, font=("Segoe UI", 18, "bold"),
                  wraplength=760).pack(side="left", anchor="w")
        self.lockable = []
        self.open_settings_button = ttk.Button(
            workspace_header, text="Settings", command=lambda: self.tabs.select(self.settings_tab))
        self.open_settings_button.pack(side="right", padx=(12, 0))
        controls = ttk.Frame(main, style="Card.TFrame", padding=(10, 8))
        controls.pack(fill="x", pady=(0, 12))
        self.start_button = ttk.Button(controls, text="Start recording", style="Accent.TButton", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="Stop & finish notes", style="Stop.TButton", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.import_button = ttk.Button(controls, text="Import recording...", command=self.import_audio)
        self.import_button.pack(side="left", padx=(8, 0))
        ttk.Label(controls, text="Ctrl+Enter to start or stop", style="Muted.TLabel").pack(side="right", padx=8)
        stats = ttk.Frame(main)
        stats.pack(fill="x", pady=(0, 10))
        for index, (label, value) in enumerate([("SESSION", self.phase), ("ELAPSED", self.elapsed), ("TRANSCRIPT", self.segment_label)]):
            stats.columnconfigure(index, weight=1, uniform="stats")
            card = ttk.Frame(stats, style="Card.TFrame", padding=(16, 11))
            card.grid(row=0, column=index, sticky="ew", padx=(0, 10 if index < 2 else 0))
            ttk.Label(card, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=value, style="Card.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(3, 0))
        status_card = ttk.Frame(main, style="Card.TFrame", padding=(14, 10))
        status_card.pack(fill="x", pady=(0, 10))
        ttk.Label(status_card, textvariable=self.status, style="Card.TLabel", wraplength=660).pack(anchor="w")
        ttk.Label(status_card, textvariable=self.queue_label, style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        self.progress = ttk.Progressbar(status_card, mode="determinate", maximum=100,
                                        style="Level.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(7, 0))
        levels = ttk.Frame(status_card, style="Card.TFrame")
        levels.pack(fill="x", pady=(7, 0))
        self.level_widgets = {}
        for index, source in enumerate(("Microphone", "Meeting audio")):
            levels.columnconfigure(index, weight=1, uniform="level")
            cell = ttk.Frame(levels, style="Card.TFrame")
            cell.grid(row=0, column=index, sticky="ew", padx=(0 if index else 0, 12 if index == 0 else 0))
            label = tk.StringVar(value=f"{source}  /  Idle")
            ttk.Label(cell, textvariable=label, style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
            meter = ttk.Progressbar(cell, style="Level.Horizontal.TProgressbar", maximum=60)
            meter.pack(fill="x")
            self.level_widgets[source] = (label, meter)
        toolbar = ttk.Frame(main, style="Card.TFrame", padding=(8, 5))
        toolbar.pack(fill="x", pady=(0, 0))
        ttk.Button(toolbar, text="Copy text", command=self.copy_current).pack(side="left")
        ttk.Button(toolbar, text="Export...", command=self.export_current).pack(side="left", padx=6)
        ttk.Checkbutton(toolbar, text="Follow live transcript", variable=self.follow_live).pack(side="right")
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)
        self.transcript = self._text_tab(self.tabs, "Live transcript")
        self.notes = self._text_tab(self.tabs, "Meeting notes")
        self._settings_tab(self.tabs)
        self._library_tab(self.tabs)
        self._set_text(self.transcript, "Ready when you are\n\nStart a meeting or import a recording to see the transcript here.\n\nMicrophone and Meeting audio identify the audio source. Individual speakers are not identified.")
        self._set_text(self.notes, "Your draft notes will appear here when processing finishes.\n\nReview matching excerpts for possible action items, decisions, and deadlines.")

    def _library_tab(self, tabs):
        frame = ttk.Frame(tabs, style="Card.TFrame", padding=16)
        tabs.add(frame, text="Saved meetings")
        bar = ttk.Frame(frame, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Meeting library", style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh_library).pack(side="right")
        ttk.Entry(bar, textvariable=self.library_search, width=22).pack(side="right", padx=8)
        ttk.Label(bar, text="Search", style="Muted.TLabel").pack(side="right")
        table = ttk.Frame(frame, style="Card.TFrame")
        table.pack(fill="x")
        self.library = ttk.Treeview(table, columns=("title", "date", "status"), show="headings", height=4, selectmode="browse")
        for key, label, width in [("title", "MEETING", 220), ("date", "CREATED", 145), ("status", "STATUS", 115)]:
            self.library.heading(key, text=label)
            self.library.column(key, width=width, minwidth=80)
        self.library.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table, command=self.library.yview)
        scrollbar.pack(side="right", fill="y")
        self.library.configure(yscrollcommand=scrollbar.set)
        self.library.bind("<<TreeviewSelect>>", self.select_saved_meeting)
        ttk.Label(frame, textvariable=self.library_path, style="Muted.TLabel", wraplength=650).pack(anchor="w", pady=10)
        actions = ttk.Frame(frame, style="Card.TFrame")
        actions.pack(fill="x", pady=(0, 10))
        self.library_buttons = []
        for label, filename in [("Transcript", "transcript.txt"), ("Notes", "notes.md"), ("Open folder", None)]:
            button = ttk.Button(actions, text=label, state="disabled", command=lambda name=filename: self.view_saved(name))
            button.pack(side="left", padx=(0, 6))
            self.library_buttons.append(button)
        self.delete_button = ttk.Button(actions, text="Delete meeting", style="Stop.TButton", state="disabled", command=self.delete_selected_meeting)
        self.delete_button.pack(side="right")
        self.library_preview = tk.Text(frame, wrap="word", font=("Segoe UI", 10), bg="#f8fafc", fg="#24334b", padx=14, pady=12, relief="flat", state="disabled")
        scroll = ttk.Scrollbar(frame, command=self.library_preview.yview)
        self.library_preview.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.library_preview.pack(fill="both", expand=True)

    def _settings_tab(self, tabs):
        frame = ttk.Frame(tabs, style="Card.TFrame", padding=22)
        tabs.add(frame, text="Settings")
        self.settings_tab = frame
        ttk.Label(frame, text="Settings", style="Card.TLabel", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Set up the meeting before you start recording. Preferences are remembered for next time.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w", pady=(4, 18))

        def row(parent, label, widget_factory, column, row_index, columnspan=1):
            cell = ttk.Frame(parent, style="Card.TFrame")
            cell.grid(row=row_index, column=column, columnspan=columnspan, sticky="ew",
                      padx=(0, 14 if column == 0 and columnspan == 1 else 0),
                      pady=(0, 12))
            ttk.Label(cell, text=label, style="Muted.TLabel",
                      font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
            widget = widget_factory(cell)
            widget.pack(fill="x")
            self.lockable.append(widget)
            return widget

        recording = ttk.LabelFrame(frame, text="  Recording  ", padding=(14, 14))
        recording.pack(fill="x", pady=(0, 14))
        recording.columnconfigure(0, weight=1)
        recording.columnconfigure(1, weight=1)
        row(recording, "MEETING TITLE", lambda parent: ttk.Entry(parent, textvariable=self.meeting_title), 0, 0, 2)
        row(recording, "CAPTURE MODE", lambda parent: ttk.Combobox(parent, state="readonly", textvariable=self.mode,
            values=["Online meeting + microphone", "Room / microphone only", "Computer audio only"]), 0, 1, 2)
        self.mic = row(recording, "MICROPHONE", lambda parent: ttk.Combobox(parent, state="readonly"), 0, 2)
        self.output = row(recording, "MEETING PLAYBACK",
                          lambda parent: ttk.Combobox(parent, state="readonly"), 1, 2)
        self.refresh_button = ttk.Button(recording, text="Refresh audio devices", command=self.refresh_devices)
        self.refresh_button.grid(row=3, column=0, sticky="w", pady=(0, 4))
        ttk.Label(recording, text="Wear headphones to reduce microphone echo. Computer audio captures all sound on the selected output.",
                  style="Muted.TLabel", wraplength=640).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        transcription = ttk.LabelFrame(frame, text="  Transcription  ", padding=(14, 14))
        transcription.pack(fill="x", pady=(0, 14))
        transcription.columnconfigure(0, weight=1)
        transcription.columnconfigure(1, weight=2)
        row(transcription, "ENGLISH SPEECH MODEL", lambda parent: ttk.Combobox(parent, state="readonly",
            textvariable=self.model_name, values=["tiny.en", "base.en", "small.en"]), 0, 0)
        ttk.Label(transcription, textvariable=self.model_hint, style="Muted.TLabel",
                  wraplength=420).grid(row=0, column=1, sticky="w", padx=(0, 10))

        storage = ttk.LabelFrame(frame, text="  Meeting files  ", padding=(14, 14))
        storage.pack(fill="x")
        storage.columnconfigure(0, weight=1)
        ttk.Label(storage, text="Transcripts, notes, and recorded audio save here automatically.",
                  style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 7))
        ttk.Entry(storage, textvariable=self.save_path, state="readonly").grid(
            row=1, column=0, sticky="ew", padx=(0, 12))
        ttk.Button(storage, text="Open current folder", command=self.open_folder).grid(
            row=1, column=1, padx=(0, 8))
        ttk.Button(storage, text="Open meetings", command=self.open_all_meetings).grid(row=1, column=2)

    def refresh_library(self):
        previous = self.selected_folder
        try:
            meetings = saved_meetings()
        except OSError as exc:
            self.library_path.set(f"Could not read saved meetings: {exc}")
            return
        self.library.delete(*self.library.get_children())
        self.saved_paths.clear()
        statuses = {"completed": "Saved", "completed_with_errors": "Needs review", "preparing": "Interrupted / active",
                    "recording": "Interrupted / active", "transcribing": "Interrupted / active", "canceled": "Partial import"}
        query = self.library_search.get().strip().casefold()
        meetings = [item for item in meetings if query in item["title"].casefold() or query in item["created"].casefold()]
        selected = None
        for index, item in enumerate(meetings):
            try:
                date = datetime.fromisoformat(item["created"]).astimezone().strftime("%b %d, %Y  %I:%M %p")
            except ValueError:
                date = "Date unavailable"
            iid = str(index)
            self.saved_paths[iid] = item["folder"]
            self.library.insert("", "end", iid=iid, values=(item["title"], date, statuses.get(item["status"], "Check files")))
            if item["folder"] == previous:
                selected = iid
        if meetings:
            self.library.selection_set(selected or "0")
            self.select_saved_meeting()
        else:
            self.selected_folder = None
            self.library_path.set("No matching meetings." if query else "No saved meetings yet. Finished sessions will appear here.")
            self._set_text(self.library_preview, "Try a different title or date." if query else "Your saved transcripts and notes will be available here after your first session.")
            for button in self.library_buttons:
                button.configure(state="disabled")
            self.delete_button.configure(state="disabled")

    def select_saved_meeting(self, event=None):
        selection = self.library.selection()
        if not selection or selection[0] not in self.saved_paths:
            return
        self.selected_folder = self.saved_paths[selection[0]]
        self.library_path.set(str(self.selected_folder))
        for button in self.library_buttons:
            button.configure(state="normal")
        self.update_delete_button()
        self.view_saved("transcript.txt")

    def update_delete_button(self):
        active = self.busy and self.meeting is not None and self.selected_folder == self.meeting.folder
        self.delete_button.configure(state="normal" if self.selected_folder is not None and not active else "disabled")

    def delete_selected_meeting(self):
        folder = self.selected_folder
        if folder is None:
            return
        if self.busy and self.meeting is not None and folder == self.meeting.folder:
            messagebox.showinfo("Meeting is active", "Stop this meeting and wait for processing to finish before deleting it.")
            return
        selection = self.library.selection()
        title = self.library.item(selection[0], "values")[0] if selection else folder.name
        confirmed = messagebox.askyesno(
            "Delete saved meeting?",
            f'Move "{title}" to the Recycle Bin?\n\n'
            "This removes the transcript, draft notes, recorded audio, and other files in this meeting folder.\n\n"
            f"{folder}\n\nYou can restore it from the Windows Recycle Bin.",
            icon="warning", default=messagebox.NO, parent=self)
        if not confirmed:
            return
        try:
            from meeting_storage import delete_saved_meeting
            active_folder = self.meeting.folder if self.busy and self.meeting is not None else None
            delete_saved_meeting(folder, active_folder=active_folder)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not delete meeting", str(exc))
            self.refresh_library()
            return
        if self.meeting is not None and self.meeting.folder == folder:
            self.meeting = None
            self.workspace_title.set("Your meeting workspace")
            self.save_path.set(str(MEETINGS_DIR))
            self.phase.set("Ready")
            self.elapsed.set("00:00:00")
            self.word_count = self.segment_count = 0
            self.segment_label.set("0 words")
            self._set_text(self.transcript, "Meeting deleted. Start a new meeting or import a recording.")
            self._set_text(self.notes, "The selected meeting and its notes were moved to the Recycle Bin.")
        self.selected_folder = None
        self.refresh_library()
        if not self.busy:
            self.status.set("Meeting moved to the Recycle Bin. Other saved meetings are available in the library.")

    def view_saved(self, filename):
        if self.selected_folder is None:
            return
        if filename is None:
            self._open_path(self.selected_folder)
            return
        try:
            content = (self.selected_folder / filename).read_text(encoding="utf-8")
            self._set_text(self.library_preview, content or "No speech was saved for this meeting.")
        except OSError as exc:
            self._set_text(self.library_preview, f"Could not open {filename}: {exc}")

    def _text_tab(self, tabs, name):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text=name)
        text = tk.Text(frame, wrap="word", font=("Segoe UI", 11), bg="white", fg="#24334b",
                       padx=18, pady=16, relief="flat", state="disabled")
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        return text

    def _set_text(self, widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", content)
        widget.configure(state="disabled")

    def update_model_hint(self):
        hints = {"tiny.en": "Fastest • lower accuracy. Useful on slower PCs.",
                 "base.en": "Balanced • recommended for everyday meetings.",
                 "small.en": "Higher accuracy • needs more processing time."}
        self.model_hint.set(hints.get(self.model_name.get(), "") + " First use downloads the model.")

    def update_mode(self):
        if self.busy:
            return
        self.mic.configure(state="disabled" if self.mode.get() == "Computer audio only" else "readonly")
        self.output.configure(state="disabled" if self.mode.get() == "Room / microphone only" else "readonly")

    def save_settings(self):
        self.settings.update({"mode": self.mode.get(), "model": self.model_name.get(),
                              "microphone": self.mic.get(), "output": self.output.get()})
        try:
            atomic_text(ROOT / "settings.json", json.dumps(self.settings, indent=2))
        except OSError:
            pass  # Recording must still work if preferences cannot be saved.

    def _selected_text_widget(self):
        selected = self.tabs.select()
        for widget in (self.transcript, self.notes, self.library_preview):
            if str(widget.master) == selected:
                return widget
        return None

    def current_text(self):
        widget = self._selected_text_widget()
        return widget.get("1.0", "end-1c") if widget is not None else ""

    def copy_current(self):
        content = self.current_text()
        if content.strip():
            self.clipboard_clear()
            self.clipboard_append(content)
            self.queue_label.set("Text copied to clipboard.")

    def export_current(self):
        content = self.current_text()
        if not content.strip():
            return
        notes = self._selected_text_widget() is self.notes
        path = filedialog.asksaveasfilename(title="Export current text", defaultextension=".md" if notes else ".txt",
                                           initialfile="meeting-notes.md" if notes else "transcript.txt",
                                           filetypes=[("Markdown", "*.md"), ("Text", "*.txt")] if notes else [("Text", "*.txt"), ("Markdown", "*.md")])
        if path:
            from pathlib import Path
            destination = Path(path).resolve()
            # Exporting a live preview into storage could overwrite an active journal.
            if destination.is_relative_to(MEETINGS_DIR.resolve()):
                messagebox.showinfo("Choose an export location", "Choose a folder outside the meetings library to keep the saved originals intact.")
                return
            try:
                atomic_text(destination, content + "\n")
                self.queue_label.set(f"Exported to {path}")
            except OSError as exc:
                messagebox.showerror("Could not export", str(exc))

    def refresh_devices(self):
        try:
            from audio_capture import devices
            self.inputs, self.outputs, default_in, default_out = devices()
            for widget, items, default, key in [(self.mic, self.inputs, default_in, "microphone"), (self.output, self.outputs, default_out, "output")]:
                previous = widget.get() or self.settings.get(key)
                widget["values"] = [f"{d['name']}  [{d['index']}]" for d in items]
                if items:
                    names = list(widget["values"])
                    chosen = next((i for i, name in enumerate(names) if name == previous), None)
                    if chosen is None and previous:
                        chosen = next((i for i, name in enumerate(names) if name.rsplit("  [", 1)[0] == previous.rsplit("  [", 1)[0]), None)
                    widget.current(chosen if chosen is not None else next((i for i, d in enumerate(items) if d["index"] == default), 0))
                else:
                    widget.set("No devices found")
        except Exception as exc:
            self.status.set(f"Audio devices unavailable: {exc}. You can still import a recording.")

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.lockable:
            widget.configure(state="disabled" if busy else ("readonly" if isinstance(widget, ttk.Combobox) else "normal"))
        for button in [self.start_button, self.import_button, self.refresh_button]:
            button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")
        self.update_delete_button()
        self.update_mode()

    def start(self):
        if self.busy:
            return
        selections = []
        if self.mode.get() != "Computer audio only":
            if not self.inputs or self.mic.current() < 0:
                messagebox.showinfo("Choose a microphone", "Connect a microphone and refresh devices.")
                return
            selections.append(("Microphone", self.inputs[self.mic.current()]))
        if self.mode.get() != "Room / microphone only":
            if not self.outputs or self.output.current() < 0:
                messagebox.showinfo("Choose playback", "Connect a playback device and refresh devices.")
                return
            selections.append(("Meeting audio", self.outputs[self.output.current()]))
        self.begin(selections, None)

    def import_audio(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title="Choose a recording", filetypes=[("Audio recordings", "*.wav *.mp3 *.m4a *.flac *.mp4 *.ogg"), ("All files", "*.*")])
        if path:
            self.begin([], path)

    def begin(self, selections, imported):
        if self.busy:
            return
        try:
            self.meeting = Meeting(self.meeting_title.get())
        except OSError as exc:
            messagebox.showerror("Could not create meeting", str(exc))
            return
        self.stop_requested.clear()
        self.save_settings()
        self.imported = bool(imported)
        self.latest_levels.clear()
        self.queue_label.set("Waiting for speech model" if imported else "Starting audio capture")
        self.progress["value"] = 0
        self.set_busy(True)
        self.phase.set("Preparing")
        self.elapsed.set("00:00:00")
        self.segment_count = 0
        self.word_count = 0
        self.segment_label.set("0 words")
        self.session_started = None
        self.workspace_title.set(self.meeting.title)
        self.save_path.set(str(self.meeting.folder))
        self.tabs.select(0)
        self._set_text(self.transcript, "")
        self._set_text(self.notes, "Notes will be ready when processing finishes.")
        self.status.set("Preparing imported recording..." if imported else "Opening your selected audio devices...")
        threading.Thread(target=self.run_session, args=(self.meeting, self.model_name.get(), selections, imported), daemon=True).start()

    def run_session(self, meeting, model_name, selections, imported):
        from recording_session import SessionRunner
        SessionRunner(self.events, self.stop_requested, self.model_cache).run(
            meeting, model_name, selections, imported)

    def stop(self):
        if not self.busy or self.stop_requested.is_set():
            return
        self.stop_requested.set()
        self.phase.set("Finishing")
        self.stop_button.configure(state="disabled")
        self.status.set("Stopping import after the current speech segment; partial text will be saved." if self.imported else
                        "Stopping capture and finishing saved speech. Model loading and queued audio may take a moment.")

    def poll(self):
        try:
            # Bound each update so a busy model cannot starve window input.
            deadline = time.monotonic() + 0.025
            while time.monotonic() < deadline:
                kind, payload = self.events.get_nowait()
                if kind == "entry":
                    self.segment_count += 1
                    self.word_count += len(payload.text.split())
                    self.segment_label.set(f"{self.word_count:,} words")
                    self.transcript.configure(state="normal")
                    self.transcript.insert("end", f"[{timestamp(payload.start)}] {payload.source}: {payload.text}\n\n")
                    if self.follow_live.get():
                        self.transcript.see("end")
                    self.transcript.configure(state="disabled")
                elif kind == "level":
                    source, rms, peak = payload
                    self.latest_levels[source] = (rms, peak, time.monotonic())
                elif kind == "recording_started":
                    self.session_started = payload
                    self.queue_label.set("Recording lossless WAV • speech processing runs separately")
                elif kind == "capture_stopped":
                    self.elapsed.set(timestamp(payload))
                    self.session_started = None
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind in ("status", "warning"):
                    self.status.set(payload)
                elif kind == "phase":
                    if payload == "Transcribing" and not self.stop_requested.is_set():
                        self.session_started = time.monotonic()
                    self.phase.set("Finishing" if self.stop_requested.is_set() else payload)
                elif kind == "processing":
                    self.queue_label.set(f"{payload} audio chunk(s) processing / queued • audio saved independently" if payload else
                                         "Transcript is up to date • waiting for the next audio chunk" if not self.imported else "Import processing finished")
                elif kind == "done":
                    meeting, errors = payload
                    self.freeze_timer()
                    self.set_busy(False)
                    partial = meeting.details.get("transcription_canceled", False)
                    self.phase.set("Needs review" if errors else "Partial import" if partial else "Saved")
                    self.progress["value"] = 100 if not errors and not partial else self.progress["value"]
                    self.queue_label.set(f"{len(meeting.entries):,} transcript segments • saved locally")
                    self._set_text(self.notes, draft_notes(meeting.entries, meeting.title))
                    ordered = sorted(meeting.entries, key=lambda e: e.start)
                    self._set_text(self.transcript, "\n\n".join(f"[{timestamp(e.start)}] {e.source}: {e.text}" for e in ordered) or "No speech detected.")
                    if errors:
                        self.status.set(f"Finished with {len(errors)} issue(s). Details are in meeting.json.")
                        self.closing = False
                        messagebox.showwarning("Meeting needs review", "\n\n".join(errors[:3]))
                    else:
                        self.status.set("Partial import saved. Your original recording is unchanged." if partial else
                                        "Saved: transcript, subtitles, draft notes and recorded audio. Open the folder below to review.")
                    self.selected_folder = meeting.folder
                    self.refresh_library()
                    if self.closing:
                        self.destroy()
                        return
        except queue.Empty:
            pass
        if self.session_started is not None:
            self.elapsed.set(timestamp(time.monotonic() - self.session_started))
        now = time.monotonic()
        for source, (label, meter) in self.level_widgets.items():
            rms, peak, updated = self.latest_levels.get(source, (0, 0, 0))
            if now - updated > 0.6 or not self.busy:
                rms = peak = 0
            db = 20 * math.log10(max(rms, 0.000001))
            meter["value"] = max(0, min(60, db + 60))
            meter.configure(style="Clip.Horizontal.TProgressbar" if peak >= 0.98 else "Level.Horizontal.TProgressbar")
            state = "Too loud - lower input" if peak >= 0.98 else f"{db:.0f} dBFS" if rms > 0.0001 else "Quiet" if self.busy and source in self.latest_levels else "Idle"
            label.set(f"{source}  /  {state}")
        if self.busy and self.meeting and self.segment_count and now - self.last_notes_update > 3:
            self._set_text(self.notes, draft_notes(list(self.meeting.entries), self.meeting.title))
            self.last_notes_update = now
        self.after(100, self.poll)

    def freeze_timer(self):
        if self.session_started is not None:
            self.elapsed.set(timestamp(time.monotonic() - self.session_started))
            self.session_started = None

    def _open_path(self, path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def open_folder(self):
        self._open_path(self.meeting.folder if self.meeting else MEETINGS_DIR)

    def open_all_meetings(self):
        self._open_path(MEETINGS_DIR)

    def close(self):
        if self.busy:
            self.closing = True
            self.stop()
            self.title("Meeting Notes — saving before closing")
            self.status.set("Saving before closing. The window will close when processing finishes.")
        else:
            self.save_settings()
            self.destroy()


if __name__ == "__main__":
    App().mainloop()
