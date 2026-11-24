#!/usr/bin/env python3
"""claude-backup: back up / restore all local Claude data to a private GitHub repo.

Stdlib only, Python 3.8+. Subcommands: init, backup, restore, schedule, unschedule, status.
Design notes live in ../references/design.md.
"""
import argparse
import glob
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
_CFG = os.environ.get("CLAUDE_CONFIG_DIR")
CLAUDE_DIR = _CFG or os.path.join(HOME, ".claude")
CLAUDE_JSON = os.path.join(_CFG, ".claude.json") if _CFG else os.path.join(HOME, ".claude.json")
STATE_DIR = os.environ.get("CLAUDE_BACKUP_HOME") or os.path.join(HOME, ".claude-backup")
REPO_DIR = os.path.join(STATE_DIR, "repo")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "backup.log")
if sys.platform == "darwin":
    DESKTOP_DIR = os.path.join(HOME, "Library", "Application Support", "Claude")
else:
    DESKTOP_DIR = os.path.join(HOME, ".config", "Claude")
LABEL = "com.claude-backup.daily"
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LABEL + ".plist")

MAX_FILE = 95 * 1024 * 1024  # GitHub rejects files over 100 MB
KEEP_DAYS = 36500            # cleanupPeriodDays: stop Claude Code deleting old conversations
PLACEHOLDER = "<REDACTED-REFILL-ME>"

# Top-level names in ~/.claude that are login credentials, caches or per-machine runtime state.
CLAUDE_EXCLUDE = {
    ".credentials.json", "cache", "debug", "shell-snapshots", "session-env", "statsig",
    "telemetry", "ide", "daemon", "sessions", "backups", "remote-settings.json",
    "policy-limits.json", "seed-admin", "environment-manager", "launcher-settings.json",
    ".last-cleanup", "remote", "downloads", "local",
}
CLAUDE_EXCLUDE_REL = {"skills/synced"}  # managed by Claude, re-synced from the account
# Desktop app (Electron) dir: browser caches, login cookies, VM images, binaries.
DESKTOP_EXCLUDE = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "blob_storage", "Crashpad", "logs", "sentry", "Session Storage", "Local Storage",
    "IndexedDB", "Cookies", "Cookies-journal", "Network", "Shared Dictionary", "SharedStorage",
    "Service Worker", "WebStorage", "vm_bundles", "claude-code", "claude-code-vm", "Partitions",
    "Trust Tokens", "Trust Tokens-journal", "TransportSecurity", "Network Persistent State",
    "DIPS", "DIPS-wal", "DIPS-shm", "SingletonLock", "SingletonCookie", "SingletonSocket",
    "lockfile", "Dictionaries", "GrShaderCache", "ShaderCache", "VideoDecodeStats", "databases",
    "Local State", "fcache", "ant-did", "git-worktrees", "window-state.json",
    "buddy-tokens.json", "ant-device-registry.json", "GPUPersistentCache", "GraphiteDawnCache",
    "shared_proto_db", "declarative_performance_observer.db", "declarative_performance_observer.db-journal",
    "Extension State", "File System", "ext-icon-probe", "preview-last-frames", "claude-code-spare",
}
# Desktop folders laid out as <name>/<accountUuid>/<orgUuid>/... . The Code tab sidebar only
# reads the folder of the account that is signed in, so on restore into another account these
# are moved to the new account's ids.
ACCOUNT_SCOPED = ("claude-code-sessions",)
SKIP_DIRS = {".git", "__pycache__", ".DS_Store", ".in_use"}  # .in_use: per-process plugin locks
ACCOUNT_KEYS = {"oauthAccount", "userID", "primaryApiKey", "customApiKeyResponses",
                "anonymousId", "s1mAccessCache", "passesEligibilityCache"}

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai", re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}")),
    ("github", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("gitlab", re.compile(r"glpat-[A-Za-z0-9_\-]{20,}")),
    ("slack", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("huggingface", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("npm", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("stripe", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}")),
    ("sendgrid", re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]
BEARER = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-+/=]{25,})")
ASSIGN = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|passwd|access[_-]?key)[A-Za-z_]*"
    r"\\?[\"']?\s*[:=]\s*\\?[\"']?)([A-Za-z0-9_\-+/=.]{24,})")
SENSITIVE_KEY = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|credential|access[_-]?key)")
NOT_SECRET_KEYS = {"apiKeyHelper", "awsCredentialExport", "awsAuthRefresh"}
JSON_CONFIGS = {"settings.json", "settings.local.json", ".mcp.json", "claude_desktop_config.json",
                "config.json", "mcp.json"}


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd=None, check=True, capture=True):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, universal_newlines=True)
    if check and p.returncode != 0:
        raise SystemExit("command failed: %s\n%s" % (" ".join(cmd), (p.stdout or "").strip()))
    return p


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data, indent=2):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, sort_keys=indent is None)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- redaction

def _mixed(s):
    return bool(re.search(r"[0-9]", s)) and bool(re.search(r"[A-Za-z]", s))


def redact_text(text, counts):
    for name, pat in SECRET_PATTERNS:
        text, n = pat.subn("[REDACTED:%s]" % name, text)
        if n:
            counts[name] = counts.get(name, 0) + n

    def bearer(m):
        if not _mixed(m.group(2)):
            return m.group(0)
        counts["bearer"] = counts.get("bearer", 0) + 1
        return m.group(1) + "[REDACTED:bearer]"

    def assign(m):
        if not _mixed(m.group(2)) or "REDACTED" in m.group(2):
            return m.group(0)
        counts["assigned-secret"] = counts.get("assigned-secret", 0) + 1
        return m.group(1) + "[REDACTED:secret]"

    text = BEARER.sub(bearer, text)
    return ASSIGN.sub(assign, text)


def scrub_config(obj, path, found):
    """Blank string values under secret-looking keys in a config JSON; record where."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            p = path + [str(k)]
            if isinstance(v, str) and v and k not in NOT_SECRET_KEYS and SENSITIVE_KEY.search(str(k)):
                obj[k] = PLACEHOLDER
                found.append(".".join(p))
            else:
                scrub_config(v, p, found)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scrub_config(v, path + [str(i)], found)


def refill(obj, cur):
    """On restore: where the backup has a placeholder and this machine has a real value, keep it."""
    left = []
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            c = cur.get(k) if isinstance(cur, dict) else None
            if v == PLACEHOLDER:
                if isinstance(c, str) and c and c != PLACEHOLDER:
                    obj[k] = c
                else:
                    left.append(str(k))
            else:
                left += ["%s.%s" % (k, x) for x in refill(v, c)]
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            c = cur[i] if isinstance(cur, list) and i < len(cur) else None
            left += ["%d.%s" % (i, x) for x in refill(v, c)]
    return left


# ---------------------------------------------------------------- backup

def walk(root, exclude_top=(), exclude_rel=()):
    """Yield (abs, rel) for files under root. Follows symlinked dirs (skills are often links)."""
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        keep = []
        for d in dirnames:
            rel = (rel_dir + "/" + d) if rel_dir else d
            if d in SKIP_DIRS or (not rel_dir and d in exclude_top) or rel in exclude_rel:
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            if fn in SKIP_DIRS or (not rel_dir and fn in exclude_top):
                continue
            if fn.endswith((".lock", ".tmp", ".sock")):
                continue
            full = os.path.join(dirpath, fn)
            if os.path.isfile(full):
                yield full, (rel_dir + "/" + fn) if rel_dir else fn


class Backup:
    def __init__(self, full=False):
        self.state = {} if full else (load_json(STATE_FILE, {}) or {})
        old = load_json(os.path.join(REPO_DIR, "backup-manifest.json"), {}) or {}
        self.mtimes = old.get("mtimes", {})
        self.counts, self.config_secrets, self.skipped = {}, [], []
        self.copied = 0

    def put(self, src, dest_rel, config=False):
        try:
            st = os.stat(src)
        except OSError:
            return
        dest = os.path.join(REPO_DIR, dest_rel)
        sig = [st.st_mtime_ns, st.st_size]
        self.mtimes[dest_rel] = int(st.st_mtime)
        if self.state.get(dest_rel) == sig and os.path.exists(dest):
            return
        if st.st_size > MAX_FILE:
            self.skipped.append("%s (%d MB, over GitHub's 100 MB limit)" % (dest_rel, st.st_size >> 20))
            return
        try:
            with open(src, "rb") as f:
                raw = f.read()
        except OSError as e:
            self.skipped.append("%s (unreadable: %s)" % (dest_rel, e))
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None:
            if config:
                data = None
                try:
                    data = json.loads(text)
                except ValueError:
                    pass
                if isinstance(data, dict):
                    if dest_rel == "claude.json":
                        for k in list(data):
                            if k in ACCOUNT_KEYS or k.startswith("cached"):
                                del data[k]
                    found = []
                    scrub_config(data, [], found)
                    self.config_secrets += ["%s → %s" % (dest_rel, x) for x in found]
                    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            text = redact_text(text, self.counts)
            raw = text.encode("utf-8")
        os.makedirs(os.path.dirname(dest) or REPO_DIR, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw)
        self.state[dest_rel] = sig
        self.copied += 1

    def collect(self):
        if os.path.isdir(CLAUDE_DIR):
            for full, rel in walk(CLAUDE_DIR, CLAUDE_EXCLUDE, CLAUDE_EXCLUDE_REL):
                self.put(full, "claude-home/" + rel, config=os.path.basename(rel) in JSON_CONFIGS)
        if os.path.isfile(CLAUDE_JSON):
            self.put(CLAUDE_JSON, "claude.json", config=True)
        if os.path.isdir(DESKTOP_DIR):
            for name in DESKTOP_EXCLUDE:  # drop anything an older version backed up by mistake
                old = os.path.join(REPO_DIR, "desktop-app", name)
                if os.path.isdir(old):
                    shutil.rmtree(old)
                elif os.path.exists(old):
                    os.remove(old)
            for full, rel in walk(DESKTOP_DIR, DESKTOP_EXCLUDE):
                self.put(full, "desktop-app/" + rel, config=os.path.basename(rel) in JSON_CONFIGS)
        # Personal, git-ignored per-project files that live outside ~/.claude
        cj = load_json(CLAUDE_JSON, {}) or {}
        index = {}
        for proj in sorted((cj.get("projects") or {}).keys()):
            if not os.path.isdir(proj):
                continue
            enc = re.sub(r"[^A-Za-z0-9]", "-", proj)
            for rel in ("CLAUDE.local.md", ".claude/settings.local.json", ".mcp.json"):
                src = os.path.join(proj, rel)
                if os.path.isfile(src):
                    index[enc] = proj
                    self.put(src, "project-local/%s/%s" % (enc, rel), config=rel.endswith(".json"))
        if index:
            save_json(os.path.join(REPO_DIR, "project-local", "index.json"), index)

    def finish(self):
        ver = ""
        if shutil.which("claude"):
            ver = (run(["claude", "--version"], check=False).stdout or "").strip()
        manifest = {
            "format": 1, "last_backup": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "home": HOME, "user": os.path.basename(HOME), "host": socket.gethostname(),
            "platform": platform.platform(), "claude_version": ver,
            "claude_dir": CLAUDE_DIR, "desktop_dir": DESKTOP_DIR, "mtimes": self.mtimes,
            "desktop_accounts": desktop_accounts(DESKTOP_DIR),
        }
        save_json(os.path.join(REPO_DIR, "backup-manifest.json"), manifest, indent=None)
        lines = ["# Secrets to refill after restore", "",
                 "These config values were blanked before upload (the values themselves were never",
                 "uploaded). After restoring, put the real values back in the matching file.", ""]
        lines += ["- `%s`" % s for s in sorted(set(self.config_secrets))] or ["(none found)"]
        prev = os.path.join(REPO_DIR, "SECRETS-TO-REFILL.md")
        if self.config_secrets or not os.path.exists(prev):
            with open(prev, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        save_json(STATE_FILE, self.state, indent=None)


def desktop_accounts(base):
    """[accountUuid, orgUuid] pairs that have a Code tab session folder."""
    out = []
    root = os.path.join(base, "claude-code-sessions")
    if os.path.isdir(root):
        for a in sorted(os.listdir(root)):
            if os.path.isdir(os.path.join(root, a)):
                out += [[a, o] for o in sorted(os.listdir(os.path.join(root, a)))
                        if os.path.isdir(os.path.join(root, a, o))]
    return out


def current_desktop_account(override=None):
    """The account the desktop app is signed in to now, as [accountUuid, orgUuid] or None."""
    if override:
        parts = override.strip("/").split("/")
        if len(parts) == 2:
            return parts
        raise SystemExit("--desktop-account must look like <accountUuid>/<orgUuid>")
    acct = (load_json(os.path.join(DESKTOP_DIR, "config.json"), {}) or {}).get("lastKnownAccountUuid")
    oa = (load_json(CLAUDE_JSON, {}) or {}).get("oauthAccount") or {}
    if acct and oa.get("accountUuid") == acct and oa.get("organizationUuid"):
        return [acct, oa["organizationUuid"]]
    # fall back: a session folder that exists for that account
    for a, o in desktop_accounts(DESKTOP_DIR):
        if a == acct:
            return [a, o]
    return None


def count_sessions(base):
    n = 0
    proj = os.path.join(base, "projects")
    if os.path.isdir(proj):
        for _, dirs, files in os.walk(proj):
            n += sum(1 for f in files if f.endswith(".jsonl"))
    return n


def is_private(remote):
    """True/False if GitHub says so, None if it can't be checked."""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", remote or "")
    if not m or not shutil.which("gh"):
        return None
    p = run(["gh", "repo", "view", m.group(1), "--json", "isPrivate", "-q", ".isPrivate"], check=False)
    out = (p.stdout or "").strip()
    return {"true": True, "false": False}.get(out)


