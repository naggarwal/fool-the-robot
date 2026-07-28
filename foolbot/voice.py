"""Three-tier voice system for the Fool the Robot booth (PRD 5.4).

WHY THREE TIERS: a cloud dependency at a community-centre event is the single
highest-risk element of this build. Venue Wi-Fi with three hundred attendees on
it is unreliable, and a mute robot is a dead booth. So every utterance walks a
cascade and something always comes out of the speaker:

  Tier 1  pre-generated cache  -- hash-keyed on (voice, model, format, text),
                                  played from disk, zero network. This is the
                                  path that should serve ~100% of lines at the
                                  event. See scripts/pregenerate_voice.py.
  Tier 2  ElevenLabs live      -- model `eleven_flash_v2_5`, streaming, HARD
                                  1200ms wall-clock deadline. On timeout we fall
                                  through and cache NOTHING (a half-downloaded
                                  file in the cache would be a permanent lie).
                                  A success is written into the Tier 1 cache so
                                  it is free and instant next time. Key comes
                                  from $ELEVENLABS_API_KEY and is never logged.
                                  No key -> tier disabled at construction, no
                                  connection ever attempted, startup unaffected.
  Tier 3  offline OS TTS       -- `say` on macOS, PowerShell System.Speech on
                                  Windows. ONE UTTERANCE PER SUBPROCESS.

WHY NOT pyttsx3 (PRD 5.4 forbids it): "run loop already started" on repeated
runAndWait(), NSSpeechDriver attribute crashes on rapid successive macOS calls,
blocking behaviour hostile to an async server, per-thread CoInitialize on
Windows SAPI5, and -- fatally -- no way to interrupt an utterance, which would
silently violate barge-in. A subprocess can be killed; a wedged engine in-process
takes the server down with it.

PLAYBACK SPLIT (deliberate, explained because it looks inconsistent):
  * Tier 1/2 produce an audio FILE, played through `pygame.mixer`, which can
    stop mid-utterance -- barge-in depends on that. Browser <audio> is
    disqualified: Chrome's autoplay policy would silently kill the attract-mode
    barker line, the one utterance whose whole job is to fire at an untouched
    kiosk.
  * Tier 3 has no file: `say` speaks DIRECTLY and we kill the subprocess to
    barge in. Rendering `say` to a temp WAV first and handing it to pygame would
    add a full synthesis round-trip of latency to the tier that is already the
    fallback, and buys nothing -- kill() stops audio just as hard as
    mixer.music.stop().
  Both paths are wrapped by the same interruptible wait, so callers never see
  the difference.

CONCURRENCY: speak() only picks a random template, formats it, and hands a
single PENDING SLOT to a worker thread. It never blocks, never touches the
network, never touches the disk. The FastAPI camera + inference loop must never
stall on audio.

WHY A SINGLE SLOT AND NOT A FIFO: a FIFO plus a 2.5s cooldown means a child
waving an object builds a backlog that drains for a minute after they stop
waving. Instead a new request with priority >= pending REPLACES pending, and a
strictly higher priority also stops the in-flight utterance. That is the PRD's
"a successful fool interrupts and replaces a queued routine guess", literally.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import yaml

log = logging.getLogger(__name__)

# --- States -------------------------------------------------------------- #
# The six phrase groups in config/phrases.yaml.
STATES: tuple[str, ...] = (
    "attract",
    "confident",
    "hedging",
    "confused",
    "fooled",
    "celebration",
)

# Only these may contain `{label}`. See phrases.yaml header for why.
LABEL_STATES: frozenset[str] = frozenset({"confident", "hedging", "fooled"})

# classifier.py emits four bands: confident | hedging | confused | unknown.
# There is deliberately no `unknown` phrase group: in that band the top label is
# below the similarity floor, so there is no label worth speaking and the
# confused lines (which are label-free) are exactly right. Mapped here rather
# than at the call site so the mapping is in one reviewable place.
BAND_TO_STATE: dict[str, str] = {
    "confident": "confident",
    "hedging": "hedging",
    "confused": "confused",
    "unknown": "confused",
}

# --- Priorities ---------------------------------------------------------- #
PRIORITY_ATTRACT = 0   # barker line at an empty booth; anything outranks it
PRIORITY_GUESS = 1     # routine per-object guess
PRIORITY_FOOL = 2      # the payoff moment; interrupts everything

STATE_PRIORITY: dict[str, int] = {
    "attract": PRIORITY_ATTRACT,
    "confident": PRIORITY_GUESS,
    "hedging": PRIORITY_GUESS,
    "confused": PRIORITY_GUESS,
    "fooled": PRIORITY_FOOL,
    "celebration": PRIORITY_FOOL,
}

# --- Tier 2 defaults ----------------------------------------------------- #
ELEVEN_MODEL = "eleven_flash_v2_5"          # ~75ms model latency, real-time
ELEVEN_VOICE = "21m00Tcm4TlvDq8ikWAM"       # placeholder; override in settings
ELEVEN_FORMAT = "mp3_44100_128"             # switch to a WAV/pcm format only if
                                            # decode latency shows on the booth
                                            # laptop (PRD 5.4)
ELEVEN_DEADLINE_S = 1.2                     # HARD. Not negotiable.
ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"

# ElevenLabs has no true WAV container option: `pcm_*` is RAW HEADERLESS PCM,
# which pygame.mixer cannot load. PRD 5.4 explicitly invites switching away from
# MP3 if decode latency shows on the booth laptop, so `pcm_*` is supported here
# by wrapping the stream in a RIFF header before it is cached (see _pcm_to_wav).
# `ulaw_8000` is deliberately unsupported: telephone-quality mono in a gymnasium
# is not a real option, and it would need its own header work.
_FORMAT_EXT = {"mp3": ".mp3", "pcm": ".wav", "wav": ".wav"}

DEFAULT_COOLDOWN_S = 2.5
DEFAULT_MAX_UTTERANCE_S = 15.0   # watchdog: a wedged TTS subprocess gets killed


# ========================================================================== #
# Phrase loading + validation
# ========================================================================== #
def _validate_line(state: str, line: str) -> None:
    """Turn the two hard 'never' rules of PRD 5.4 into load-time failures."""
    if not isinstance(line, str) or not line.strip():
        raise ValueError(f"phrases.yaml [{state}]: empty line")
    n_label = line.count("{label}")
    if n_label > 1:
        raise ValueError(
            f"phrases.yaml [{state}]: {line!r} speaks two labels in one line; "
            "the runner-up belongs on screen, and label x label explodes the cache"
        )
    if state in LABEL_STATES:
        if n_label != 1:
            raise ValueError(
                f"phrases.yaml [{state}]: {line!r} must contain exactly one {{label}}"
            )
    elif n_label:
        raise ValueError(
            f"phrases.yaml [{state}]: {line!r} must be label-free "
            f"(state {state} has no trustworthy label to speak)"
        )
    if "%" in line or any(ch.isdigit() for ch in line):
        raise ValueError(
            f"phrases.yaml [{state}]: {line!r} contains a number or percent sign; "
            "the robot never speaks a raw percentage (PRD 5.4) -- it is on screen"
        )
    # Catch stray braces, e.g. {lable}
    stripped = line.replace("{label}", "")
    if "{" in stripped or "}" in stripped:
        raise ValueError(f"phrases.yaml [{state}]: {line!r} has an unknown placeholder")


def render(template: str, label: str | None = None) -> str:
    """Fill `{label}` and fix the article: "a apple" -> "an apple".

    The templates are written with "a {label}" because the label vocabulary is
    edited independently of the copy (labels.yaml gains vowel-initial entries
    like apple, orange, eraser, umbrella). Deterministic, so the pregeneration
    cache and the runtime line always agree byte for byte.
    """
    text = template.format(label=label or "")
    return _ARTICLE_RE.sub(lambda m: ("An " if m.group(1) == "A" else "an "), text)


_ARTICLE_RE = re.compile(r"\b([Aa]) (?=[aeiouAEIOU])")


def load_phrases(path: str = "config/phrases.yaml") -> dict[str, list[str]]:
    """Load + validate phrase templates. Raises on any copy-rule violation."""
    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}
    phrases: dict[str, list[str]] = {}
    for state in STATES:
        lines = raw.get(state)
        if not lines:
            raise ValueError(f"phrases.yaml: state {state!r} is missing or empty")
        for line in lines:
            _validate_line(state, line)
        phrases[state] = list(lines)
    unknown = set(raw) - set(STATES)
    if unknown:
        # Not fatal, but it would silently never be spoken.
        log.warning("phrases.yaml: ignoring unknown state(s) %s", sorted(unknown))
    return phrases


def load_display_labels(path: str = "config/labels.yaml") -> list[str]:
    """Display labels only. Anchor labels are never spoken (PRD 5.2b)."""
    with open(path, "r") as f:
        cfg = yaml.safe_load(f) or {}
    return [e["label"] for e in cfg.get("display", [])]


def enumerate_utterances(
    phrases: dict[str, list[str]], labels: list[str]
) -> list[tuple[str, str]]:
    """Every line the robot can possibly say, as (state, text).

    This is the whole point of the copy constraints: templates x labels, finite
    and enumerable in advance. Used by scripts/pregenerate_voice.py.
    """
    out: list[tuple[str, str]] = []
    for state in STATES:
        for tmpl in phrases.get(state, []):
            if state in LABEL_STATES:
                out.extend((state, render(tmpl, lab)) for lab in labels)
            else:
                out.append((state, render(tmpl)))
    return out


# ========================================================================== #
# Cache addressing (shared with the pregeneration script)
# ========================================================================== #
def cache_key(voice: str, model: str, fmt: str, text: str) -> str:
    """Hash of (voice, model, format, text).

    Format is in the key on purpose: pregeneration writing WAV and a live Tier 2
    hit writing MP3 would otherwise collide on identical content-different-bytes.
    """
    h = hashlib.sha256()
    h.update("\x1f".join((voice, model, fmt, text)).encode("utf-8"))
    return h.hexdigest()[:20]


def format_ext(fmt: str) -> str:
    family = fmt.split("_", 1)[0]
    if family not in _FORMAT_EXT:
        raise ValueError(
            f"unsupported audio format {fmt!r}; use mp3_* or pcm_* "
            "(pcm is RIFF-wrapped on the way into the cache)"
        )
    return _FORMAT_EXT[family]


def _pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1,
                bits: int = 16) -> bytes:
    """Wrap raw signed-LE PCM in a minimal RIFF header so pygame can load it."""
    import struct

    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits
    ) + b"data" + struct.pack("<I", len(pcm))
    return header + pcm


def cache_path(cache_dir: str, voice: str, model: str, fmt: str, text: str) -> str:
    return os.path.join(
        cache_dir, cache_key(voice, model, fmt, text) + format_ext(fmt)
    )


def write_cache_atomic(path: str, data: bytes) -> None:
    """Temp + os.replace: a killed run must never leave a truncated 'cache hit'."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.part"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ========================================================================== #
