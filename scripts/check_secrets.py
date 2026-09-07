"""Offline heuristic scan of tracked/new files and ZIP members; never print values.

This is a defense in depth check, not proof that arbitrary secrets cannot exist.
"""
import io
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "github-token": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "provider-key": rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,})",
    "credential-url": rb"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@",
    "literal-secret": rb"(?i)(?:password|api_key|access_token|client_secret)\s*[=:]\s*[\"'][A-Za-z0-9_+/=-]{20,}[\"']",
}


def scan(name, data):
    findings = []
    if name.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    findings.extend(scan(name + '!' + item.filename, archive.read(item)))
        return findings
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, data):
            findings.append(f'{name}:{data[:match.start()].count(bytes([10])) + 1}: {kind}')
    return findings


def main():
    paths = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
    ).decode().split('\0')
    findings = []
    count = 0
    for name in sorted(set(filter(None, paths))):
        path = ROOT / name
        if path.is_file():
            count += 1
            findings.extend(scan(name, path.read_bytes()))
    if '--history' in sys.argv:
        seen = set()
        for commit in subprocess.check_output(['git', 'rev-list', '--all'], cwd=ROOT).decode().split():
            for entry in subprocess.check_output(['git', 'ls-tree', '-r', commit], cwd=ROOT).decode().splitlines():
                meta, name = entry.split('\t', 1)
                sha = meta.split()[2]
                if sha not in seen:
                    seen.add(sha)
                    findings.extend(scan(f'{commit[:8]}:{name}', subprocess.check_output(['git', 'cat-file', 'blob', sha], cwd=ROOT)))
        print(f'Historical blobs scanned: {len(seen)}')
    print(f'Files scanned: {count}; findings: {len(findings)}')
    for finding in findings:
        print(finding)
    return bool(findings)


if __name__ == '__main__':
    sys.exit(main())
