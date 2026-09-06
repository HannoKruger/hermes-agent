"""Resolve terminal SSH settings from the ACTIVE profile, not the default home.

With ``gateway.multiplex_profiles`` on, every turn runs inside
``_profile_runtime_scope``, which redirects ``get_hermes_home()`` to that
person's profile home via a contextvar. Config, skills and memory follow it.
The terminal tool does not.

``gateway/run.py`` bridges ``terminal.*`` from the DEFAULT home's config.yaml
into process-global ``TERMINAL_*`` environment variables, once, at module
import. ``tools/terminal_tool.py:_get_env_config()`` then reads only
``os.getenv("TERMINAL_SSH_USER")`` / ``TERMINAL_SSH_KEY`` / ``TERMINAL_CWD``.
So ``profiles/<name>/config.yaml`` is loaded for everything except the one
setting that decides which account a command runs as.

On this deployment the default home carries a deliberate sentinel
(``ssh_user: DISABLED-no-default-profile``, ``ssh_key: /dev/null``) so an
unrouted sender can never reach hulk. Because the bridge is global, both
routed profiles inherited that sentinel too and every terminal call failed:

    SSH connection failed: Load key "/dev/null": error in libcrypto
    DISABLED-no-default-profile@192.168.0.189: Permission denied (publickey).

hulk's sshd logged the other side as ``Invalid user
DISABLED-no-default-profile from 192.168.0.188``. The agent read that as a
dropped connection and told Hanno its SSH link to hulk was down.

Raising the sentinel to a real user in the default config is NOT a fix: the
env var is process-global, so it would hand every unrouted sender, and Hakru,
Hanno's root-capable account on hulk.

This overlays the active profile's ``terminal`` section onto the resolved
config on each call. ``get_hermes_home()`` is contextvar-backed, so two
concurrent turns read their own profile with no shared mutable state. Nothing
is written back to ``os.environ``.

Only identity keys are overridden. ``backend`` is deliberately left alone
because it steers control flow earlier in ``_get_env_config`` (container
resource parsing, cwd sanity checks); a profile that disagrees with the
process backend gets a loud warning instead of a half-applied config.

When no profile scope is active, ``get_hermes_home()`` returns the default
home, so the sentinel still applies and unrouted senders are still refused.
"""
import sys

TERMINAL_TOOL = sys.argv[1] if len(sys.argv) > 1 else "/opt/hermes/tools/terminal_tool.py"

source = open(TERMINAL_TOOL).read()

if "_apply_profile_terminal_overrides" in source:
    sys.exit("PATCH ALREADY PRESENT — upstream may have taken this fix")

for anchor in (
    "def _get_env_config() -> Dict[str, Any]:",
    '"ssh_user": os.getenv("TERMINAL_SSH_USER", ""),',
    '"ssh_key": os.getenv("TERMINAL_SSH_KEY", ""),',
    "import threading",
):
    if anchor not in source:
        sys.exit(f"ANCHOR NOT FOUND — upstream terminal_tool changed: {anchor!r}")