# Tier 2 -- ElevenLabs
# ========================================================================== #
def elevenlabs_synthesize(
    text: str,
    *,
    api_key: str,
    voice: str = ELEVEN_VOICE,
    model: str = ELEVEN_MODEL,
    fmt: str = ELEVEN_FORMAT,
    deadline_s: float = ELEVEN_DEADLINE_S,
) -> bytes | None:
    """Stream one utterance. Returns audio bytes, or None on ANY failure.

    urllib's `timeout=` is per socket operation, not total, so the 1200ms budget
    is additionally enforced as a wall-clock deadline while draining the stream:
    a slow-but-alive connection must still fall through to Tier 3. The check
    runs before each read, so the true worst case is one in-flight socket
    timeout beyond the budget (~2x) before we give up -- once, after which the
    booth is on Tier 3 anyway.
    Never raises, never logs the key or the request headers.
    """
    start = time.monotonic()
    url = ELEVEN_URL.format(voice=voice) + f"?output_format={fmt}"
    body = json.dumps({"text": text, "model_id": model}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "*/*",
        },
        method="POST",
    )
    try:
        remaining = deadline_s - (time.monotonic() - start)
        if remaining <= 0:
            return None
        with urllib.request.urlopen(req, timeout=remaining) as resp:
            chunks: list[bytes] = []
            while True:
                if time.monotonic() - start > deadline_s:
                    log.info("Tier 2 exceeded %.0fms deadline; falling through",
                             deadline_s * 1000)
                    return None
                chunk = resp.read(8192)
                if not chunk:
                    break
                chunks.append(chunk)
    except urllib.error.HTTPError as exc:
        # .reason/.code are safe; the key is only ever in the request headers.
        log.warning("Tier 2 HTTP %s; falling through to Tier 3", exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 - a mute booth is the only real bug
        log.warning("Tier 2 failed (%s); falling through to Tier 3",
                    type(exc).__name__)
        return None
    data = b"".join(chunks)
    if not data:
        return None
    if fmt.startswith("pcm"):
        try:
            rate = int(fmt.split("_", 1)[1])
        except (IndexError, ValueError):
            log.error("cannot parse sample rate from format %r", fmt)
            return None
        data = _pcm_to_wav(data, rate)
    return data


# ========================================================================== #
# Engine
# ========================================================================== #
@dataclass
class _Pending:
    text: str
    priority: int
    state: str
    requested_at: float = field(default_factory=time.monotonic)
    # Set when this request barged in on a playing utterance: it must not then
    # be swallowed by the cooldown started by the line it just killed, which
    # would net out as silence.
    cooldown_exempt: bool = False


class VoiceEngine:
    """Non-blocking three-tier speech with barge-in, cooldown and a panic mute.

    Everything public is safe to call from the FastAPI event loop or any thread;
    nothing public performs I/O.
    """

    def __init__(
        self,
        phrases_path: str = "config/phrases.yaml",
        cache_dir: str = "cache/voice",
        *,
        voice: str = ELEVEN_VOICE,
        model: str = ELEVEN_MODEL,
        fmt: str = ELEVEN_FORMAT,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        high_priority_bypasses_cooldown: bool = True,
        max_utterance_s: float = DEFAULT_MAX_UTTERANCE_S,
        cloud_deadline_s: float = ELEVEN_DEADLINE_S,
        os_voice: str | None = None,
        os_rate_wpm: int | None = 180,
        enabled: bool = True,
        muted: bool = False,
    ) -> None:
        self.phrases = load_phrases(phrases_path)
        self.cache_dir = cache_dir
        self.voice = voice
        self.model = model
        self.fmt = fmt
        self.cooldown_s = float(cooldown_s)
        # A routine guess fired 0.4s earlier must not swallow the payoff line,
        # so high priority skips the cooldown by default.
        self.high_priority_bypasses_cooldown = bool(high_priority_bypasses_cooldown)
        self.max_utterance_s = float(max_utterance_s)
        self.cloud_deadline_s = float(cloud_deadline_s)
        self.os_voice = os_voice
        self.os_rate_wpm = os_rate_wpm
        self.enabled = bool(enabled)

        self._api_key = os.environ.get("ELEVENLABS_API_KEY") or None
        if self._api_key:
            log.info("Tier 2 enabled (ElevenLabs %s)", self.model)
        else:
            log.info("Tier 2 disabled: ELEVENLABS_API_KEY not set "
                     "(Tier 1 cache + Tier 3 offline TTS only)")

        os.makedirs(self.cache_dir, exist_ok=True)

        # --- worker state ---
        self._lock = threading.Condition()
        self._pending: _Pending | None = None
        self._playing_priority: int | None = None
        self._interrupt = threading.Event()   # set -> stop current utterance now
        self._shutdown = threading.Event()
        self._muted = bool(muted)
        self._last_end = 0.0
        self._last_index: dict[str, int] = {}   # per-state, avoid immediate repeat
        self._thread: threading.Thread | None = None

        # --- stats for the operator view (PRD 5.7) ---
        self.current_tier: str = "idle"
        self.counts: dict[str, int] = {
            "cache_hit": 0, "cloud": 0, "offline": 0,
            "dropped_cooldown": 0, "replaced": 0, "interrupted": 0,
        }

        # --- pygame, imported lazily so a missing dep degrades, not crashes ---
        self._pygame = None
        self._mixer_state = "unknown"   # unknown | ready | failed

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> "VoiceEngine":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run, name="voice-worker", daemon=True
        )
        self._thread.start()
        return self

    def shutdown(self, timeout: float = 3.0) -> None:
        self._shutdown.set()
        self._interrupt.set()
        with self._lock:
            self._pending = None
            self._lock.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._mixer_state == "ready" and self._pygame is not None:
            try:
                self._pygame.mixer.quit()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    # Public API (non-blocking)
    # ------------------------------------------------------------------ #
    def speak(
        self,
        state: str,
        label: str | None = None,
        priority: int | None = None,
    ) -> str | None:
        """Queue one line for `state` (or a classifier band).

        Returns the text that was ACCEPTED for speaking, or None if it was
        dropped (muted, disabled, in cooldown, or outranked). Use the return
        value for the on-screen caption / log so the screen never claims a line
        the speaker never said.

        NOTE: a dropped line is dropped, NOT deferred. If the caller still wants
        it a moment later, it must ask again.

        Cheap and non-blocking: picks a template, formats it, sets the pending
        slot. Never does network or disk I/O on the caller's thread.
        """
        state = BAND_TO_STATE.get(state, state)
        lines = self.phrases.get(state)
        if not lines:
            log.warning("speak(): unknown state %r", state)
            return None
        if state in LABEL_STATES and not label:
            log.warning("speak(%s): label required, dropping", state)
            return None
        text = render(self._pick(state), label)
        accepted = self.say(
            text,
            priority=priority if priority is not None
            else STATE_PRIORITY.get(state, PRIORITY_GUESS),
            state=state,
        )
        return text if accepted else None

    def say(self, text: str, priority: int = PRIORITY_GUESS,
            state: str = "raw") -> bool:
        """Queue arbitrary text. Prefer speak(); this exists for tests/tools.

        True -> accepted into the pending slot. False -> dropped, not deferred.
        """
        if not self.enabled or self._muted or self._shutdown.is_set():
            return False
        now = time.monotonic()
        with self._lock:
            # An utterance in flight counts as cooldown too: the next allowed
            # slot is at least `cooldown_s` after it ends, so accepting the line
            # here and dropping it at dequeue would make say() return an
            # optimistic True and put a phantom caption on screen.
            in_cooldown = (
                (now - self._last_end) < self.cooldown_s
                or self._playing_priority is not None
            )
            bypass = self._bypasses_cooldown(priority)
            if in_cooldown and not bypass:
                self.counts["dropped_cooldown"] += 1
                log.debug("cooldown: dropped %r (%.2fs since last utterance)",
                          text, now - self._last_end)
                return False
            if self._pending is not None:
                if priority < self._pending.priority:
                    return False               # lower priority never displaces
                self.counts["replaced"] += 1
            self._pending = _Pending(text=text, priority=priority, state=state)
            # Barge-in: strictly higher priority stops what is speaking now.
            if self._playing_priority is not None and priority > self._playing_priority:
                self.counts["interrupted"] += 1
                log.info("barge-in: priority %d interrupts %d",
                         priority, self._playing_priority)
                self._pending.cooldown_exempt = True
                self._interrupt.set()
            self._lock.notify_all()
            return True

    def _bypasses_cooldown(self, priority: int) -> bool:
        return self.high_priority_bypasses_cooldown and priority >= PRIORITY_FOOL

    def set_muted(self, muted: bool) -> None:
        """Panic key (PRD 5.7). Immediate: stops playback and drops pending."""
        with self._lock:
            self._muted = bool(muted)
            if self._muted:
                self._pending = None
                self._interrupt.set()
            self._lock.notify_all()
        log.info("audio %s", "MUTED" if muted else "unmuted")

    @property
    def muted(self) -> bool:
        return self._muted

    def is_speaking(self) -> bool:
        return self._playing_priority is not None

    def status(self) -> dict:
        """Operator-view payload (PRD 5.7)."""
        with self._lock:
            pending = self._pending.text if self._pending else None
        return {
            "enabled": self.enabled,
            "muted": self._muted,
            "tier": self.current_tier,
            "speaking": self.is_speaking(),
            "pending": pending,
            "cloud_available": bool(self._api_key),
            "playback": self._mixer_state,
            "counts": dict(self.counts),
        }

    # ------------------------------------------------------------------ #
    # Worker
    # ------------------------------------------------------------------ #
    def _pick(self, state: str) -> str:
        lines = self.phrases[state]
        if len(lines) == 1:
            return lines[0]
        last = self._last_index.get(state)
        idx = random.randrange(len(lines))
        while idx == last:
            idx = random.randrange(len(lines))
        self._last_index[state] = idx
        return lines[idx]

    def _run(self) -> None:
        # Warm the mixer here rather than in start(): importing pygame and
        # opening the audio device measured ~2.4s on the booth laptop, and that
        # must not land on the first utterance (or on server startup).
        self._ensure_mixer()
        while not self._shutdown.is_set():
            with self._lock:
                while self._pending is None and not self._shutdown.is_set():
                    self._lock.wait(0.25)
                if self._shutdown.is_set():
                    return
                item = self._pending
                self._pending = None
                if item is None or self._muted:
                    continue
                # Re-check the cooldown at dequeue: a line queued DURING the
                # previous utterance would otherwise play back-to-back with it.
                if (time.monotonic() - self._last_end) < self.cooldown_s \
                        and not item.cooldown_exempt \
                        and not self._bypasses_cooldown(item.priority):
                    self.counts["dropped_cooldown"] += 1
                    log.debug("cooldown: dropped %r at dequeue", item.text)
                    continue
                self._playing_priority = item.priority
                self._interrupt.clear()
            try:
                self._utter(item)
            except Exception:  # noqa: BLE001 - the booth must not go mute
                log.exception("voice worker error; continuing")
            finally:
                with self._lock:
                    self._playing_priority = None
                    self._last_end = time.monotonic()
                    self.current_tier = "idle"
                    self._lock.notify_all()

    def _utter(self, item: _Pending) -> None:
        """Tier 1 -> Tier 2 -> Tier 3, on the worker thread only."""
        path = cache_path(self.cache_dir, self.voice, self.model, self.fmt, item.text)
        if os.path.exists(path):
            self.current_tier = "cache"
            self.counts["cache_hit"] += 1
            if self._play_file(path):
                return
            log.warning("cache playback unavailable; falling through to Tier 3")
        elif self._api_key:
            data = elevenlabs_synthesize(
                item.text,
                api_key=self._api_key,
                voice=self.voice,
                model=self.model,
                fmt=self.fmt,
                deadline_s=self.cloud_deadline_s,
            )
            if data:
                try:
                    write_cache_atomic(path, data)
                except OSError as exc:
                    log.warning("could not write voice cache: %s", exc)
                self.current_tier = "cloud"
                self.counts["cloud"] += 1
                if os.path.exists(path) and self._play_file(path):
                    return
        self.current_tier = "offline"
        self.counts["offline"] += 1
        self._speak_offline(item.text)

    # --- playback ------------------------------------------------------ #
    def _ensure_mixer(self) -> bool:
        if self._mixer_state == "ready":
            return True
        if self._mixer_state == "failed":
            return False
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame  # lazy: a missing dep must degrade, not crash startup

            pygame.mixer.init()
            self._pygame = pygame
            self._mixer_state = "ready"
            log.info("pygame.mixer ready")
        except Exception as exc:  # noqa: BLE001
            self._mixer_state = "failed"
            log.warning("pygame.mixer unavailable (%s: %s); Tier 1/2 audio "
                        "disabled, falling back to offline TTS",
                        type(exc).__name__, exc)
        return self._mixer_state == "ready"

    def _play_file(self, path: str | None) -> bool:
        """Play a cached/streamed file. False -> caller should fall through."""
        if path is None:
            return False
        if not self._ensure_mixer():
            return False
        pg = self._pygame
        try:
            pg.mixer.music.load(path)
            pg.mixer.music.play()
        except Exception as exc:  # noqa: BLE001
            log.warning("playback failed for %s (%s)", path, type(exc).__name__)
            return False
        deadline = time.monotonic() + self.max_utterance_s
        while pg.mixer.music.get_busy():
            if self._interrupt.wait(0.02):
                pg.mixer.music.stop()
                log.debug("playback stopped mid-utterance (barge-in/mute)")
                return True
            if time.monotonic() > deadline:
                pg.mixer.music.stop()
                log.error("playback watchdog fired after %.0fs", self.max_utterance_s)
                return True
        return True

    def _offline_cmd(self, text: str) -> tuple[list[str], str | None]:
        """(argv, stdin_text) for one utterance. One subprocess per utterance."""
        if sys.platform == "darwin":
            cmd = ["say"]
            if self.os_voice:
                cmd += ["-v", self.os_voice]
            if self.os_rate_wpm:
                cmd += ["-r", str(int(self.os_rate_wpm))]
            cmd.append(text)
            return cmd, None
        if os.name == "nt":
            # Text over stdin, never interpolated into the command line: no
            # quoting bugs, nothing to escape.
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.Speak([Console]::In.ReadToEnd())"
            )
            return ["powershell", "-NoProfile", "-Command", ps], text
        return ["espeak-ng", text], None      # best-effort on Linux dev boxes

    def _speak_offline(self, text: str) -> None:
        cmd, stdin_text = self._offline_cmd(text)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.error("Tier 3 unavailable: %r not found. Booth is MUTE.", cmd[0])
            return
        if stdin_text and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_text.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass
        deadline = time.monotonic() + self.max_utterance_s
        while proc.poll() is None:
            if self._interrupt.wait(0.02):
                self._kill(proc, "barge-in/mute")
                return
            if time.monotonic() > deadline:
                self._kill(proc, f"watchdog after {self.max_utterance_s:.0f}s")
                return

    @staticmethod
    def _kill(proc: subprocess.Popen, why: str) -> None:
        log.info("killing TTS subprocess (%s)", why)
        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001 - never let a wedged child kill us
            log.warning("TTS subprocess did not die cleanly; abandoning it")