def need_repo():
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        raise SystemExit("Not set up yet. Run: claude_backup.py init --repo <name>")


def git(*a, **kw):
    return run(["git"] + list(a), cwd=REPO_DIR, **kw)


def remote_url():
    return (git("remote", "get-url", "origin", check=False).stdout or "").strip()


def ensure_identity():
    if not (git("config", "user.email", check=False).stdout or "").strip():
        git("config", "user.email", "claude-backup@localhost")
        git("config", "user.name", "claude-backup")


def repoint_repo(man, old_home):
    """After restoring under a different home folder, rename the folders inside the backup
    too, so later backups from this machine update the same conversations (no duplicates)."""
    eo, en = enc_path(old_home), enc_path(HOME)
    mt = man.get("mtimes", {})
    for top in ("claude-home/projects", "project-local"):
        base = os.path.join(REPO_DIR, top)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not (name == eo or name.startswith(eo + "-")):
                continue
            new = en + name[len(eo):]
            src, dst = os.path.join(base, name), os.path.join(base, new)
            if not os.path.isdir(src):
                continue
            if os.path.exists(dst):
                shutil.copytree(src, dst, dirs_exist_ok=True)
                shutil.rmtree(src)
            else:
                os.rename(src, dst)
            for k in [k for k in mt if k.startswith("%s/%s/" % (top, name))]:
                mt["%s/%s/%s" % (top, new, k[len(top) + len(name) + 2:])] = mt.pop(k)
    ipath = os.path.join(REPO_DIR, "project-local", "index.json")
    idx = load_json(ipath, None)
    if isinstance(idx, dict):
        save_json(ipath, {(en + k[len(eo):]) if (k == eo or k.startswith(eo + "-")) else k:
                          (HOME + v[len(old_home):]) if (v == old_home or v.startswith(old_home + "/")) else v
                          for k, v in idx.items()})
    man["home"], man["user"] = HOME, os.path.basename(HOME)
    save_json(os.path.join(REPO_DIR, "backup-manifest.json"), man, indent=None)
    ensure_identity()
    git("add", "-A")
    git("commit", "-q", "-m", "re-point backup to new home folder %s" % HOME, check=False)
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def protect_history():
    """Deliberately does nothing: the user wants Claude's own 30-day cleanup rule kept."""
    return
    path = os.path.join(CLAUDE_DIR, "settings.json")
    s = load_json(path, None)
    if s is None:
        if os.path.exists(path):
            log("! could not parse %s; set \"cleanupPeriodDays\": %d there by hand" % (path, KEEP_DAYS))
            return
        s = {}
    if not isinstance(s.get("cleanupPeriodDays"), int) or s["cleanupPeriodDays"] < KEEP_DAYS:
        s["cleanupPeriodDays"] = KEEP_DAYS
        save_json(path, s)
        log("· set cleanupPeriodDays=%d in %s (keeps old conversations on disk)" % (KEEP_DAYS, path))


def cmd_init(a):
    os.makedirs(STATE_DIR, exist_ok=True)
    if not shutil.which("git"):
        raise SystemExit("git not found. On macOS run: xcode-select --install")
    remote = a.remote
    if not remote:
        if not a.repo:
            raise SystemExit("give --repo <name or owner/name> (GitHub, needs gh) or --remote <git url>")
        if not shutil.which("gh"):
            raise SystemExit("GitHub CLI not found. Install: brew install gh && gh auth login")
        if run(["gh", "auth", "status"], check=False).returncode != 0:
            raise SystemExit("GitHub CLI is not logged in. Run: gh auth login")
        if run(["gh", "repo", "view", a.repo], check=False).returncode != 0:
            run(["gh", "repo", "create", a.repo, "--private",
                 "--description", "Private backup of my Claude data"])
            log("· created private repo %s" % a.repo)
        remote = (run(["gh", "repo", "view", a.repo, "--json", "url", "-q", ".url"]).stdout or "").strip() + ".git"
        run(["gh", "auth", "setup-git"], check=False)
    if is_private(remote) is False:
        raise SystemExit("REFUSING: %s is a PUBLIC repo. Make it private first." % remote)
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        if run(["git", "clone", remote, REPO_DIR], check=False).returncode != 0:
            os.makedirs(REPO_DIR, exist_ok=True)
            run(["git", "init", "-b", "main"], cwd=REPO_DIR)
            git("remote", "add", "origin", remote)
    else:
        git("remote", "set-url", "origin", remote)
    ensure_identity()
    with open(os.path.join(REPO_DIR, ".gitattributes"), "w") as f:
        f.write("* -text\n")
    save_json(CONFIG_FILE, {"remote": remote})
    protect_history()
    log("✓ ready. repo: %s\n  local copy: %s" % (remote, REPO_DIR))


def cmd_backup(a):
    need_repo()
    remote = remote_url()
    if is_private(remote) is False:
        raise SystemExit("REFUSING to push: %s is PUBLIC. Make it private first." % remote)
    ensure_identity()
    git("pull", "--rebase", "--autostash", "-q", check=False)
    b = Backup(full=a.full)
    b.collect()
    b.finish()
    git("add", "-A")
    changed = (git("status", "--porcelain").stdout or "").strip()
    n_local = count_sessions(CLAUDE_DIR)
    n_repo = count_sessions(os.path.join(REPO_DIR, "claude-home"))
    if changed:
        msg = "backup %s · %d files updated · %d conversations" % (
            time.strftime("%Y-%m-%d %H:%M"), b.copied, n_repo)
        git("commit", "-q", "-m", msg)
    pushed = False
    if not a.no_push:
        for wait in (0, 2, 4, 8, 16):
            time.sleep(wait)
            if git("push", "-u", "origin", "HEAD", check=False).returncode == 0:
                pushed = True
                break
    log("✓ backup done: %d files updated, %s" % (b.copied, "pushed" if pushed else
        ("NOT pushed (--no-push)" if a.no_push else "PUSH FAILED – commit is saved locally, will retry next run")))
    log("  conversations: %d on this machine, %d in the backup (backup never deletes)" % (n_local, n_repo))
    red = sum(b.counts.values()) + len(b.config_secrets)
    if red:
        log("  secrets blanked this run: %d  %s" % (red, json.dumps(b.counts) if b.counts else ""))
    for s in b.skipped:
        log("  ! skipped: " + s)
    if not pushed and not a.no_push:
        sys.exit(2)


# ---------------------------------------------------------------- restore

def enc_path(p):
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def remap_text(text, old, new):
    o, n = json.dumps(old)[1:-1], json.dumps(new)[1:-1]
    for key in ("cwd", "project"):
        text = re.sub(r'("%s"\s*:\s*")%s(?=[/"\\])' % (key, re.escape(o)),
                      lambda m: m.group(1) + n, text)
    return text


