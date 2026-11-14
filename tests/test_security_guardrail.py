import unittest
from scripts.security_guardrail import (
    check_forbidden_files,
    check_package_json,
    MALICIOUS_SIGNATURES,
    SECRET_PATTERNS,
)


class TestSecurityGuardrail(unittest.TestCase):
    def test_catches_forbidden_file_names(self):
        bad_files = [
            "frontend/init",
            "frontend/init.js",
            ".vscode/tasks.json",
            ".vscode/eslint-check.cmd",
            "scripts/malicious.bat",
            "temp_auto_push.bat",
            "config.bat",
            "root_malware.exe",
        ]
        violations = check_forbidden_files(bad_files)
        self.assertEqual(len(violations), len(bad_files))

    def test_allows_valid_repository_files(self):
        good_files = [
            "frontend/package.json",
            "frontend/src/App.tsx",
            "services/gateway/app.py",
            "scripts/security_guardrail.py",
            "docs/Neutron_Architecture_Whitepaper.pdf",
        ]
        violations = check_forbidden_files(good_files)
        self.assertEqual(len(violations), 0)

    def test_catches_malicious_c2_signatures(self):
        sample_malicious_code = """
        const x = "eth_getBlockByNumber";
        const h = headers["X-Payload-B64"];
        eval(proxyInfo);
        """
        matches = []
        for pat, desc in MALICIOUS_SIGNATURES:
            if pat.search(sample_malicious_code):
                matches.append(desc)

        self.assertIn("Ethereum RPC C2 resolver pattern", matches)
        self.assertIn("InvisibleFerret payload header", matches)
        self.assertIn("Dynamic remote eval execution", matches)

    def test_catches_secret_leaks(self):
        sample_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
        matched = any(pat.search(sample_key) for pat, _ in SECRET_PATTERNS)
        self.assertTrue(matched)

    def test_current_package_json_is_valid(self):
        violations = check_package_json()
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