# ========================================================================== #
def from_config(
    settings_path: str = "config/settings.yaml",
    phrases_path: str = "config/phrases.yaml",
    **overrides,
) -> VoiceEngine:
    """Build a VoiceEngine from an optional `voice:` block in settings.yaml.

    Tolerates the block being absent entirely (it is, today) so nothing else has
    to change to get audio working. Recognised keys mirror the constructor:
    cache_dir, voice, model, fmt, cooldown_s, os_voice, os_rate_wpm, enabled,
    muted, max_utterance_s, cloud_deadline_s, high_priority_bypasses_cooldown.
    """
    cfg: dict = {}
    try:
        with open(settings_path, "r") as f:
            cfg = (yaml.safe_load(f) or {}).get("voice") or {}
    except FileNotFoundError:
        log.warning("settings.yaml not found; using voice defaults")
    allowed = {
        "cache_dir", "voice", "model", "fmt", "cooldown_s", "os_voice",
        "os_rate_wpm", "enabled", "muted", "max_utterance_s",
        "cloud_deadline_s", "high_priority_bypasses_cooldown",
    }
    kwargs = {k: v for k, v in cfg.items() if k in allowed}
    ignored = set(cfg) - allowed
    if ignored:
        log.warning("settings.yaml voice: ignoring unknown key(s) %s", sorted(ignored))
    kwargs.update(overrides)
    cache_dir = kwargs.pop("cache_dir", "cache/voice")
    return VoiceEngine(phrases_path=phrases_path, cache_dir=cache_dir, **kwargs)


if __name__ == "__main__":
    # Smoke test: `python -m foolbot.voice` from the repo root.
    logging.basicConfig(level=logging.DEBUG,
                        format="%(relativeCreated)6.0fms %(levelname)s %(message)s")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eng = VoiceEngine(
        phrases_path=os.path.join(root, "config", "phrases.yaml"),
        cache_dir=os.path.join(root, "cache", "voice"),
    ).start()
    print("phrase counts:", {s: len(v) for s, v in eng.phrases.items()})
    print("speaking:", eng.speak("confident", "banana"))
    time.sleep(3.0)
    print("status:", eng.status())
    eng.shutdown()
