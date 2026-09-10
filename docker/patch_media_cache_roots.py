"""Let vision read inbound media that ingest cached under the DEFAULT home.

``tools/image_source.py:_media_cache_roots()`` builds the allowlist of host
paths vision may read under a non-local terminal backend. It derives them from
``get_hermes_home()``, which inside a turn is the routed profile's home.

Inbound media does not land there. The gateway downloads and caches a photo
during message ingest, BEFORE ``_profile_runtime_scope`` is installed, so
``get_image_cache_dir()`` resolves to the DEFAULT home. The writer and the
allowlist therefore never agree once ``gateway.multiplex_profiles`` is on:

    written to : /opt/data/cache/images/img_<hex>.jpg
    allowed    : /opt/data/profiles/<name>/cache/...

With no match, ``_permitted_host_read_target()`` returns None and the caller
falls through to ``_resolve_container_fallback()``, which reads the file
*inside the sandbox*. On this deployment the sandbox is hulk over SSH, and
hulk has no ``/opt/data`` at all, so every photo died with:

    '<path>' is not reachable inside the sandbox
    sandbox returned non-image data: Only base64 data is allowed

Upstream's own docstring says the permitted set is "gateway-downloaded inbound
media and the tools' own URL-download temp dirs". The default home's cache IS
gateway-downloaded inbound media — the list is simply incomplete for multiplex
deployments, which upstream did not anticipate. This adds those roots.

SCOPE OF THE WIDENING, stated plainly: ingest is unscoped, so BOTH profiles'
inbound media already share ``<default home>/cache`` on disk today. This does
not create that commingling, it only lets vision read it. A turn running as one
profile can therefore read another profile's cached inbound media if it knows
the random filename. The proper fix is to scope ingest so media lands in the
routed profile's cache; until upstream does that, this is the honest trade and
it is logged every time it happens rather than being silent.

Every fallback match logs a WARNING naming both paths, so the scope mismatch
stays visible in errors.log instead of being papered over.
"""
import sys

IMAGE_SOURCE = sys.argv[1] if len(sys.argv) > 1 else "/opt/hermes/tools/image_source.py"

source = open(IMAGE_SOURCE).read()

if "_default_home_media_roots" in source:
    sys.exit("PATCH ALREADY PRESENT — upstream may have taken this fix")

OLD = '''    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    return [
        home / "cache",  # cache/images, cache/vision, cache/video(s), cache/audio
        home / "images",  # desktop/clipboard/PDF uploads (tui_gateway) — #69575
        home / "image_cache",
        home / "audio_cache",
        home / "video_cache",
        home / "temp_vision_images",
        home / "temp_video_files",
    ]'''

NEW = '''    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    roots = _media_roots_for_home(home)

    # Multiplex deployments: the gateway caches inbound media during message
    # ingest, before _profile_runtime_scope is installed, so the file lands
    # under the DEFAULT home while this call resolves the PROFILE home. Without
    # these the read is refused and the caller falls through to an in-sandbox
    # read of a path the sandbox has never heard of. See
    # docker/patch_media_cache_roots.py.
    for extra in _default_home_media_roots():
        if extra not in roots:
            roots.append(extra)
    return roots


def _media_roots_for_home(home) -> list:
    """Media cache directories under one Hermes home."""
    return [
        home / "cache",  # cache/images, cache/vision, cache/video(s), cache/audio
        home / "images",  # desktop/clipboard/PDF uploads (tui_gateway) — #69575
        home / "image_cache",
        home / "audio_cache",
        home / "video_cache",
        home / "temp_vision_images",
        home / "temp_video_files",
    ]


def _default_home_media_roots() -> list:
    """Media cache directories under the PROCESS default home, if it differs.

    Returns [] when no profile override is active, so single-profile installs
    get byte-identical behaviour to upstream.
    """
    import os as _os
    from pathlib import Path as _Path

    from hermes_constants import get_hermes_home, get_hermes_home_override

    if get_hermes_home_override() is None:
        return []
    default_home = (_os.environ.get("HERMES_HOME") or "").strip()
    if not default_home:
        return []
    try:
        default_home = _Path(default_home).resolve()
        if default_home == _Path(get_hermes_home()).resolve():
            return []
    except Exception:  # noqa: BLE001 — unresolvable default home: skip the widening
        return []
    return _media_roots_for_home(default_home)'''

if OLD not in source:
    sys.exit("ANCHOR NOT FOUND — upstream _media_cache_roots changed")

source = source.replace(OLD, NEW, 1)

source += '''

import logging as _logging

logger = _logging.getLogger("tools.image_source")

# ─────────────────────────────────────────────────────────────────────────────
# Homelab overlay: warn when a media read is only permitted because of the
# default-home widening above, so the ingest/turn scope mismatch is visible in
# errors.log rather than silently working. See
# docker/patch_media_cache_roots.py.
# ─────────────────────────────────────────────────────────────────────────────

_permitted_host_read_target_strict = _permitted_host_read_target


def _permitted_host_read_target(p, ctx):  # noqa: F811 — deliberate override
    result = _permitted_host_read_target_strict(p, ctx)
    if result is None:
        return None
    try:
        extra = _default_home_media_roots()
        if not extra:
            return result
        resolved = result.resolve()
        in_default = any(_is_within(resolved, r) for r in extra)
        if in_default:
            from hermes_constants import get_hermes_home

            logger.warning(
                "vision read %s served from the DEFAULT Hermes home, not the "
                "active profile home %s. Inbound media is cached during "
                "message ingest, before the profile scope exists, so writer "
                "and reader disagree. The read is permitted (both are "
                "Hermes-owned media caches) but this is a real scope bug: "
                "media from every profile shares that directory.",
                resolved, get_hermes_home(),
            )
    except Exception:  # noqa: BLE001 — diagnostics must never break a read
        logger.debug("default-home media read diagnostic failed", exc_info=True)
    return result


def _is_within(child, parent) -> bool:
    """True when *child* is *parent* or sits underneath it."""
    try:
        child.relative_to(parent)
        return True
    except Exception:  # noqa: BLE001 — different roots
        return False
'''

open(IMAGE_SOURCE, "w").write(source)

import py_compile

py_compile.compile(IMAGE_SOURCE, doraise=True)
print("media cache roots patch applied")
