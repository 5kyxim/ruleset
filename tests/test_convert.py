import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.convert import convert


class ConvertTests(unittest.TestCase):
    def test_direct_filters_broad_suffixes_only(self):
        payload = "payload: ['+.CN', '+.xn--fiqs8s', '+.futuretld', '+.in.th', '+.zone.id', 'exact.cn', '+.specific.cn', 'zone.id', '+.tenant.zone.id', '+.aliyuncs.com']"
        result, count = convert("direct", payload)
        self.assertEqual(count, 10)
        self.assertEqual(result["rules"], [
            {"domain": ["exact.cn", "zone.id"]},
            {"domain_suffix": ["aliyuncs.com", "specific.cn", "tenant.zone.id"]},
        ])
        proxy, _ = convert("proxy", payload)
        suffixes = next(r["domain_suffix"] for r in proxy["rules"] if "domain_suffix" in r)
        self.assertIn("cn", suffixes)
        self.assertIn("zone.id", suffixes)

    def test_direct_all_filtered_has_no_catch_all_rule(self):
        result, _ = convert("direct", "payload: ['+.cn', '+.in.th']")
        self.assertEqual(result["rules"], [])

    def test_exact_and_suffix_stay_distinct(self):
        result, count = convert("direct", "payload: ['Example.COM', '+.example.com', 'example.com']")
        self.assertEqual(count, 3)
        self.assertEqual(result["rules"], [
            {"domain": ["example.com"]}, {"domain_suffix": ["example.com"]}
        ])

    def test_ipv4_and_ipv6(self):
        result, _ = convert("lancidr", "payload: ['192.168.0.0/16', 'fc00::/7']")
        self.assertEqual(result["rules"], [{"ip_cidr": ["192.168.0.0/16", "fc00::/7"]}])

    def test_process_case_spaces_and_percent_preserved(self):
        result, _ = convert("applications", "payload: ['PROCESS-NAME,Surge 2', 'PROCESS-NAME,Surge%202']")
        self.assertEqual(result["rules"], [{"process_name": ["Surge 2", "Surge%202"]}])

    def test_rejects_unknown_or_malformed_input(self):
        cases = [
            ("direct", "payload: ['*.example.com']"),
            ("direct", "payload: ['.example.com']"),
            ("direct", "payload: [123]"),
            ("direct", "payload: []"),
            ("direct", "payload: ['example.com']\nextra: true"),
            ("lancidr", "payload: ['192.168.0.1/16']"),
            ("lancidr", "payload: ['192.168.0.1']"),
            ("applications", "payload: ['DOMAIN,example.com']"),
            ("applications", "payload: ['PROCESS-NAME,']"),
        ]
        for name, text in cases:
            with self.subTest(name=name, text=text), self.assertRaises(ValueError):
                convert(name, text)


@unittest.skipUnless(shutil.which("sing-box"), "sing-box 1.14.1 is required for binary matching tests")
class BinaryMatchTests(unittest.TestCase):
    def test_filtered_direct_preserves_specific_matches(self):
        self.assert_matches("direct", "payload: ['+.cn', '+.zone.id', 'exact.cn', '+.specific.cn', '+.tenant.zone.id', '+.aliyuncs.com']", [
            ("us.ip111.cn", False), ("arbitrary.zone.id", False),
            ("exact.cn", True), ("sub.exact.cn", False),
            ("sub.specific.cn", True), ("sub.tenant.zone.id", True),
            ("overseas.aliyuncs.com", True),
        ])

    def assert_matches(self, name, payload, cases):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rules.json"
            binary = Path(directory) / "rules.srs"
            result, _ = convert(name, payload)
            source.write_text(json.dumps(result))
            subprocess.run(["sing-box", "rule-set", "compile", "--output", str(binary), str(source)], check=True)
            for candidate, expected in cases:
                with self.subTest(candidate=candidate):
                    output = subprocess.check_output([
                        "sing-box", "rule-set", "match", "--format", "binary", str(binary), candidate
                    ], text=True, stderr=subprocess.STDOUT)
                    self.assertEqual("match rules." in output, expected, output)

    def test_domain_boundaries_after_compilation(self):
        self.assert_matches("direct", "payload: ['exact.example', '+.suffix.example']", [
            ("exact.example", True), ("sub.exact.example", False),
            ("suffix.example", True), ("sub.suffix.example", True),
            ("deep.sub.suffix.example", True), ("notsuffix.example", False),
            ("suffix.example.evil", False),
        ])

    def test_cidr_boundaries_after_compilation(self):
        self.assert_matches("lancidr", "payload: ['192.168.0.0/16', 'fc00::/7']", [
            ("192.168.0.0", True), ("192.168.255.255", True),
            ("192.169.0.0", False), ("fdff::1", True), ("fe00::1", False),
        ])


if __name__ == "__main__":
    unittest.main()
