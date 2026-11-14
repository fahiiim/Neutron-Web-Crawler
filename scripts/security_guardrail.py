#!/usr/bin/env python3
"""
Neutron Security Guardrail & Integrity Scanner
=============================================
Zero-dependency static security validator designed to prevent supply-chain attacks,
malicious script injection (e.g. InvisibleFerret / BeaverTail Trojans), unauthorized
VS Code automated tasks, package manifest tampering, and credential leaks.

Can be run locally (as a pre-commit or pre-push hook) and in CI/CD pipelines.
Exits with code 0 on clean pass; code 1 on any detected security violation.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 1. Prohibited file patterns anywhere in repository
FORBIDDEN_FILE_PATTERNS = [
    re.compile(r"^frontend/init(\.js|\.mjs|\.cjs)?$", re.IGNORECASE),
    re.compile(r"^\.vscode/tasks\.json$", re.IGNORECASE),
    re.compile(r"^\.vscode/eslint(-check)?(\.cmd|\.sh)?$", re.IGNORECASE),
    re.compile(r".*\.bat$", re.IGNORECASE),
    re.compile(r".*\.cmd$", re.IGNORECASE),
    re.compile(r".*\.vbs$", re.IGNORECASE),
    re.compile(r".*\.exe$", re.IGNORECASE),
    re.compile(r".*\.dll$", re.IGNORECASE),
    re.compile(r".*\.so$", re.IGNORECASE),
    re.compile(r".*\.dylib$", re.IGNORECASE),
    re.compile(r".*temp_.*push\.bat$", re.IGNORECASE),
    re.compile(r"^config\.bat$", re.IGNORECASE),
]

# Exceptions to file patterns (e.g. virtual environment files if scanned, or docs)
WHITELISTED_FILES = {
    # No batch/cmd files are allowed in production tracked repository
}

# 2. Known Trojan / Infostealer signatures (InvisibleFerret / BeaverTail / Arbitrary Remote Exec)
MALICIOUS_SIGNATURES = [
    (re.compile(r"eth_getBlockByNumber", re.IGNORECASE), "Ethereum RPC C2 resolver pattern"),
    (re.compile(r"eth_getTransactionCount", re.IGNORECASE), "Ethereum RPC C2 resolver pattern"),
    (re.compile(r"X-Payload-B64", re.IGNORECASE), "InvisibleFerret payload header"),
    (re.compile(r"/0x/(cls|ls)", re.IGNORECASE), "Known C2 endpoint path"),
    (re.compile(r"atob\s*\(\s*process\.env\.[A-Za-z0-9_]+\s*\)", re.IGNORECASE), "Obfuscated env decoding"),
    (re.compile(r"eval\s*\(\s*(proxyInfo|[a-zA-Z0-9_]+\s*\+\s*[a-zA-Z0-9_]+)\s*\)"), "Dynamic remote eval execution"),
    (re.compile(r"global\s*\[\s*['\"]_V['\"]\s*\]"), "Trojan global state injection"),
    (re.compile(r"global\.i\s*=\s*['\"][A-Za-z0-9_\-\*]+['\"]"), "Trojan campaign marker"),
    (re.compile(r"task\.allowAutomaticTasks"), "VS Code silent task auto-execution setting"),
    (re.compile(r"\"runOn\"\s*:\s*\"folderOpen\""), "VS Code folderOpen auto-execution task"),
]

# 3. Secret leak patterns
SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN\s+(RSA|OPENSSH|DSA|EC)\s+PRIVATE\s+KEY-----"), "Private cryptographic key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b"), "Fine-grained GitHub token"),
    (re.compile(r"\bAIzaSy[A-Za-z0-9_-]{33}\b"), "Google API key"),
    (re.compile(r"\b[A-Za-z0-9_\-]{20,}:[A-Za-z0-9_\-]{40,}\b"), "Generic auth credential token"),
]

# Scanned extensions
SCANNABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".sh", ".html", ".css", ".md", ".toml", ".sql", ".proto", ".txt"
}


def get_files_to_check(staged_only: bool = False) -> list[str]:
    """Return files to check (either staged files or all tracked files)."""
    if staged_only:
        try:
            res = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=True,
            )
            files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            return files
        except Exception as e:
            print(f"[WARN] Failed to get staged files ({e}); checking all files instead.")

    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception as e:
        print(f"[WARN] Failed to run git ls-files ({e}); falling back to filesystem walk.")
        tracked = []
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "env", "node_modules", "__pycache__"}]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), REPO_ROOT).replace("\\", "/")
                tracked.append(rel)
        return tracked


def check_forbidden_files(files: list[str]) -> list[str]:
    """Ensure no prohibited or executable trojan vector files are tracked."""
    violations = []
    for f in files:
        f_norm = f.replace("\\", "/")
        if f_norm in WHITELISTED_FILES:
            continue
        for pat in FORBIDDEN_FILE_PATTERNS:
            if pat.search(f_norm):
                violations.append(f"Prohibited file tracked: {f_norm} (matches pattern {pat.pattern})")
                break
    return violations


def check_package_json() -> list[str]:
    """Validate frontend/package.json to guarantee no pre/post-install or trojan scripts."""
    violations = []
    pkg_path = REPO_ROOT / "frontend" / "package.json"
    if not pkg_path.exists():
        return violations

    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})

        # Allowed script commands
        expected_scripts = {
            "dev": "vite",
            "build": "tsc -b && vite build",
            "preview": "vite preview",
        }

        for name, cmd in scripts.items():
            if name in expected_scripts:
                expected = expected_scripts[name]
                if cmd.strip() != expected:
                    violations.append(
                        f"Tampered script in frontend/package.json: '{name}' is '{cmd}', expected '{expected}'"
                    )
            elif name in {"preinstall", "postinstall", "prebuild", "postbuild"}:
                violations.append(
                    f"Forbidden lifecycle script in frontend/package.json: '{name}'='{cmd}'"
                )
            elif "node " in cmd and "init" in cmd:
                violations.append(
                    f"Suspicious node invocation in frontend/package.json: '{name}'='{cmd}'"
                )
    except Exception as e:
        violations.append(f"Failed to parse frontend/package.json: {e}")

    return violations


def check_file_contents(files: list[str]) -> list[str]:
    """Scan tracked source files for known malware signatures and leaked secrets."""
    violations = []
    for rel_path in files:
        rel_norm = rel_path.replace("\\", "/")
        path = REPO_ROOT / rel_norm
        if not path.is_file():
            continue

        ext = path.suffix.lower()
        if ext not in SCANNABLE_EXTENSIONS:
            continue

        # Skip test files from secret pattern checks if they use dummy placeholders
        is_test_file = "tests/" in rel_norm

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Disregard scanner itself, its unit tests, and security documentation referencing signatures
        if (
            rel_norm.endswith("security_guardrail.py")
            or rel_norm.endswith("test_security_guardrail.py")
            or rel_norm.endswith("SECURITY.md")
        ):
            continue

        # Check malware signatures
        for pat, desc in MALICIOUS_SIGNATURES:
            match = pat.search(content)
            if match:
                violations.append(
                    f"Malicious signature detected in {rel_norm}: {desc} (match: '{match.group(0)[:60]}')"
                )

        # Check secret leaks
        if not is_test_file and not rel_norm.endswith(".example") and not rel_norm.endswith("security_guardrail.py"):
            for pat, desc in SECRET_PATTERNS:
                match = pat.search(content)
                if match:
                    violations.append(
                        f"Potential secret leak in {rel_norm}: {desc} (match: '{match.group(0)[:30]}...')"
                    )

    return violations


def check_git_attributes_and_ignore() -> list[str]:
    """Ensure sensitive files are strictly gitignored."""
    violations = []
    gitignore_path = REPO_ROOT / ".gitignore"
    if not gitignore_path.exists():
        violations.append("Missing .gitignore file in repository root.")
        return violations

    content = gitignore_path.read_text(encoding="utf-8")
    mandatory_ignores = [
        "*.env",
        ".venv/",
        "frontend/node_modules/",
    ]
    for rule in mandatory_ignores:
        if rule not in content:
            violations.append(f"Missing mandatory ignore rule in .gitignore: '{rule}'")

    return violations


def main() -> int:
    staged_mode = "--staged" in sys.argv
    mode_str = "Staged Git Changes" if staged_mode else "Full Repository"
    print("=" * 70)
    print(f"Neutron Security Guardrail & Integrity Scanner ({mode_str})")
    print("=" * 70)

    files = get_files_to_check(staged_only=staged_mode)
    if staged_mode and not files:
        print("[INFO] No staged files to check.")
        return 0

    print(f"[*] Scanning {len(files)} target files...")

    all_violations: list[str] = []

    # 1. Check prohibited filenames
    forbidden_errs = check_forbidden_files(files)
    if forbidden_errs:
        all_violations.extend(forbidden_errs)

    # 2. Check package.json scripts
    pkg_errs = check_package_json()
    if pkg_errs:
        all_violations.extend(pkg_errs)

    # 3. Check file contents (IOCs + secrets)
    content_errs = check_file_contents(files)
    if content_errs:
        all_violations.extend(content_errs)

    # 4. Check .gitignore
    ignore_errs = check_git_attributes_and_ignore()
    if ignore_errs:
        all_violations.extend(ignore_errs)

    if all_violations:
        print("\n[FAILED] SECURITY VIOLATIONS DETECTED:")
        for v in all_violations:
            print(f"  [!] {v}")
        print("\nAborting push/commit to preserve repository security.")
        return 1

    print("[SUCCESS] All security guardrails passed cleanly. No malicious patterns detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
