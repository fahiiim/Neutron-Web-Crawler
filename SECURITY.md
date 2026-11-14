# Security Policy & Repository Integrity

Neutron adheres to a strict zero-tolerance security model designed to safeguard contributors, deployed cloud services, and end users against supply-chain attacks, credential leaks, and malicious script injections.

---

## 1. Automated Security Guardrails

All code submitted to this repository is validated by automated multi-layered defenses:

| Defense Layer | Mechanism | Protection Scope |
|---|---|---|
| **Local Pre-Commit Hook** | `.githooks/pre-commit` | Scans staged diffs before git commits can complete locally. |
| **Local Pre-Push Hook** | `.githooks/pre-push` | Validates entire repository before pushing to any remote. |
| **CI Security Scanner** | `scripts/security_guardrail.py` | Runs first in GitHub Actions before any dependency installation or build step. |
| **Dependency Auditing** | `npm audit` / `package-lock.json` | Ensures immutable dependency trees and zero known high/critical vulnerabilities. |
| **Workspace Sandboxing** | `.gitignore` + Path Policies | Prohibits `.vscode/tasks.json` auto-execution, arbitrary batch/shell binaries, and backdoor scripts. |

---

## 2. Trojan & Supply-Chain Attack Mitigations

Recent developer-targeted campaigns (such as the InvisibleFerret / BeaverTail Trojans) exploit IDE workspace automation and package lifecycle scripts. Neutron implements active defenses against these vectors:

1. **Blocked Automated Tasks (`.vscode/tasks.json`)**:
   - Automatic execution on folder open (`"runOn": "folderOpen"`, `"allowAutomaticTasks": true`) is prohibited and blocked by CI.
   - All `.cmd`, `.bat`, `.vbs`, and unreviewed executable scripts are forbidden from version control.

2. **Immutable Package Manifests (`frontend/package.json`)**:
   - Build and development scripts are locked to `vite` and `tsc -b && vite build`.
   - Pre-install, post-install, or custom Node bootstrap hooks (e.g. `node init`) are strictly disallowed.

3. **Decentralized C2 & Obfuscation Detection**:
   - The security guardrail scanner screens all codebase files for Ethereum smart contract C2 query patterns (`eth_getBlockByNumber`, `eth_getTransactionCount`), base64 execution headers (`X-Payload-B64`), and dynamic `eval()` injections.

4. **Secret Scanning**:
   - Automatic detection blocks accidental commits containing API keys, private certificates, or database credentials.

---

## 3. Contributor Setup: Enabling Git Security Hooks

To enable the local pre-commit and pre-push hooks on your local clone, run:

```bash
git config core.hooksPath .githooks
```

Once configured, Git will automatically verify your staged files using `scripts/security_guardrail.py` before allowing any commit or push.

---

## 4. Reporting a Vulnerability

If you discover a security issue or vulnerability in Neutron:
- Please **do not** open a public issue.
- Report your findings directly to the repository maintainer via email or GitHub Private Vulnerability Reporting.
- Maintainers will investigate, patch, and release a fix promptly.