def cmd_restore(a):
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        if not a.remote:
            raise SystemExit("give --remote <git url of your backup repo> (or --repo owner/name with gh)")
        os.makedirs(STATE_DIR, exist_ok=True)
        run(["git", "clone", a.remote, REPO_DIR], capture=False)
        save_json(CONFIG_FILE, {"remote": a.remote})
    else:
        git("pull", "--rebase", "--autostash", "-q", check=False)
    man = load_json(os.path.join(REPO_DIR, "backup-manifest.json"), None)
    if not man:
        raise SystemExit("no backup-manifest.json in the repo – is this the right repository?")
    old_home = man.get("home", HOME)
    remap = old_home != HOME
    src_root = os.path.join(REPO_DIR, "claude-home")
    plan = []
    for full, rel in walk(src_root):
        out_rel = rel
        if remap and rel.startswith("projects/"):
            parts = rel.split("/")
            eo, en = enc_path(old_home), enc_path(HOME)
            if parts[1] == eo or parts[1].startswith(eo + "-"):
                parts[1] = en + parts[1][len(eo):]
                out_rel = "/".join(parts)
        plan.append((full, rel, os.path.join(CLAUDE_DIR, out_rel)))
    log("backup from %s (%s@%s), %d files, %d conversations" % (
        man.get("last_backup"), man.get("user"), man.get("host"), len(plan), count_sessions(src_root)))
    if remap:
        log("home folder differs (%s → %s): conversation folders will be re-pointed" % (old_home, HOME))
    if a.dry_run:
        log("dry run – nothing written.")
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safety = os.path.join(STATE_DIR, "pre-restore-" + stamp)
    while os.path.exists(safety):
        safety += "x"
    if os.path.isdir(CLAUDE_DIR):
        try:
            shutil.copytree(CLAUDE_DIR, os.path.join(safety, "claude-home"), symlinks=True,
                            ignore=shutil.ignore_patterns("cache", "debug", "shell-snapshots"))
        except shutil.Error as e:
            log("! some files could not be copied into the safety copy (%d)" % len(e.args[0]))
    if os.path.isfile(CLAUDE_JSON):
        os.makedirs(safety, exist_ok=True)
        shutil.copy2(CLAUDE_JSON, os.path.join(safety, "claude.json"))
    log("· safety copy of the current state: %s" % safety)

    mt = man.get("mtimes", {})
    wrote = kept = 0
    unfilled = []
    for full, rel, dest in plan:
        want = mt.get("claude-home/" + rel)
        with open(full, "rb") as f:
            raw = f.read()
        is_cfg = os.path.basename(rel) in JSON_CONFIGS
        if os.path.exists(dest) and not is_cfg:
            st = os.stat(dest)
            # a local file that is newer than the backed-up one (e.g. a conversation that
            # was continued here) wins; the safety copy has it either way
            if want and st.st_mtime > want + 1 and not a.force:
                kept += 1
                continue
            if want and abs(st.st_mtime - want) <= 1 and not a.force:
                continue  # unchanged since the backup; the local copy still has unredacted text
        if is_cfg:
            data, cur = None, load_json(dest, None)
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                pass
            if isinstance(data, dict):
                unfilled += ["claude-home/%s → %s" % (rel, x) for x in refill(data, cur)]
                raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        elif remap and (rel.endswith(".jsonl")):
            try:
                raw = remap_text(raw.decode("utf-8"), old_home, HOME).encode("utf-8")
            except UnicodeDecodeError:
                pass
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw)
        if rel.endswith((".sh", ".py")) or "/bin/" in rel:
            os.chmod(dest, 0o755)
        elif rel.startswith("projects/") or rel.endswith(".json"):
            os.chmod(dest, 0o600)  # conversations and configs are private to this user
        if want:
            os.utime(dest, (want, want))
        wrote += 1
    protect_history()

    # ~/.claude.json: backup is the base, this machine's account/login keys win
    bj = load_json(os.path.join(REPO_DIR, "claude.json"), None)
    if isinstance(bj, dict):
        cur = load_json(CLAUDE_JSON, {}) or {}
        if remap and isinstance(bj.get("projects"), dict):
            bj["projects"] = {(HOME + k[len(old_home):]) if (k == old_home or k.startswith(old_home + "/"))
                              else k: v for k, v in bj["projects"].items()}
        unfilled += ["~/.claude.json → " + x for x in refill(bj, cur)]
        merged = dict(bj)
        for k, v in cur.items():
            if k in ACCOUNT_KEYS or k.startswith("cached") or k not in merged:
                merged[k] = v
        if isinstance(cur.get("projects"), dict):
            p = dict(cur["projects"])
            p.update(merged.get("projects") or {})
            merged["projects"] = p
        save_json(CLAUDE_JSON, merged)
        os.chmod(CLAUDE_JSON, 0o600)

    # git-ignored per-project personal files
    idx = load_json(os.path.join(REPO_DIR, "project-local", "index.json"), {}) or {}
    for enc, proj in idx.items():
        if remap and (proj == old_home or proj.startswith(old_home + "/")):
            proj = HOME + proj[len(old_home):]
        base = os.path.join(REPO_DIR, "project-local", enc)
        if not os.path.isdir(proj) or not os.path.isdir(base):
            continue
        for full, rel in walk(base):
            dest = os.path.join(proj, rel)
            if not os.path.exists(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(full, dest)

    if a.desktop and os.path.isdir(os.path.join(REPO_DIR, "desktop-app")):
        n = 0
        if os.path.isdir(DESKTOP_DIR):
            shutil.copytree(DESKTOP_DIR, os.path.join(safety, "desktop-app"), symlinks=True,
                            ignore=lambda d, names: [x for x in names if x in DESKTOP_EXCLUDE]
                            if os.path.realpath(d) == os.path.realpath(DESKTOP_DIR) else [])
        target = current_desktop_account(a.desktop_account)
        sources = man.get("desktop_accounts") or []
        if target:
            log("· desktop app is signed in as account %s (org %s)" % (target[0], target[1]))
        else:
            log("! could not tell which account the desktop app is signed in to. Open the app, sign in,"
                " start one Code conversation, quit it and run restore again (or pass --desktop-account)."
                " Old Code tab conversations are restored under the old account folder for now.")
        moved = 0
        for full, rel in walk(os.path.join(REPO_DIR, "desktop-app")):
            out_rel = rel
            parts = rel.split("/")
            if target and len(parts) > 3 and parts[0] in ACCOUNT_SCOPED and parts[1:3] != target:
                parts[1:3] = target
                out_rel = "/".join(parts)
                moved += 1
            if parts[-1] == "archived-sessions.idx" and out_rel != rel:
                out_rel = None  # merged below
            if out_rel is None:
                continue
            dest = os.path.join(DESKTOP_DIR, out_rel)
            want = mt.get("desktop-app/" + rel)
            # Only add what is missing. Files that exist belong to the running app / new
            # login (config.json holds its sign-in), and the backup copies are redacted.
            if os.path.exists(dest) and not a.force:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if remap and parts[0] in ACCOUNT_SCOPED and rel.endswith(".json"):
                # sidebar entries store absolute folder paths (cwd, originCwd, ...)
                o, nw = json.dumps(old_home + "/")[1:-1], json.dumps(HOME + "/")[1:-1]
                with open(full, encoding="utf-8") as f:
                    txt = f.read().replace('"%s' % o, '"%s' % nw)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(txt)
            else:
                shutil.copyfile(full, dest)
            os.chmod(dest, 0o600)  # the app keeps all of its files owner-only
            if want:
                os.utime(dest, (want, want))
            n += 1
        # keep the archived flags of old conversations when they move to the new account
        if target:
            arch = set()
            for src in sources:
                if src != target:
                    idx = load_json(os.path.join(REPO_DIR, "desktop-app", "claude-code-sessions",
                                                 src[0], src[1], "archived-sessions.idx"), {}) or {}
                    arch |= set(idx.get("archived") or [])
            if arch:
                ip = os.path.join(DESKTOP_DIR, "claude-code-sessions", target[0], target[1], "archived-sessions.idx")
                cur = load_json(ip, {}) or {}
                merged = sorted(set(cur.get("archived") or []) | arch)
                save_json(ip, {"v": cur.get("v", 1), "archived": merged}, indent=None)
        if moved:
            log("· %d Code tab sidebar files moved from the old account folder to the signed-in one" % moved)
        log("· desktop app data restored: %d files" % n)

    if remap:
        repoint_repo(man, old_home)
    log("✓ restored %d files (%d newer local files kept). conversations now on disk: %d" % (
        wrote, kept, count_sessions(CLAUDE_DIR)))
    if unfilled:
        log("  secrets you still need to type back in:")
        for u in sorted(set(unfilled)):
            log("   - " + u)
    log("next: start `claude`, run /login with the new account, then `claude --resume` inside a project.")


# ---------------------------------------------------------------- folder ids (survive move / rename)
# Claude ties every conversation to a folder's full path. A tiny hidden file inside each project
# folder carries a random id, so after the folder is moved, renamed or put on an external disk we
# can find it again and point its conversations at the new place.

FOLDER_ID_FILE = ".claude-folder-id"
FOLDER_REG = os.path.join(STATE_DIR, "folder-ids.json")
SEARCH_SKIP = {"Library", ".Trash", "node_modules", ".git", "Applications", ".cache", ".npm",
               ".Trash-1000", "System", "Pictures", "Music", "Movies", ".claude", ".claude-backup",
               "__pycache__", ".venv", "venv", "dist", "build"}


def project_dirs():
    """Folders the Code tab conversations use (main folder + extra folders), that exist now."""
    found = set()
    for f in sorted(_glob(os.path.join(DESKTOP_DIR, "claude-code-sessions", "*", "*", "local_*.json"))):
        d = load_json(f, {}) or {}
        cands = [d.get("cwd"), d.get("originCwd")]
        for u in d.get("sessionPermissionUpdates") or []:
            cands += u.get("directories") or [] if isinstance(u, dict) else []
        found |= {c for c in cands if isinstance(c, str)}
    found |= set(((load_json(CLAUDE_JSON, {}) or {}).get("projects") or {}).keys())
    out = []
    for p in sorted(found):
        if not os.path.isdir(p) or p.rstrip("/") in (HOME, "/", ""):
            continue
        if os.path.realpath(p).startswith(os.path.realpath(DESKTOP_DIR) + "/"):
            continue  # the app's own scratch folders: backed up whole, never moved by the user
        if os.path.realpath(p).startswith(os.path.realpath(CLAUDE_DIR) + "/"):
            continue
        out.append(p)
    return out


def _glob(pat):
    import glob
    return glob.glob(pat)


def read_folder_id(p):
    try:
        with open(os.path.join(p, FOLDER_ID_FILE), encoding="utf-8") as f:
            return (json.load(f) or {}).get("id")
    except (OSError, ValueError):
        return None


def tag_folders():
    """Give every project folder a hidden id file; return {id: path} for all of them."""
    import uuid
    reg = load_json(FOLDER_REG, {}) or {}
    for p in project_dirs():
        fid = read_folder_id(p)
        if not fid:
            fid = uuid.uuid4().hex
            try:
                with open(os.path.join(p, FOLDER_ID_FILE), "w", encoding="utf-8") as f:
                    json.dump({"id": fid, "note": "Claude backup: lets conversations find this folder "
                               "after it is moved or renamed. Safe to keep; please don't delete."}, f)
                    f.write("\n")
            except OSError:
                continue
            ex = os.path.join(p, ".git", "info", "exclude")  # keep it out of git repos
            if os.path.isdir(os.path.dirname(ex)):
                try:
                    cur = open(ex).read() if os.path.exists(ex) else ""
                    if FOLDER_ID_FILE not in cur:
                        with open(ex, "a") as f:
                            f.write(("\n" if cur and not cur.endswith("\n") else "") + FOLDER_ID_FILE + "\n")
                except OSError:
                    pass
        old = reg.get(fid)
        reg[fid] = p if not isinstance(old, dict) else p
    save_json(FOLDER_REG, reg)
    return reg


def find_folder_ids(wanted):
    """Search the home folder and external disks for id files. {id: [paths]}"""
    roots = [HOME] + [os.path.join("/Volumes", v) for v in (os.listdir("/Volumes") if os.path.isdir("/Volumes") else [])
                      if not os.path.realpath(os.path.join("/Volumes", v)) == "/"]
    hits = {}
    for root in roots:
        base_depth = root.rstrip("/").count("/")
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count("/") - base_depth >= 7:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in SEARCH_SKIP and not d.endswith((".app", ".photoslibrary"))]
            if FOLDER_ID_FILE in filenames:
                fid = read_folder_id(dirpath)
                if fid in wanted:
                    hits.setdefault(fid, []).append(dirpath)
    return hits