overlay = '''

# ─────────────────────────────────────────────────────────────────────────────
# Per-profile terminal identity (homelab overlay — see
# docker/patch_profile_terminal_config.py for why).
#
# _get_env_config() reads process-global TERMINAL_* env vars that the gateway
# bridges once, at import, from the DEFAULT home's config.yaml. Under
# gateway.multiplex_profiles every turn runs inside a contextvar scope that
# points get_hermes_home() at the sender's profile home, so those env vars are
# the wrong person's. Overlay the active profile's terminal section instead.
# ─────────────────────────────────────────────────────────────────────────────

_PROFILE_TERMINAL_SECTION_CACHE: Dict[str, Any] = {}
_PROFILE_TERMINAL_SECTION_LOCK = threading.Lock()

_PROFILE_TERMINAL_INT_KEYS = {
    "ssh_port": "ssh_port",
    "timeout": "timeout",
    "lifetime_seconds": "lifetime_seconds",
}
_PROFILE_TERMINAL_STR_KEYS = {
    "ssh_host": "ssh_host",
    "ssh_user": "ssh_user",
    "ssh_key": "ssh_key",
}
_PROFILE_TERMINAL_CWD_PLACEHOLDERS = {".", "auto", "cwd"}


def _active_profile_terminal_section() -> Dict[str, Any]:
    """Return the ``terminal`` section of the ACTIVE profile's config.yaml.

    Cached per file on (mtime, size) so a terminal call does not re-parse YAML,
    and an edited profile config still takes effect without a restart.
    """
    from pathlib import Path as _Path

    from hermes_constants import get_hermes_home

    config_path = _Path(get_hermes_home()) / "config.yaml"
    key = str(config_path)
    stamp = config_path.stat()
    stamp = (stamp.st_mtime_ns, stamp.st_size)

    with _PROFILE_TERMINAL_SECTION_LOCK:
        cached = _PROFILE_TERMINAL_SECTION_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]

    from hermes_cli.config import _expand_env_vars, read_user_config_raw

    raw = read_user_config_raw(config_path)
    raw = _expand_env_vars(raw) if isinstance(raw, dict) else {}
    section = raw.get("terminal") if isinstance(raw, dict) else None
    section = dict(section) if isinstance(section, dict) else {}

    with _PROFILE_TERMINAL_SECTION_LOCK:
        _PROFILE_TERMINAL_SECTION_CACHE[key] = (stamp, section)
    return section


def _apply_profile_terminal_overrides(config: Dict[str, Any]) -> None:
    """Overlay the active profile's terminal identity onto ``config``."""
    try:
        section = _active_profile_terminal_section()
    except Exception:
        logger.debug("profile terminal overlay skipped", exc_info=True)
        return
    if not section:
        return

    env_type = config.get("env_type")

    backend = str(section.get("backend") or "").strip().lower()
    if backend and backend != env_type:
        logger.warning(
            "profile config.yaml sets terminal.backend=%r but this process runs "
            "the %r backend. Only SSH identity and cwd are applied per profile; "
            "the backend comes from the default home's config.yaml.",
            backend, env_type,
        )

    for config_key, target in _PROFILE_TERMINAL_STR_KEYS.items():
        value = section.get(config_key)
        if isinstance(value, str) and value.strip():
            config[target] = value.strip()

    for config_key, target in _PROFILE_TERMINAL_INT_KEYS.items():
        if config_key not in section or section[config_key] is None:
            continue
        try:
            config[target] = int(section[config_key])
        except (TypeError, ValueError):
            logger.warning(
                "profile config.yaml has non-integer terminal.%s=%r; keeping %r",
                config_key, section[config_key], config.get(target),
            )

    if "persistent_shell" in section:
        config["ssh_persistent"] = str(
            section["persistent_shell"]
        ).strip().lower() in {"true", "1", "yes"}

    cwd = section.get("cwd")
    if isinstance(cwd, str) and cwd.strip() and cwd.strip() not in _PROFILE_TERMINAL_CWD_PLACEHOLDERS:
        if env_type == "ssh":
            cwd = cwd.strip()
            from hermes_cli.config import _is_ssh_remote_tilde_cwd
            if not _is_ssh_remote_tilde_cwd(env_type, cwd):
                cwd = os.path.expanduser(cwd)
            config["cwd"] = cwd
        else:
            # Container backends remap and sanity-check cwd inside
            # _get_env_config (host_cwd/workspace, _is_unusable_container_cwd).
            # Overwriting it here would bypass both.
            logger.debug(
                "profile terminal.cwd=%r not applied for %r backend", cwd, env_type,
            )


_get_env_config_process_scoped = _get_env_config


def _get_env_config() -> Dict[str, Any]:
    """Process-scoped terminal config, overlaid with the active profile's."""
    config = _get_env_config_process_scoped()
    _apply_profile_terminal_overrides(config)
    return config
'''

# Appended at end of module: no call site resolves _get_env_config before
# import completes (verified — every reference is inside a function body), and
# Python looks module globals up at call time, so the rebind reaches all of
# them. Appending also means no fragile mid-file anchor to drift against.
source = source + overlay
open(TERMINAL_TOOL, "w").write(source)

import py_compile

py_compile.compile(TERMINAL_TOOL, doraise=True)
print("per-profile terminal config patch applied")
