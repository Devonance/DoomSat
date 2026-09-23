"""Run a measurement from a commit, not from whatever the working tree happens to be.

Two things went wrong before this existed, and both are invisible in the results:

  - the first jev-versus-code pairing ran its two sides on different commits, because the second run
    started after an edit that the first had not seen. The row looked like a clean paired comparison;
    it was not;
  - the bench starts a fresh payload process per attempt, so a file edited while a run is in flight is
    picked up by the attempts that come later. Half a run on one version of the code, half on another,
    and nothing in the output says so.

So: check out the commit into its own git worktree, refuse to start if the tree is dirty, run there, and
stamp the commit into every attempt. After this, a ledger row can be re-run and it will mean the same
thing. Results still land in the main checkout's `research/out`, because the worktree is scratch.

    python research/runner.py bench --pin HEAD ...          # pins to the current commit
    python research/runner.py bench --pin 5313412 ...       # pins to any commit
    python research/runner.py bench --allow-dirty ...       # scratch run, not for the ledger
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREES = HERE / "worktrees"
# Code that changes what a run does. A change anywhere in here makes the tree dirty for our purposes;
# a note in docs/ or a new file under research/out does not.
CODE_DIRS = ("ground", "payload", "research", "knowledge", "flight", "scripts", "tools")


def git(*args, cwd=None, check=True):
    r = subprocess.run(["git"] + list(args), cwd=str(cwd or HERE.parent), text=True,
                       capture_output=True)
    if check and r.returncode:
        raise SystemExit("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def dirty_paths(root):
    """Tracked modifications and untracked files under the code directories."""
    out = []
    for line in git("status", "--porcelain", cwd=root).splitlines():
        path = line[3:].strip().strip('"')
        # Scratch, both of them: results, and the pinned checkouts this module creates. Without the
        # second, one pinned run leaves the tree permanently "dirty" and every later run refuses.
        if path.startswith("research/out/") or path.startswith("research/worktrees/"):
            continue
        if any(path.startswith(d + "/") for d in CODE_DIRS):
            out.append(line.strip())
    return out


def resolve(ref, root):
    return git("rev-parse", ref, cwd=root)


def worktree_for(commit, root):
    """A detached worktree at `commit`, created once and reused."""
    WORKTREES.mkdir(parents=True, exist_ok=True)
    dest = WORKTREES / commit[:12]
    if dest.is_dir() and (dest / "research" / "runner.py").is_file():
        return dest
    git("worktree", "add", "--detach", "--force", str(dest), commit, cwd=root)
    return dest


def relaunch(commit, argv, root, python=None):
    """Re-run this command inside the worktree for `commit`. Returns its exit code."""
    dest = worktree_for(commit, root)
    args = [a for a in argv if a not in ("--pin",)]
    # drop the --pin value, keep everything else, and tell the child it is already pinned
    out = []
    skip = False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--pin":
            skip = True
            continue
        out.append(a)
    cmd = [python or sys.executable, str(dest / "research" / "runner.py")] + out + ["--pinned-at", commit]
    # The PILOT code is pinned; the RULER is not. Grading, the metric definitions and the grader itself
    # have to be one version across every experiment, or two rows were scored by two different rulers and
    # the ledger is comparing nothing. DOOMSAT_HARNESS points the child back at the main checkout.
    env = dict(os.environ, DOOMSAT_PINNED=commit, DOOMSAT_HARNESS=str(root))
    print("[pinned] %s\n[pinned] worktree %s" % (commit, dest), flush=True)
    return subprocess.call(cmd, cwd=str(dest), env=env)


def prepare(args, argv, root, python=None):
    """Returns an exit code if the run was handed off to a worktree, or None to carry on here.

    `--allow-dirty` is the escape hatch for a smoke test. It is recorded in the attempt so that a row
    built from one is obvious.
    """
    if getattr(args, "pinned_at", None):
        return None                       # we are the child, already inside the worktree
    if not getattr(args, "pin", None):
        if not getattr(args, "allow_dirty", False):
            bad = dirty_paths(root)
            if bad:
                raise SystemExit(
                    "the working tree has uncommitted code:\n  %s\n\n"
                    "A measurement taken from a dirty tree cannot be re-run, and the bench starts a fresh\n"
                    "payload per attempt, so an edit made while it runs lands in the later attempts only.\n"
                    "Commit, or pass --pin <commit>, or --allow-dirty for a scratch run."
                    % "\n  ".join(bad[:12]))
        return None
    bad = dirty_paths(root)
    if bad:
        raise SystemExit("cannot pin with uncommitted code in the tree:\n  %s" % "\n  ".join(bad[:12]))
    return relaunch(resolve(args.pin, root), argv, root, python)


def clean(keep=None):
    """Remove worktrees other than `keep`. Scratch, all of it."""
    if not WORKTREES.is_dir():
        return []
    gone = []
    for d in sorted(WORKTREES.iterdir()):
        if keep and d.name == keep[:12]:
            continue
        git("worktree", "remove", "--force", str(d), check=False)
        gone.append(d.name)
    return gone