def _replace_path(text, old, new):
    """Replace a folder path inside JSON text, only as a whole path (followed by / or a quote)."""
    for asc in (False, True):  # files may keep Chinese as-is or as \\u escapes
        o, n = json.dumps(old, ensure_ascii=asc)[1:-1], json.dumps(new, ensure_ascii=asc)[1:-1]
        text = re.sub(re.escape(o) + r'(?=["/\\])', lambda m: n, text)
    return text


def remap_folder(old, new):
    """Point every conversation that used folder `old` at `new`."""
    changed = 0
    for f in _glob(os.path.join(DESKTOP_DIR, "claude-code-sessions", "*", "*", "local_*.json")):
        with open(f, encoding="utf-8") as fh:
            t = fh.read()
        t2 = _replace_path(t, old, new)
        if t2 != t:
            st = os.stat(f)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(t2)
            os.utime(f, (st.st_atime, st.st_mtime))
            changed += 1
    proj = os.path.join(CLAUDE_DIR, "projects")
    eo = enc_path(old)
    if os.path.isdir(proj):
        for name in sorted(os.listdir(proj)):
            if not (name == eo or name.startswith(eo + "-")):
                continue
            src = os.path.join(proj, name)
            cwd = None  # the folder name is lossy: confirm from a conversation's own cwd
            for fn in os.listdir(src):
                if fn.endswith(".jsonl"):
                    with open(os.path.join(src, fn), encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            m = re.search(r'"cwd":\s*"((?:[^"\\]|\\.)*)"', line)
                            if m:
                                cwd = json.loads('"%s"' % m.group(1))
                                break
                if cwd:
                    break
            if not cwd or not (cwd == old or cwd.startswith(old + "/")):
                continue
            new_cwd = new + cwd[len(old):]
            dst = os.path.join(proj, enc_path(new_cwd))
            for root, _, files in os.walk(src):
                for fn in files:
                    if fn.endswith(".jsonl"):
                        fp = os.path.join(root, fn)
                        st = os.stat(fp)
                        with open(fp, encoding="utf-8", errors="surrogateescape") as fh:
                            t = fh.read()
                        t2 = _replace_path(t, old, new)
                        if t2 != t:
                            with open(fp, "w", encoding="utf-8", errors="surrogateescape") as fh:
                                fh.write(t2)
                            os.utime(fp, (st.st_atime, st.st_mtime))
            if src != dst:
                if os.path.exists(dst):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    shutil.rmtree(src)
                else:
                    os.rename(src, dst)
            changed += 1
    cj = load_json(CLAUDE_JSON, None)
    if isinstance(cj, dict) and isinstance(cj.get("projects"), dict):
        pr = cj["projects"]
        moved = {k: new + k[len(old):] for k in pr if k == old or k.startswith(old + "/")}
        if moved:
            for k, nk in moved.items():
                if nk not in pr:
                    pr[nk] = pr[k]
                del pr[k]
            save_json(CLAUDE_JSON, cj)
            os.chmod(CLAUDE_JSON, 0o600)
            changed += 1
    return changed


def relink_folders(reg=None):
    """Find moved / renamed project folders by their id file and re-point their conversations.
    Returns a list of human-readable notes."""
    reg = reg if reg is not None else (load_json(FOLDER_REG, {}) or {})
    lost = {fid: p for fid, p in reg.items() if isinstance(p, str) and read_folder_id(p) != fid}
    if not lost:
        return []
    seen = load_json(os.path.join(STATE_DIR, "folder-search.json"), {}) or {}
    key = ",".join(sorted(lost))
    if seen.get("key") == key and time.time() - seen.get("at", 0) < 6 * 3600:
        return []  # same folders still missing; don't search the disk every 10 minutes
    hits = find_folder_ids(set(lost))
    notes, still = [], []
    for fid, old in sorted(lost.items(), key=lambda x: -len(x[1])):
        places = hits.get(fid, [])
        if len(places) == 1:
            n = remap_folder(old, places[0])
            reg[fid] = places[0]
            notes.append("folder moved: %s → %s (%d records updated)" % (old, places[0], n))
        elif len(places) > 1:
            notes.append("folder copied, not sure which one is used: %s → %s" % (old, places))
            still.append(fid)
        else:
            still.append(fid)
    save_json(FOLDER_REG, reg)
    save_json(os.path.join(STATE_DIR, "folder-search.json"),
              {"key": ",".join(sorted(still)), "at": time.time()} if still else {})
    for nt in notes:
        log("· " + nt)
    return notes


def cmd_relink(a):
    notes = relink_folders()
    tag_folders()
    log("✓ folders checked%s" % ("" if not notes else ". Quit Claude (⌘Q) and reopen it to see the change."))


# ---------------------------------------------------------------- clean account switch
# pack:   copy Code-tab conversations, settings, skills, plugins into a folder, with every trace
#         of the old Claude account (account/org ids, login email, request ids, thinking
#         signatures, claude.ai links) removed or replaced by placeholders.
# unpack: after signing in with the new account, put it all back under the new account's ids.

P_ACCT = "00000000-0000-4000-8000-00000000a001"   # same length as a real uuid, keeps paths valid
P_ORG = "00000000-0000-4000-8000-00000000b002"
P_EMAIL = "claude-account@email.invalid"
CLAUDE_LINK = re.compile(r"(?:[a-z]+://)?(?:[a-z0-9-]+\.)?claude\.ai/[^\s\"'\\)\]>]*", re.I)
# a claude.ai link that points at something of the account (chat, artifact, session, project ...)
HAS_LINK = re.compile(r"claude\.ai/", re.I)


def account_links(t):
    i = t.find("claude.ai/")
    while i >= 0:
        seg = re.match(r"[^\s\"'\\)\]>]*", t[i + 10:i + 400]).group(0)
        if ACCOUNT_LINK.search(seg):
            return True
        i = t.find("claude.ai/", i + 10)
    return False


SERVER_REQ = re.compile(r"\breq_(?!removed)[A-Za-z0-9]{16,}")
SERVER_ID = re.compile(r"\b(msg|toolu|srvtoolu)_(?!x[0-9a-f]{24})([A-Za-z0-9]{16,})")
ACCOUNT_LINK = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}|[A-Za-z0-9_]{20,}")
DROP_LINE_KEYS = {"requestId", "requestRef", "requestDigest", "bridgeSessionId", "deliveryId",
                  "quotaLimits", "serverClassifierRequest", "serverClassifierContext", "wireIngestContext"}
SIDEBAR_DROP = {"remoteMcpServersConfig"}
CJ_KEEP = {"projects", "mcpServers", "theme", "editorMode", "autoUpdates", "verbose",
           "preferredNotifChannel", "autoCompactEnabled", "diffTool", "env"}
PACK_CLAUDE_EXCLUDE = CLAUDE_EXCLUDE | {".claude.json", "settings.json.bak-20261113"}
PACK_PREFIX_EXCLUDE = ("remote-settings", "policy-limits", "settings.json.bak")
ARCHIVE_NAME = "Claude旧账号原始数据-"
SELF_SKILL = "skills/ai-backup/"
RESTORE_BUTTON = "Claude换号-一键恢复.command"


def old_identity():
    cj = load_json(CLAUDE_JSON, {}) or {}
    oa = cj.get("oauthAccount") or {}
    accts, orgs = set(), set()
    if oa.get("accountUuid"):
        accts.add(oa["accountUuid"])
    if oa.get("organizationUuid"):
        orgs.add(oa["organizationUuid"])
    for a, o in desktop_accounts(DESKTOP_DIR):
        accts.add(a)
        orgs.add(o)
    la = (load_json(os.path.join(DESKTOP_DIR, "config.json"), {}) or {}).get("lastKnownAccountUuid")
    if la:
        accts.add(la)
    emails = {e for e in [oa.get("emailAddress")] if e}
    other = {v for v in [cj.get("userID"), cj.get("machineID"), cj.get("anonymousId"),
                         (load_json(os.path.join(CLAUDE_DIR, ".claude.json"), {}) or {}).get("userID")] if v}
    return sorted(accts), sorted(orgs), sorted(emails), sorted(other)


