"""Write auto-TTS temp audio inside HERMES_WRITE_SAFE_ROOT.

Upstream's build_auto_tts_output_path() hardcodes tempfile.gettempdir(), but
text_to_speech_tool() validates output_path through agent.file_safety, which
denies anything outside HERMES_WRITE_SAFE_ROOT. This deployment sets that to
/opt/data, so every auto-TTS write is refused:

    output_path targets a protected credential or system path: /tmp/...

The adapter then does `if tts_data.get("success", True):` with no else and no
raise, so _tts_paths stays empty, the playback loop runs zero times, and the
failure is completely silent — no log, no warning. Auto-TTS is dead on every
platform (Discord VC, WhatsApp voice notes) with no diagnostic.

Redirect the base dir to $HERMES_HOME/audio_cache (inside the safe root, and
already used for audio). Files are still unlinked after playback.
"""
import sys

p = "/opt/hermes/gateway/platforms/base.py"
s = open(p).read()

old = """    audio_path = os.path.join(
        tempfile.gettempdir(),
        "hermes_voice",
        f"tts_reply_{uuid.uuid4().hex[:12]}.{ext}",
    )"""
new = """    _safe_root = os.environ.get("HERMES_WRITE_SAFE_ROOT", "").strip()
    if _safe_root:
        _tts_base = os.path.join(
            os.environ.get("HERMES_HOME", _safe_root).strip() or _safe_root,
            "audio_cache",
        )
    else:
        _tts_base = os.path.join(tempfile.gettempdir(), "hermes_voice")
    audio_path = os.path.join(
        _tts_base,
        f"tts_reply_{uuid.uuid4().hex[:12]}.{ext}",
    )"""

if old not in s:
    sys.exit("ANCHOR NOT FOUND — upstream build_auto_tts_output_path changed")

s = s.replace(old, new, 1)
open(p, "w").write(s)

import py_compile
py_compile.compile(p, doraise=True)
print("auto-TTS safe-path patch applied")
