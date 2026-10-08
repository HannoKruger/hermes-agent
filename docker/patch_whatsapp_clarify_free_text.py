"""Let a typed WhatsApp message answer a clarify that was sent as a poll.

The WhatsApp adapter renders a multiple-choice clarify as a native poll. In
v2026.8.13, ``clarify_gateway._coerce_text_response`` rejects typed prose for
a native multiple-choice prompt and lets it "continue as a normal turn". But
the turn it would continue into is the one blocked on the clarify, so the
message queues behind it until ``clarify_timeout`` (3600s) runs out.

A WhatsApp poll has no "Other" button, so typing is the only way to give an
answer that is not one of the options. This marks the clarify as awaiting
text once the poll is sent. Typed numbers and exact option labels still map
to the option, because ``_coerce_text_response`` checks those first.

Upstream solved the prose case differently in 9bff109783 (v2026.8.16): prose
cancels the clarify and runs as a new turn. Delete this patch when the FROM
line moves to v2026.8.16 or later.
"""
import sys

WHATSAPP_ADAPTER = (
    sys.argv[1] if len(sys.argv) > 1 else "/opt/hermes/plugins/platforms/whatsapp/adapter.py"
)

source = open(WHATSAPP_ADAPTER).read()

if "mark_awaiting_text(clarify_id)" in source:
    sys.exit("PATCH ALREADY PRESENT — delete this patch")

OLD = '''                selectable_count=1,
            )
            if result.success:
                return result
            logger.warning(
                "[%s] Native WhatsApp clarify poll failed; falling back to text: %s",'''

NEW = '''                selectable_count=1,
            )
            if result.success:
                from tools.clarify_gateway import mark_awaiting_text

                mark_awaiting_text(clarify_id)
                return result
            logger.warning(
                "[%s] Native WhatsApp clarify poll failed; falling back to text: %s",'''

if source.count(OLD) != 1:
    sys.exit("ANCHOR NOT FOUND — upstream WhatsApp send_clarify changed")

open(WHATSAPP_ADAPTER, "w").write(source.replace(OLD, NEW, 1))

import py_compile

py_compile.compile(WHATSAPP_ADAPTER, doraise=True)
print("whatsapp clarify free text patch applied")