class Scrubber:
    def __init__(self, ident, salt):
        self.accts, self.orgs, self.emails, self.other = ident
        self.salt = salt
        self.email_re = [re.compile(re.escape(e), re.I) for e in self.emails]
        # the email's name part on its own, and 8-character id prefixes ("1234abcd-…")
        self.local_re = [re.compile(re.escape(e.split("@")[0]), re.I) for e in self.emails
                         if len(e.split("@")[0]) >= 6]
        self.prefixes = [(x[:8], P_ACCT[:8]) for x in self.accts] + [(x[:8], P_ORG[:8]) for x in self.orgs] + \
                        [(x[:8], "removed0") for x in self.other if len(x) >= 16]
        self.counts = {}

    def text(self, t):
        for a in self.accts:
            t = t.replace(a, P_ACCT)
        for o in self.orgs:
            t = t.replace(o, P_ORG)
        for r in self.email_re:
            t = r.sub(P_EMAIL, t)
        for x in self.other:
            t = t.replace(x, "removed-id")
        for r in self.local_re:
            t = r.sub("claude-account", t)
        for x, y in self.prefixes:
            t = re.sub(r"(?<![0-9a-fA-F])%s" % re.escape(x), y, t)
        if HAS_LINK.search(t):
            t = CLAUDE_LINK.sub(lambda m: "[old claude.ai link removed]" if ACCOUNT_LINK.search(m.group(0))
                                else m.group(0), t)
        # ids the old account's API handed out: request ids go, message/tool ids get a new
        # consistent name (tool calls and their results must still match each other)
        t = SERVER_REQ.sub("req_removed", t)
        t = SERVER_ID.sub(lambda m: m.group(1) + "_x" + self._hash(m.group(2)), t)
        return redact_text(t, self.counts)

    def _hash(self, v):
        import hashlib
        return hashlib.sha256((self.salt + v).encode()).hexdigest()[:24]

    def jsonl(self, t):
        rows, dropped = [], {}
        for line in t.split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                rows.append(line)
                continue
            if not isinstance(d, dict):
                rows.append(d)
                continue
            for k in DROP_LINE_KEYS:
                d.pop(k, None)
            m = d.get("message")
            if isinstance(m, dict):
                c = m.get("content")
                if isinstance(c, list):
                    kept = [b for b in c if not (isinstance(b, dict) and
                                                 b.get("type") in ("thinking", "redacted_thinking"))]
                    if len(kept) != len(c):
                        if not kept and d.get("uuid"):
                            dropped[d["uuid"]] = d.get("parentUuid")
                            continue
                        m["content"] = kept
            rows.append(d)

        def up(u):
            seen = 0
            while u in dropped and seen < 10000:
                u, seen = dropped[u], seen + 1
            return u
        out = []
        for d in rows:
            if isinstance(d, dict):
                for k in ("parentUuid", "logicalParentUuid", "leafUuid"):
                    if d.get(k) in dropped:
                        d[k] = up(d[k])
                d = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
            elif not isinstance(d, str):
                d = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
            out.append(self.text(d))
        return "\n".join(out) + "\n"


INC = {"on": False, "old": {}, "new": {}, "produced": set(), "changed": []}

# Conversations too big for GitHub wait for the person to decide: compress / skip / delete.
BIG_FILE = os.path.join(STATE_DIR, "big-files.json")   # {"<file name>": {"choice": "compress"|"skip", ...}}
BIG_PENDING = []                                       # filled while packing, written to status.json
PART = 90 * 1024 * 1024


def big_id(path):
    """Conversations are named by their own id; any other file by where it is."""
    return os.path.basename(path) if path.endswith(".jsonl") else os.path.abspath(path)


def big_choices():
    return load_json(BIG_FILE, {}) or {}


def _big_outputs(dest):
    d = os.path.dirname(dest)
    base = os.path.basename(dest)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in os.listdir(d)
            if n == base + ".gz" or (n.startswith(base + ".gz.part") and n[len(base) + 8:].isdigit())]


def _pack_file(sc, src, dest, kind, mt, key):
    st = os.stat(src)
    sig = [st.st_mtime_ns, st.st_size]
    INC["produced"].add(key)
    mt[key] = int(st.st_mtime)
    if INC["on"] and INC["old"].get(key) == sig and (os.path.exists(dest) or _big_outputs(dest)):
        INC["new"][key] = sig
        for o in _big_outputs(dest):
            INC["produced"].add(key[:-len(os.path.basename(dest))] + os.path.basename(o))
        return True  # unchanged since last pack: the scrubbed copy is still right
    ok = _pack_file_now(sc, src, dest, kind, mt, key)
    if ok:
        INC["new"][key] = sig
        INC["changed"].append(key)
    return ok


def _pack_file_now(sc, src, dest, kind, mt, key):
    big = os.path.getsize(src) > MAX_FILE
    choice = (big_choices().get(big_id(src)) or {}).get("choice") if big else None
    if big and choice == "skip":
        return True   # the person said: don't upload this one
    if big and choice != "compress":
        BIG_PENDING.append({"name": big_id(src), "path": src, "mb": os.path.getsize(src) >> 20})
        log("  ! waiting for your decision (over GitHub's 100 MB limit): %s" % key)
        return True
    with open(src, "rb") as f:
        raw = f.read()
    try:
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        t = None
    if t is not None:
        if kind == "jsonl":
            t = sc.jsonl(t)
        elif kind == "sidebar":
            d = json.loads(t)
            for k in SIDEBAR_DROP:
                d.pop(k, None)
            t = sc.text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
        elif kind == "config":
            d = None
            try:
                d = json.loads(t)
            except ValueError:
                pass
            if isinstance(d, dict):
                scrub_config(d, [], [])
                t = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
            t = sc.text(t)
        else:
            t = sc.text(t)
        raw = t.encode("utf-8")
    elif any(x.encode() in raw for x in sc.accts + sc.orgs + sc.emails):
        return False   # binary file that names the old account: leave it behind
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for old in _big_outputs(dest):
        os.remove(old)
    if big:   # compress, and cut into parts if it is still too big
        import gzip
        z = gzip.compress(raw, compresslevel=9, mtime=0)
        if os.path.exists(dest):
            os.remove(dest)
        if len(z) <= MAX_FILE:
            outs = [(dest + ".gz", z)]
        else:
            outs = [(dest + ".gz.part%03d" % i, z[o:o + PART]) for i, o in enumerate(range(0, len(z), PART))]
        for path, chunk in outs:
            with open(path, "wb") as f:
                f.write(chunk)
            INC["produced"].add(key[:-len(os.path.basename(dest))] + os.path.basename(path))
    else:
        with open(dest, "wb") as f:
            f.write(raw)
    mt[key] = int(os.stat(src).st_mtime)
    return True


def pack_salt():
    """Kept on this Mac only (never in the repo): renames message/tool ids the same way every day."""
    path = os.path.join(STATE_DIR, "pack-salt")
    if not os.path.exists(path):
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(os.urandom(16).hex())
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


def cmd_pack(a):
    out = os.path.abspath(os.path.expanduser(a.out))
    if os.path.exists(os.path.join(out, "pack-manifest.json")) and not a.overwrite:
        raise SystemExit("%s already has a pack. Use --overwrite to replace it." % out)
    ident = old_identity()
    if not ident[0]:
        raise SystemExit("could not find the current Claude account on this Mac – nothing to pack")
    import hashlib
    salt = pack_salt()
    ihash = hashlib.sha256(json.dumps([ident, salt]).encode()).hexdigest()
    spath = os.path.join(STATE_DIR, "pack-state.json")
    prev = load_json(spath, {}) or {}
    full_run = getattr(a, "full", False) or prev.get("out") != out or prev.get("ident") != ihash
    INC.update(on=not full_run, old={} if full_run else prev.get("files", {}), new={},
               produced=set(), changed=[])
    if full_run:
        for sub in ("claude-home", "desktop"):
            shutil.rmtree(os.path.join(out, sub), ignore_errors=True)
    sc = Scrubber(ident, salt)
    mt, links, left = {}, {}, []
    n = 0
    # 1. ~/.claude : conversations, memory, skills, agents, commands, settings, plugins
    for top in ("skills", "agents", "commands"):
        base = os.path.join(CLAUDE_DIR, top)
        if os.path.isdir(base):
            for name in os.listdir(base):
                full = os.path.join(base, name)
                if os.path.islink(full):
                    links["%s/%s" % (top, name)] = os.path.realpath(full)
    for full, rel in walk(CLAUDE_DIR, PACK_CLAUDE_EXCLUDE, CLAUDE_EXCLUDE_REL):
        if rel.split("/")[0].startswith(PACK_PREFIX_EXCLUDE) or "/.in_use/" in rel:
            continue
        if rel.startswith(SELF_SKILL):  # this tool itself: copy as is (it holds the placeholders)
            dest = os.path.join(out, "claude-home", rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(full, dest)
            INC["produced"].add("claude-home/" + rel)
            continue
        kind = "jsonl" if rel.startswith("projects/") and rel.endswith(".jsonl") else \
               ("config" if os.path.basename(rel) in JSON_CONFIGS else "text")
        prel = sc.text(rel)
        if _pack_file(sc, full, os.path.join(out, "claude-home", prel), kind, mt, "claude-home/" + prel):
            n += 1
        else:
            left.append(rel)
    # 2. ~/.claude.json : only per-project settings, MCP servers and plain preferences
    cj = load_json(CLAUDE_JSON, {}) or {}
    keep = {k: v for k, v in cj.items() if k in CJ_KEEP}
    scrub_config(keep, [], [])
    with open(os.path.join(out, "claude.json"), "w", encoding="utf-8") as f:
        f.write(sc.text(json.dumps(keep, ensure_ascii=False, indent=2)) + "\n")
    # 3. desktop app: Code tab sidebar entries, their work folders, app preferences
    for acct, org in desktop_accounts(DESKTOP_DIR):
        base = os.path.join(DESKTOP_DIR, "claude-code-sessions", acct, org)
        for fn in sorted(os.listdir(base)):
            if fn.startswith("local_") and fn.endswith(".json"):
                kind = "sidebar"
            elif fn in ("archived-sessions.idx", "scheduled-tasks.json"):
                kind = "text"
            else:
                continue
            dest_rel = "desktop/claude-code-sessions/%s/%s/%s" % (P_ACCT, P_ORG, fn)
            if _pack_file(sc, os.path.join(base, fn), os.path.join(out, dest_rel), kind, mt, dest_rel):
                n += 1
        sw = os.path.join(DESKTOP_DIR, "scratch-workspaces", acct, org)
        if os.path.isdir(sw):
            for full, rel in walk(sw):
                dest_rel = "desktop/scratch-workspaces/%s/%s/%s" % (P_ACCT, P_ORG, sc.text(rel))
                if _pack_file(sc, full, os.path.join(out, dest_rel), "text", mt, dest_rel):
                    n += 1
                else:
                    left.append("scratch-workspaces/" + rel)
    cfg = os.path.join(DESKTOP_DIR, "claude_desktop_config.json")
    if os.path.isfile(cfg):
        _pack_file(sc, cfg, os.path.join(out, "desktop", "claude_desktop_config.json"), "config", mt,
                   "desktop/claude_desktop_config.json")
    save_json(os.path.join(out, "pack-manifest.json"), {
        "format": 1, "packed": time.strftime("%Y-%m-%d %H:%M:%S"), "home": HOME,
        "mtimes": mt, "links": {k: sc.text(v) for k, v in links.items()}, "left_behind": left})
    os.makedirs(os.path.join(out, "tool"), exist_ok=True)
    shutil.copy2(os.path.abspath(__file__), os.path.join(out, "tool", "claude_backup.py"))
    here = os.path.dirname(os.path.abspath(__file__))
    for name in (RESTORE_BUTTON, "README.md"):
        src = os.path.join(here, "repo-files", name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, name))
            if name.endswith(".command"):
                os.chmod(os.path.join(out, name), 0o755)
    # files whose source is gone (e.g. Claude's own 30-day cleanup) leave the pack too
    removed = 0
    for sub in ("claude-home", "desktop"):
        for full, rel in list(walk(os.path.join(out, sub))):
            if "%s/%s" % (sub, rel) not in INC["produced"]:
                os.remove(full)
                removed += 1
        for d, dirs, files in os.walk(os.path.join(out, sub), topdown=False):
            if not dirs and not files and d != os.path.join(out, sub):
                os.rmdir(d)
    save_json(spath, {"out": out, "ident": ihash, "files": INC["new"]}, indent=None)
    log("✓ packed into %s: %d changed, %d removed%s (conversations: %d)" % (
        out, len(INC["changed"]), removed, " [full]" if full_run else "",
        count_sessions(os.path.join(out, "claude-home"))))
    if left:
        log("  left behind %d binary files that contain the old account id" % len(left))
    only = None if full_run else set(INC["changed"]) | {"claude.json", "pack-manifest.json"}
    bad = verify_pack(out, ident, only)
    if bad:
        raise SystemExit("! VERIFY FAILED – old account info still found in %d files, e.g. %s" % (len(bad), bad[:5]))
    log("✓ verified: no old account id, org id, email, login or claude.ai link left in the pack")


