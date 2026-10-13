"""Deterministic file/line (±3) plus bug-class keyword matching; no model judge."""
import re

FINDING = re.compile(r'(?:src/)?([\w-]+\.py)[` ]*:\s*(\d+)(?:[-–]\d+)?[` ]*\s*(?:—|–|-|:)\s*([^\n]+)')


def grade(text, oracle, failed=False):
    found, false, duplicates, parsed = set(), [], 0, []
    seen = set()
    for match in FINDING.finditer(text):
        file, line, description = match.groups()
        item = {'file': file, 'line': int(line), 'description': description.strip()}
        fingerprint = (file, int(line), description.lower().strip())
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        parsed.append(item)
        candidates = [bug for bug in oracle['bugs']
                      if bug['file'] == file and abs(bug['line'] - int(line)) <= oracle['tolerance']
                      and any(re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', description, re.I)
                              for word in bug['keywords'])]
        # Nearest bug first, with a stable id tiebreak; one finding cannot claim two bugs.
        candidates.sort(key=lambda bug: (abs(bug['line'] - int(line)), bug['id']))
        if candidates:
            fresh = next((bug for bug in candidates if bug['id'] not in found), None)
            if fresh:
                found.add(fresh['id'])
            else:
                duplicates += 1
        else:
            false.append(item)
    tp = len(found) if not failed else 0
    fp = len(false)
    recall = tp / len(oracle['bugs'])
    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {'bugs_found': tp, 'bugs_planted': len(oracle['bugs']), 'false_positives': fp,
            'recall': recall, 'precision': precision, 'f1': f1, 'pass': tp == len(oracle['bugs']) and fp == 0,
            'matched': sorted(found), 'false_findings': false, 'parsed': parsed,
            'duplicates': duplicates, 'failed': failed, 'label': 'OBSERVED'}
