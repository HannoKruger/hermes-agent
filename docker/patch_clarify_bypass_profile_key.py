"""Let a WhatsApp reply answer a pending clarify under multiplex profiles.

Carries upstream commit 525ca9ca1c (issue #82975), which first ships in
v2026.8.16. The pinned v2026.8.13 base image does not have it.

``BasePlatformAdapter.handle_message()`` builds the session key for its
clarify reply bypass without a ``profile=``, so it lands in the legacy
``agent:main`` namespace. The runner registers the pending clarify under the
profile key (``agent:hanno:...``). Once ``gateway.multiplex_profiles`` is on,
the lookup misses and the user's answer is queued as a new turn behind the
blocked one. The turn then waits out ``clarify_timeout`` (3600s) and the
whole chat goes silent for an hour.

Seen in production on 2026-09-10 (21:19 to 22:19 UTC) and on every WhatsApp
clarify since profiles were switched on (2026-08-23): none was ever answered.

Delete this patch when the FROM line moves to v2026.8.16 or later.
"""
import sys

BASE_ADAPTER = sys.argv[1] if len(sys.argv) > 1 else "/opt/hermes/gateway/platforms/base.py"

source = open(BASE_ADAPTER).read()

if "_resolve_profile_for_key(event.source)" in source:
    sys.exit("PATCH ALREADY PRESENT — upstream took this fix, delete this patch")

OLD = '''        session_key = build_session_key(
            event.source,
            group_sessions_per_user=self.config.extra.get("group_sessions_per_user", True),
            thread_sessions_per_user=self.config.extra.get("thread_sessions_per_user", False),
        )
        expected_session_key = str('''

NEW = '''        _sk_store = getattr(self, "_session_store", None)
        session_key = build_session_key(
            event.source,
            group_sessions_per_user=self.config.extra.get("group_sessions_per_user", True),
            thread_sessions_per_user=self.config.extra.get("thread_sessions_per_user", False),
            profile=_sk_store._resolve_profile_for_key(event.source) if _sk_store else None,
        )
        expected_session_key = str('''

if source.count(OLD) != 1:
    sys.exit("ANCHOR NOT FOUND — upstream handle_message changed")

open(BASE_ADAPTER, "w").write(source.replace(OLD, NEW, 1))

import py_compile

py_compile.compile(BASE_ADAPTER, doraise=True)
print("clarify bypass profile key patch applied")