def verify_pack(out, ident, only=None):
    accts, orgs, emails, other = ident
    needles = [x.lower() for x in accts + orgs + other] + [x[:8].lower() for x in accts + orgs + other]
    needles += [e.lower() for e in emails] + [e.split("@")[0].lower() for e in emails if len(e.split("@")[0]) >= 6]
    needles += ['"signa' + 'ture":"']  # split so this file does not match itself
    bad = []
    for full, rel in walk(out):
        if rel.startswith("tool/") or (only is not None and rel not in only):
            continue
        with open(full, "rb") as f:
            t = f.read().decode("utf-8", "replace").lower()
        hay = rel.lower() + "\n" + t
        if any(x in hay for x in needles) or SERVER_REQ.search(t) or account_links(t):
            bad.append(rel)
    return bad


def cmd_verify(a):
    ident = old_identity()
    bad = verify_pack(os.path.abspath(os.path.expanduser(a.dir)), ident)
    log("✓ clean" if not bad else "! old account info found in:\n  " + "\n  ".join(bad[:50]))


def claude_app_running():
    p = run(["pgrep", "-x", "Claude"], check=False)
    return p.returncode == 0


def cmd_move_old(a):
    """Move the old account's raw data out of the places Claude reads, keeping the big
    downloads (VM image, bundled CLI) so the new login does not re-download 10 GB."""
    if claude_app_running():
        raise SystemExit("Quit the Claude app first (⌘Q), then run this again.")
    arch = os.path.join(HOME, ARCHIVE_NAME + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(arch)
    for src, name in ((CLAUDE_DIR, "dot-claude"), (CLAUDE_JSON, "dot-claude.json"),
                      (DESKTOP_DIR, "AppSupport-Claude"),
                      (os.path.join(HOME, "claude-test-safety"), "claude-test-safety"),
                      (os.path.join(HOME, ".claude-backup-test"), "dot-claude-backup-test")):
        if os.path.exists(src):
            os.rename(src, os.path.join(arch, name))
    old_app = os.path.join(arch, "AppSupport-Claude")
    if os.path.isdir(old_app):
        os.makedirs(DESKTOP_DIR, mode=0o700)
        for keep in ("vm_bundles", "claude-code", "claude-code-vm"):
            if os.path.exists(os.path.join(old_app, keep)):
                os.rename(os.path.join(old_app, keep), os.path.join(DESKTOP_DIR, keep))
        sd = os.path.join(DESKTOP_DIR, "vm_bundles", "claudevm.bundle", "sessiondata.img")
        if os.path.exists(sd):  # Cowork's working disk of the old account
            os.rename(sd, os.path.join(old_app, "sessiondata.img"))
    save_json(PENDING, {"archive": arch, "started": time.strftime("%Y-%m-%d %H:%M:%S")})
    log("✓ old account data moved to %s\n  (Claude can no longer see it. Delete it once the new account works.)" % arch)


def new_identity(override=None):
    cj = load_json(CLAUDE_JSON, {}) or {}
    oa = cj.get("oauthAccount") or {}
    t = current_desktop_account(override)
    if not t:
        return None
    return t[0], t[1], (oa.get("emailAddress") if oa.get("accountUuid") == t[0] else None)


def cmd_wait_login(a):
    """Block until the Claude app has been signed in (an account folder + ~/.claude.json exist)
    and the app has been quit again."""
    log("waiting: sign in with the NEW account, send one message in the Code tab, then quit with ⌘Q ...")
    while True:
        if not claude_app_running() and new_identity():
            log("✓ new account detected: %s" % new_identity()[0])
            return
        time.sleep(3)


def cmd_has_old(a):
    """exit 0: this Mac holds the current account's data and no switch is half done."""
    sys.exit(0 if old_identity()[0] and not os.path.exists(PENDING) else 1)


def cmd_adopt(a):
    """Run from inside the NEW account's Code tab (app running). Pull the GitHub backup,
    move the old account's raw data aside (except this account's own sessions), and put the
    clean backup in place under the new account. The user then quits and reopens the app."""
    use_system_proxy()
    acct_org = current_desktop_account(a.desktop_account)
    if not acct_org:
        raise SystemExit("Can't tell which account the app is signed in to. Send one message in the Code tab first.")
    acct, org = acct_org
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        os.makedirs(STATE_DIR, exist_ok=True)
        run(["gh", "repo", "clone", a.repo, REPO_DIR])
    else:
        git("pull", "-q", check=False)
    # sessions that belong to the signed-in (new) account stay where they are
    mine = set()
    base = os.path.join(DESKTOP_DIR, "claude-code-sessions", acct, org)
    if os.path.isdir(base):
        for fn in os.listdir(base):
            if fn.startswith("local_") and fn.endswith(".json"):
                c = (load_json(os.path.join(base, fn), {}) or {}).get("cliSessionId")
                if c:
                    mine.add(c)
    arch = os.path.join(HOME, ARCHIVE_NAME + time.strftime("%Y%m%d-%H%M%S"))
    moved = 0

    def away(src, rel):
        nonlocal moved
        if os.path.lexists(src):
            dst = os.path.join(arch, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            moved += 1
    # desktop: every other account's folders
    for top in ("claude-code-sessions", "scratch-workspaces", "local-agent-mode-sessions", "plugin-list"):
        d = os.path.join(DESKTOP_DIR, top)
        if os.path.isdir(d):
            for a_ in os.listdir(d):
                if a_ != acct and a_ not in ("skills-plugin",):
                    away(os.path.join(d, a_), "AppSupport-Claude/%s/%s" % (top, a_))
    # ~/.claude: old conversations and anything that may quote them
    proj = os.path.join(CLAUDE_DIR, "projects")
    if os.path.isdir(proj):
        for pd in os.listdir(proj):
            pdir = os.path.join(proj, pd)
            if not os.path.isdir(pdir):
                continue
            for fn in os.listdir(pdir):
                sid = fn[:-6] if fn.endswith(".jsonl") else fn
                if sid not in mine:
                    away(os.path.join(pdir, fn), "dot-claude/projects/%s/%s" % (pd, fn))
    for name in ("history.jsonl", "file-history", "todos", "plans", "tasks", "paste-cache",
                 "shell-snapshots", "session-env", "sessions", "backups", "telemetry", "debug", ".claude.json"):
        away(os.path.join(CLAUDE_DIR, name), "dot-claude/" + name)
    for name in ("claude-test-safety", ".claude-backup-test"):
        away(os.path.join(HOME, name), name)
    log("· moved %d old items to %s (Claude can't see them; delete after checking)" % (moved, arch))
    a.src, a.allow_running = REPO_DIR, True
    cmd_unpack(a)
    log("NEXT: quit the Claude app with ⌘Q and open it again – the old conversations will be in the sidebar.")


def cmd_setup(a):
    """One step on any Mac, after installing this tool: restore if this account is new and the
    backup has conversations; otherwise start backing up. Then turn on the 10-minute sync."""
    use_system_proxy()
    if not shutil.which("gh"):
        raise SystemExit("GitHub CLI missing. Install it: brew install gh   (no Homebrew? https://brew.sh first)")
    if run(["gh", "auth", "status"], check=False).returncode != 0:
        raise SystemExit("GitHub CLI is not logged in. Ask the user to run in Terminal: gh auth login")
    user = (run(["gh", "api", "user", "--jq", ".login"]).stdout or "").strip()
    repo = a.repo if "/" in a.repo else "%s/%s" % (user, a.repo)
    exists = run(["gh", "repo", "view", repo], check=False).returncode == 0
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        if exists:
            os.makedirs(STATE_DIR, exist_ok=True)
            run(["gh", "repo", "clone", repo, REPO_DIR])
            run(["gh", "auth", "setup-git"], check=False)
        else:
            a.remote = None
            a.repo = repo
            cmd_init(a)
    else:
        git("pull", "-q", check=False)
    here, there = count_sessions(CLAUDE_DIR), count_sessions(os.path.join(REPO_DIR, "claude-home"))
    if there >= 5 and here < there * 0.5:
        log("· this account has %d conversations, the backup has %d → restoring" % (here, there))
        a.repo = repo
        cmd_adopt(a)
    else:
        log("· backing up this Mac (%d conversations)" % here)
        a.no_push, a.force = False, False
        cmd_sync(a)
    a.every, a.time = 10, "23:00"
    cmd_schedule(a)


def cmd_unpack(a):
    src = os.path.abspath(os.path.expanduser(a.src))
    man = load_json(os.path.join(src, "pack-manifest.json"), None)
    if not man:
        raise SystemExit("%s is not a pack folder" % src)
    if claude_app_running() and not a.allow_running:
        raise SystemExit("Quit the Claude app first (⌘Q), then run this again.")
    ni = new_identity(a.desktop_account)
    if not ni:
        raise SystemExit("Can't tell which account is signed in. Open Claude, sign in with the new account, "
                         "send one message in the Code tab, quit with ⌘Q, then run this again.")
    acct, org, email = ni
    old_home = man.get("home", HOME)

    def fix(t):
        t = t.replace(P_ACCT, acct).replace(P_ORG, org)
        if email:
            t = t.replace(P_EMAIL, email)
        if old_home != HOME:
            t = t.replace(json.dumps(old_home + "/")[1:-1], json.dumps(HOME + "/")[1:-1])
            t = t.replace(enc_path(old_home) + "-", enc_path(HOME) + "-")
        return t
    links = {fix(k): fix(v) for k, v in (man.get("links") or {}).items()}
    linked = {k for k, v in links.items() if os.path.exists(v)}
    mt = man.get("mtimes", {})
    wrote = skipped = 0
    for full, rel in walk(src):
        if rel.startswith("tool/") or rel in ("pack-manifest.json", "claude.json") or rel.endswith(".command"):
            continue
        if re.search(r"\.gz\.part\d{3}$", rel) and not rel.endswith(".part000"):
            continue   # read together with part000
        packed = None
        if rel.endswith(".gz") or rel.endswith(".gz.part000"):
            import gzip
            stem = rel[:-3] if rel.endswith(".gz") else rel[:-11]
            if rel.endswith(".gz"):
                with open(full, "rb") as f:
                    packed = gzip.decompress(f.read())
            else:
                buf, i = b"", 0
                while os.path.exists(os.path.join(src, stem + ".gz.part%03d" % i)):
                    with open(os.path.join(src, stem + ".gz.part%03d" % i), "rb") as f:
                        buf += f.read()
                    i += 1
                packed = gzip.decompress(buf)
            rel = stem
        frel = fix(rel)
        if frel.startswith("claude-home/"):
            r = frel[len("claude-home/"):]
            if any(r == l or r.startswith(l + "/") for l in linked):
                continue
            dest = os.path.join(CLAUDE_DIR, r)
        elif frel.startswith("desktop/"):
            dest = os.path.join(DESKTOP_DIR, frel[len("desktop/"):])
        else:
            continue
        name = os.path.basename(dest)
        if os.path.exists(dest) and name not in ("settings.json", "archived-sessions.idx",
                                                 "claude_desktop_config.json"):
            skipped += 1
            continue
        if packed is not None:
            raw = packed
        else:
            with open(full, "rb") as f:
                raw = f.read()
        if not rel.startswith("claude-home/" + SELF_SKILL):
            try:
                raw = fix(raw.decode("utf-8")).encode("utf-8")
            except UnicodeDecodeError:
                pass
        if os.path.exists(dest):  # merge: what the new login already set wins
            cur, new = load_json(dest, None), None
            try:
                new = json.loads(raw.decode("utf-8"))
            except ValueError:
                pass
            if name == "archived-sessions.idx" and isinstance(cur, dict) and isinstance(new, dict):
                new["archived"] = sorted(set(new.get("archived") or []) | set(cur.get("archived") or []))
            elif isinstance(cur, dict) and isinstance(new, dict):
                new.update(cur)
            if new is not None:
                raw = (json.dumps(new, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw)
        os.chmod(dest, 0o755 if rel.endswith((".sh", ".py")) or "/bin/" in rel else 0o600)
        want = mt.get(rel)
        if want:
            os.utime(dest, (want, want))
        wrote += 1
    for l in sorted(linked):
        dest = os.path.join(CLAUDE_DIR, l)
        if not os.path.lexists(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.symlink(links[l], dest)
    # ~/.claude.json: add project settings and MCP servers; keep everything the new login wrote
    bj = load_json(os.path.join(src, "claude.json"), {}) or {}
    bj = json.loads(fix(json.dumps(bj, ensure_ascii=False)))
    cur = load_json(CLAUDE_JSON, {}) or {}
    for k, v in bj.items():
        if isinstance(v, dict) and isinstance(cur.get(k), dict):
            merged = dict(v)
            merged.update(cur[k])
            cur[k] = merged
        elif k not in cur:
            cur[k] = v
    save_json(CLAUDE_JSON, cur)
    os.chmod(CLAUDE_JSON, 0o600)
    protect_history()
    reg = load_json(os.path.join(src, "folder-ids.json"), {}) or {}
    if reg:
        reg = {k: (HOME + v[len(old_home):]) if isinstance(v, str) and (v == old_home or v.startswith(old_home + "/"))
               else v for k, v in reg.items()}
        cur = load_json(FOLDER_REG, {}) or {}
        cur.update(reg)
        save_json(FOLDER_REG, cur)
        if os.path.exists(os.path.join(STATE_DIR, "folder-search.json")):
            os.remove(os.path.join(STATE_DIR, "folder-search.json"))
        relink_folders(cur)
    log("✓ restored %d files (%d already there, kept). Code tab conversations now: %d" % (
        wrote, skipped, len([f for f in os.listdir(os.path.join(DESKTOP_DIR, "claude-code-sessions", acct, org))
                             if f.startswith("local_")])))
    log("  signed-in account: %s  (old account info was never copied)" % acct)
    if os.path.exists(PENDING):
        os.remove(PENDING)


PENDING = os.path.join(STATE_DIR, "switch-pending")
STATUS_FILE = os.path.join(STATE_DIR, "status.json")


def write_status(ok, changed=0, note=""):
    """Small JSON any dashboard can read: ~/.claude-backup/status.json"""
    st = load_json(STATUS_FILE, {}) or {}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.update({"last_run": now, "ok": ok, "note": note, "changed_files": changed,
               "repo": remote_url() if os.path.isdir(os.path.join(REPO_DIR, ".git")) else "",
               "conversations_local": count_sessions(CLAUDE_DIR),
               "conversations_backup": count_sessions(os.path.join(REPO_DIR, "claude-home")),
               "every_minutes": 10,
               "too_big": [{"name": b["name"], "path": b["path"], "mb": b["mb"]} for b in BIG_PENDING]})
    if ok:
        st["last_success"] = now
    st["unpushed_commits"] = None
    for ref in ("@{u}..HEAD", "origin/main..HEAD"):
        r = git("rev-list", "--count", ref, check=False)
        if r.returncode == 0 and (r.stdout or "").strip().isdigit():
            st["unpushed_commits"] = int(r.stdout.strip())
            break
    save_json(STATUS_FILE, st)


def use_system_proxy():
    """Scheduled jobs don't inherit the terminal's proxy variables; read macOS's own setting."""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or sys.platform != "darwin":
        return
    out = run(["scutil", "--proxy"], check=False).stdout or ""
    kv = dict(re.findall(r"(\w+)\s*:\s*(\S+)", out))
    for kind, scheme in (("HTTPS", "http"), ("HTTP", "http"), ("SOCKS", "socks5h")):
        if kv.get(kind + "Enable") == "1" and kv.get(kind + "Proxy") and kv.get(kind + "Port"):
            url = "%s://%s:%s" % (scheme, kv[kind + "Proxy"], kv[kind + "Port"])
            os.environ["HTTPS_PROXY"] = os.environ["HTTP_PROXY"] = url
            os.environ["ALL_PROXY"] = url
            return


def cmd_big(a):
    """List files too big for GitHub, or record what to do with one (name = what `big list` shows)."""
    ch = big_choices()
    st = load_json(STATUS_FILE, {}) or {}
    waiting = st.get("too_big") or []
    if a.action == "list":
        print(json.dumps({"waiting": waiting, "decided": ch}, ensure_ascii=False, indent=2))
        return
    if not a.name:
        raise SystemExit("give the name `big list` shows")
    name = a.name
    if "/" not in name and not name.endswith(".jsonl"):
        name += ".jsonl"
    paths = [b.get("path") for b in waiting if b["name"] == name and b.get("path")]
    if not paths:
        paths = glob.glob(os.path.join(CLAUDE_DIR, "projects", "*", name)) if name.endswith(".jsonl") and "/" not in name \
            else ([name] if os.path.exists(name) else [])
    if a.action == "delete":
        if not paths:
            raise SystemExit("not found: %s" % name)
        trash = os.path.expanduser("~/.Trash")
        for h in paths:
            dst = os.path.join(trash, os.path.basename(h))
            if os.path.exists(dst):
                dst = os.path.join(trash, "%s-%s" % (time.strftime("%H%M%S"), os.path.basename(h)))
            shutil.move(h, dst)
            side = h[:-len(".jsonl")] if h.endswith(".jsonl") else None  # a conversation's own folder
            if side and os.path.isdir(side):
                shutil.move(side, dst[:-len(".jsonl")])
        ch.pop(name, None)
        log("moved to Trash: %s" % name)
    else:
        ch[name] = {"choice": a.action, "at": time.strftime("%Y-%m-%d %H:%M")}
    save_json(BIG_FILE, ch)
    st["too_big"] = [b for b in waiting if b["name"] != name]
    save_json(STATUS_FILE, st)
    print("ok: %s → %s" % (name, a.action))


KEEP_LOCAL = 150   # versions kept on this Mac; GitHub keeps all of them


def tidy_repo(force=False):
    """Once a day: drop leftovers of an interrupted compress, keep only recent versions on this Mac
    (everything is already on GitHub) and compress the rest. Saves gigabytes over time."""
    stamp = os.path.join(STATE_DIR, "last-tidy")
    today = time.strftime("%Y-%m-%d")
    if not force and os.path.exists(stamp) and open(stamp).read().strip() == today:
        return
    for g in glob.glob(os.path.join(REPO_DIR, ".git", "objects", "pack", "tmp_*")):
        os.remove(g)
    ahead = (git("rev-list", "--count", "@{u}..HEAD", check=False).stdout or "").strip()
    total = (git("rev-list", "--count", "HEAD", check=False).stdout or "").strip()
    if ahead == "0" and total.isdigit() and int(total) > KEEP_LOCAL * 2:
        cut = git("rev-parse", "HEAD~%d" % KEEP_LOCAL).stdout.strip()
        with open(os.path.join(REPO_DIR, ".git", "shallow"), "w") as f:
            f.write(cut + "\n")
        git("reflog", "expire", "--expire=now", "--all", check=False)
    git("gc", "-q", "--prune=now", check=False)
    for g in ("commit-graph", "commit-graphs"):
        p = os.path.join(REPO_DIR, ".git", "objects", "info", g)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    git("commit-graph", "write", "--reachable", check=False)
    with open(stamp, "w") as f:
        f.write(today)
    log("✓ daily tidy done (local copy keeps the last %d versions; GitHub keeps all)" % KEEP_LOCAL)


def cmd_sync(a):
    need_repo()
    import fcntl
    lock = open(os.path.join(STATE_DIR, "sync.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("· another backup is still running – skipping this round")
        return
    use_system_proxy()
    if os.path.exists(PENDING):
        log("· account switch in progress – skipping backup until the restore button has finished")
        return
    try:
        moved_notes = relink_folders()
        reg = tag_folders()
    except Exception as e:  # never let folder bookkeeping stop the backup
        moved_notes, reg = ["folder check failed: %s" % e], load_json(FOLDER_REG, {}) or {}
    here, there = count_sessions(CLAUDE_DIR), count_sessions(os.path.join(REPO_DIR, "claude-home"))
    if there >= 10 and here < there * 0.5 and not getattr(a, "force", False):
        raise SystemExit("REFUSING: this Mac has %d conversations but the backup has %d. Looks like a fresh "
                         "account – not overwriting the backup. (Run the restore button, or sync --force.)"
                         % (here, there))
    remote = remote_url()
    if is_private(remote) is False:
        raise SystemExit("REFUSING to push: %s is PUBLIC. Make it private first." % remote)
    try:
        if os.path.getsize(LOG_FILE) > 1 << 20:
            with open(LOG_FILE, "rb") as f:
                f.seek(-(256 << 10), 2)
                tail = f.read()
            with open(LOG_FILE, "wb") as f:
                f.write(tail)
    except OSError:
        pass
    log(time.strftime("== %Y-%m-%d %H:%M:%S sync"))
    a.out, a.overwrite = REPO_DIR, True
    cmd_pack(a)
    save_json(os.path.join(REPO_DIR, "folder-ids.json"), reg)
    ensure_identity()
    with open(os.path.join(REPO_DIR, ".gitattributes"), "w") as f:
        f.write("* -text\n")
    git("add", "-A")
    changed = [l for l in (git("status", "--porcelain").stdout or "").splitlines() if l.strip()]
    if changed:
        git("commit", "-q", "-m", "backup %s · %d files changed · %d conversations" % (
            time.strftime("%Y-%m-%d %H:%M"), len(changed), count_sessions(os.path.join(REPO_DIR, "claude-home"))))

    pushed = getattr(a, "no_push", False)
    if not pushed:
        for wait in (0, 5, 15, 30):
            time.sleep(wait)
            if git("push", "-q", "-u", "origin", "HEAD", check=False).returncode == 0:
                pushed = True
                break
    if pushed and not getattr(a, "no_push", False):
        try:
            tidy_repo()
        except Exception as e:   # tidying must never break the backup
            log("· daily tidy skipped: %s" % e)
    write_status(ok=bool(pushed), changed=len(changed),
                 note=("; ".join(moved_notes) + (" – reopen Claude to see it" if moved_notes else "")) if pushed
                 else "upload failed, will retry")
    log("✓ %d files changed, %s" % (len(changed), "uploaded to GitHub" if pushed and not getattr(a, "no_push", False)
                                    else ("not uploaded (--no-push)" if pushed else "UPLOAD FAILED – will retry next time")))
    if not pushed:
        sys.exit(2)


# ---------------------------------------------------------------- schedule / status

def cmd_schedule(a):
    hh, mm = [int(x) for x in a.time.split(":")]
    # run from a fixed copy, so the schedule keeps working when the skill/plugin moves or updates
    bindir = os.path.join(STATE_DIR, "bin")
    os.makedirs(bindir, exist_ok=True)
    script = os.path.join(bindir, "claude_backup.py")
    if os.path.abspath(__file__) != script:
        shutil.copy2(os.path.abspath(__file__), script)
    path = ":".join(["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    if sys.platform != "darwin":
        log("Not macOS. Add this line with `crontab -e`:\n%d %d * * * %s %s backup >> %s 2>&1" % (
            mm, hh, sys.executable, script, LOG_FILE))
        return
    plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key><array>
    <string>%s</string><string>-I</string><string>%s</string><string>sync</string>
  </array>
  %s
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>%s</string></dict>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict></plist>
""" % (LABEL, "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable, script,
       ("<key>StartInterval</key><integer>%d</integer><key>RunAtLoad</key><true/>" % (a.every * 60)) if a.every else
       ("<key>StartCalendarInterval</key><dict><key>Hour</key><integer>%d</integer>"
        "<key>Minute</key><integer>%d</integer></dict>" % (hh, mm)),
       path, LOG_FILE, LOG_FILE)  # system python survives Homebrew upgrades
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PLIST, "w") as f:
        f.write(plist)
    dom = "gui/%d" % os.getuid()
    run(["launchctl", "bootout", dom, PLIST], check=False)
    p = run(["launchctl", "bootstrap", dom, PLIST], check=False)
    if p.returncode != 0:
        raise SystemExit("launchctl failed: " + (p.stdout or ""))
    log(("✓ backup scheduled every %d minutes (only changed conversations are processed)" % a.every if a.every else
         "✓ daily backup scheduled at %02d:%02d (if the Mac is asleep it runs on wake)" % (hh, mm)) + "\n  log: " + LOG_FILE)


def cmd_unschedule(a):
    if os.path.exists(PLIST):
        run(["launchctl", "bootout", "gui/%d" % os.getuid(), PLIST], check=False)
        os.remove(PLIST)
    log("✓ schedule removed")


def cmd_status(a):
    ok = os.path.isdir(os.path.join(REPO_DIR, ".git"))
    log("set up: %s" % ("yes" if ok else "NO – run init"))
    if ok:
        r = remote_url()
        priv = is_private(r)
        log("repo: %s (%s)" % (r, {True: "private", False: "PUBLIC!", None: "privacy not checked"}[priv]))
        log("last commit: " + (git("log", "-1", "--format=%cd  %s", "--date=format:%Y-%m-%d %H:%M",
                                   check=False).stdout or "none").strip())
        ahead = (git("rev-list", "--count", "@{u}..HEAD", check=False).stdout or "").strip()
        if ahead.isdigit() and int(ahead):
            log("! %s commit(s) not pushed yet" % ahead)
        log("conversations: %d local, %d in backup" % (
            count_sessions(CLAUDE_DIR), count_sessions(os.path.join(REPO_DIR, "claude-home"))))
    log("schedule: %s" % ("installed" if os.path.exists(PLIST) else "not installed"))
    s = load_json(os.path.join(CLAUDE_DIR, "settings.json"), {}) or {}
    log("cleanupPeriodDays: %s" % s.get("cleanupPeriodDays", "unset (default 30 → old conversations get deleted!)"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init"); p.add_argument("--repo"); p.add_argument("--remote"); p.set_defaults(f=cmd_init)
    p = sub.add_parser("backup-raw"); p.add_argument("--full", action="store_true")
    p.add_argument("--no-push", action="store_true"); p.set_defaults(f=cmd_backup)
    for name in ("sync", "backup"):  # "backup" = clean sync; raw backups would carry the old account
        p = sub.add_parser(name); p.add_argument("--no-push", action="store_true")
        p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_sync)
    p = sub.add_parser("restore"); p.add_argument("--remote"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true"); p.add_argument("--desktop", action="store_true")
    p.add_argument("--desktop-account", help="<accountUuid>/<orgUuid> to put Code tab conversations under")
    p.set_defaults(f=cmd_restore)
    p = sub.add_parser("schedule"); p.add_argument("--time", default="23:00")
    p.add_argument("--every", type=int, default=10, help="minutes between runs; 0 = once a day at --time"); p.set_defaults(f=cmd_schedule)
    p = sub.add_parser("unschedule"); p.set_defaults(f=cmd_unschedule)
    p = sub.add_parser("status"); p.set_defaults(f=cmd_status)
    p = sub.add_parser("big"); p.add_argument("action", choices=["list", "compress", "skip", "delete"])
    p.add_argument("name", nargs="?"); p.set_defaults(f=cmd_big)
    p = sub.add_parser("pack"); p.add_argument("--out", required=True)
    p.add_argument("--overwrite", action="store_true"); p.set_defaults(f=cmd_pack)
    p = sub.add_parser("verify"); p.add_argument("dir"); p.set_defaults(f=cmd_verify)
    p = sub.add_parser("move-old"); p.set_defaults(f=cmd_move_old)
    p = sub.add_parser("wait-login"); p.set_defaults(f=cmd_wait_login)
    p = sub.add_parser("relink"); p.set_defaults(f=cmd_relink)
    p = sub.add_parser("setup"); p.add_argument("--repo", default="claude-backup")
    p.add_argument("--desktop-account"); p.set_defaults(f=cmd_setup)
    p = sub.add_parser("adopt"); p.add_argument("--repo", default="claude-backup")
    p.add_argument("--desktop-account"); p.set_defaults(f=cmd_adopt)
    p = sub.add_parser("has-old"); p.set_defaults(f=cmd_has_old)
    p = sub.add_parser("unpack"); p.add_argument("src"); p.add_argument("--desktop-account")
    p.add_argument("--allow-running", action="store_true"); p.set_defaults(f=cmd_unpack)
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return
    if a.f is cmd_sync:
        try:
            a.f(a)
        except SystemExit as e:
            if e.code not in (None, 0):
                write_status(ok=False, note=str(e.code)[:300])
            raise
        return
    a.f(a)


if __name__ == "__main__":
    main()
