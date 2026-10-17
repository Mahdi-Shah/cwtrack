"""Point installed Codex skills at this checkout, so there is one source of truth.

The skills in `.agents/skills/` are the project. The copy under the agent's config
directory is what actually gets loaded, and a *copy* of them is a fork waiting to
happen: this one had drifted far enough that the loaded version had no `brief`
command at all, which is the seam between the two skills, so a skill-driven session
could never hand work over. A file link removes the possibility rather than asking
people to remember.

    python tools/link_skills.py            # link, creating the config dir if needed
    python tools/link_skills.py --check    # report drift in installed copies, change nothing

`--check` is what the test suite calls, so a divergent installed copy fails the suite
instead of quietly changing what Codex reads. A skill that has not been installed is
not drift and does not fail the check.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".agents" / "skills"


def config_skills_dir() -> Path:
    """Where Codex looks for skills, per its own config layout."""
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "skills"
    # Keep explicit OpenCode config support for existing users of the old workflow.
    opencode_config = os.environ.get("OPENCODE_CONFIG_DIR")
    if opencode_config:
        return Path(opencode_config) / "skills"
    return Path.home() / ".codex" / "skills"


def is_link(path: Path) -> bool:
    """True when the entry is a symlink or a Windows junction, not a real folder.

    Python 3.12 added Path.is_junction(). Before that a junction shows up only
    through lstat, as an entry with FILE_ATTRIBUTE_REPARSE_POINT. Note that
    Path.is_symlink() is False for a junction, so the obvious check reports "not a
    link" about the one thing that is a link.
    """
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            return bool(is_junction())
        except OSError:
            return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _link(src: Path, dst: Path) -> None:
    if os.name == "nt":
        # A junction needs no elevation, which a symlink does; it is enough for a
        # directory of files.
        os.system('mklink /J "{}" "{}" >NUL 2>&1'.format(dst, src))
        if not dst.exists():
            dst.symlink_to(src, target_is_directory=True)
    else:
        dst.symlink_to(src, target_is_directory=True)


def link_all(check_only: bool = False) -> int:
    config = config_skills_dir()
    if not SKILLS.is_dir():
        print("no skills in {}".format(SKILLS), file=sys.stderr)
        return 2
    if check_only and not config.is_dir():
        return 0

    problems = []
    for name in sorted(p.name for p in SKILLS.iterdir() if p.is_dir()):
        src = SKILLS / name
        dst = config / name

        if dst.exists():
            try:
                same = Path(os.path.realpath(dst)).resolve() == src.resolve()
            except OSError:
                same = False
            if same:
                continue
            if is_link(dst):
                problems.append("{}: links somewhere else ({})".format(name, dst))
            else:
                problems.append("{}: a real directory, not a link - it is a fork".format(name))
            if check_only:
                continue
            print("unlinking {} (it was a separate copy)".format(dst))
            _unlink(dst)

        if check_only:
            continue

        config.mkdir(parents=True, exist_ok=True)
        _link(src, dst)
        print("{} -> {}".format(name, src))

    if problems:
        for p in problems:
            print("  ! " + p, file=sys.stderr)
        if check_only:
            print(
                "\ninstalled skills have drifted from .agents/skills/.\n"
                "fix with: python tools/link_skills.py",
                file=sys.stderr,
            )
            return 1
    return 0


def _unlink(path: Path) -> None:
    """Remove a link without following it into the target."""
    if path.is_symlink() or is_link(path):
        try:
            path.rmdir()
            return
        except OSError:
            pass
    import shutil

    shutil.rmtree(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check", action="store_true",
        help="report drift and exit non-zero; change nothing",
    )
    args = ap.parse_args()
    return link_all(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
