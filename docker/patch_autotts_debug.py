"""TEMPORARY instrumentation: log each auto-TTS gate value at runtime."""
import sys
p = "/opt/hermes/gateway/platforms/base.py"
s = open(p).read()
anchor = "                if (self._should_auto_tts_for_chat(event.source.chat_id)\n"
if anchor not in s:
    sys.exit("ANCHOR NOT FOUND")
probe = (
    "                try:\n"
    "                    logger.info(\n"
    "                        '[AUTOTTS-DEBUG] chat=%s should=%s mtype=%s text=%s media=%s stts=%s default=%s enabled=%s disabled=%s',\n"
    "                        event.source.chat_id,\n"
    "                        self._should_auto_tts_for_chat(event.source.chat_id),\n"
    "                        event.message_type,\n"
    "                        bool(text_content), bool(media_files),\n"
    "                        self._streaming_tts_turn_completed(session_key, getattr(interrupt_event, '_hermes_run_generation', None), event=event),\n"
    "                        getattr(self, '_auto_tts_default', 'MISSING'),\n"
    "                        sorted(getattr(self, '_auto_tts_enabled_chats', []) or []),\n"
    "                        sorted(getattr(self, '_auto_tts_disabled_chats', []) or []),\n"
    "                    )\n"
    "                except Exception as _dbg_err:\n"
    "                    logger.info('[AUTOTTS-DEBUG] probe failed: %s', _dbg_err)\n"
)
s = s.replace(anchor, probe + anchor, 1)
open(p, "w").write(s)
import py_compile; py_compile.compile(p, doraise=True)
print("AUTOTTS-DEBUG probe installed")
