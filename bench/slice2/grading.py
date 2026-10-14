"""Stored scored-grading procedures; live judging requires the adapter's explicit opt-in."""
import argparse
import hashlib
import json
from pathlib import Path

from bench.judges.glm_judge import make_glm_judge
from bench.slice2.audit import recipe_errors, valid_cell
from bench.slice2.grade import freeze_grades, judge_answers, score_verdicts, scored_rows_digest
from bench.slice2.protocol import ROOT, TASK, schedule
from bench.slice2.stats import report

ACCEPTED = '938b9ec62265'
MALFORMED = ('Judge content', 'Judge result', 'Judge followed_instruction',
             'Judge finding', 'GLM response')
SCORE_KEYS = ('tp', 'fp', 'recall', 'precision', 'f1', 'cross_file_recall', 'duplicates')


def reask_malformed(judge, attempts=3):
    """Use the first well-formed reply; retry only strict reply-parse failures."""
    if not 1 <= attempts <= 3:
        raise ValueError('Malformed reply attempts must be between 1 and 3')

    def call(request):
        for attempt in range(attempts):
            try:
                return judge(request)
            except ValueError as error:
                if attempt == attempts - 1 or not str(error).startswith(MALFORMED):
                    raise
                print(f'malformed judge reply (attempt {attempt + 1}): {error}; re-asking', flush=True)
    return call


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_new(*paths):
    for path in paths:
        if path.exists():
            raise FileExistsError(f'Refusing to overwrite {path}')


def write_new(path, value):
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.write('\n')


def rows_with_answers(ev, valid_only=False):
    rows = read_json(ev / 'scored.json')
    if valid_only:
        rows = [r for r in rows if valid_cell(r)]
    for row in rows:
        row['answer'] = (ev / row['cell'] / 'answer.txt').read_text(encoding='utf-8')
    return rows


def judge(ev, out, valid_only=False, accepted_prefix=ACCEPTED, oracles_path=None):
    adapter = hashlib.sha256((ROOT / 'bench/judges/glm_judge.py').read_bytes()).hexdigest()
    if not accepted_prefix or not adapter.startswith(accepted_prefix):
        raise SystemExit(f'adapter {adapter[:12]} is not the accepted judge {accepted_prefix}')
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise SystemExit('OUT must be empty')
    rows = read_json(ev / 'scored.json')
    if sorted(r['cell'] for r in rows) != sorted(c['cell'] for c in schedule('scored')):
        raise SystemExit('scored.json does not hold the frozen 40-cell schedule')
    invalid = [r['cell'] for r in rows if not valid_cell(r)]
    if invalid and not valid_only:
        raise SystemExit(f'invalid scored cells (result INCONCLUSIVE per DECLARED): {invalid}')
    if invalid:
        print('EXPLORATORY: excluded invalid cells', invalid)
        rows = [r for r in rows if valid_cell(r)]
    for row in rows:
        text = (ev / row['cell'] / 'answer.txt').read_text(encoding='utf-8')
        row['answer'] = text
        row['answer_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    oracles = read_json(oracles_path or TASK / 'hidden/oracles.json')
    try:
        packet, mapping = judge_answers(rows, reask_malformed(make_glm_judge(out / 'receipts')), oracles)
    except ValueError as error:
        print('grading stopped:', error,
              '(re-qualify with 3 consecutive control passes; DECISIONS 12:56)')
        return 1
    write_new(out / 'verdicts.json', packet | {'adapter_sha256': adapter})
    hashes = {r['cell']: r['answer_sha256'] for r in rows}
    write_new(out / 'private-mapping.json',
              {aid: m | {'answer_sha256': hashes[m['cell']]} for aid, m in mapping.items()})
    for verdict in packet['verdicts']:
        print(verdict['answer_id'], verdict['case'], len(verdict['findings']), 'findings')
    return 0


def normalize_compound(packet, path):
    """Normalize in memory only, crediting no additional bug or false positive."""
    if not path.exists():
        return
    for item in read_json(path)['items']:
        verdicts = [v for v in packet['verdicts'] if v['answer_id'] == item['answer_id']]
        if len(verdicts) != 1:
            raise ValueError('Normalization requires exactly one matching answer')
        findings = verdicts[0]['findings']
        targets = [f for f in findings if f['status'] == 'supported' and f['bug_id'] is None]
        credited = {f['bug_id'] for f in findings if f['status'] == 'supported' and f['bug_id']}
        if len(targets) != 1 or item['bug_id'] not in credited:
            raise ValueError('Normalization requires one supported null finding and a bug credited in the same answer')
        targets[0]['bug_id'] = item['bug_id']


def score(ev, g, dispositions_path, valid_only=False, normalizations_path=None, oracles_path=None):
    require_new(g / 'scores.json', g / 'scored-rows.json')
    packet = read_json(g / 'verdicts.json')
    if normalizations_path is not None:
        # An explicit path must exist; only the default file is optional.
        if not normalizations_path.exists():
            raise FileNotFoundError(normalizations_path)
    normalize_compound(packet, normalizations_path or g / 'normalizations.json')
    mapping = {aid: {k: m[k] for k in ('arm', 'cell')}
               for aid, m in read_json(g / 'private-mapping.json').items()}
    oracles = read_json(oracles_path or TASK / 'hidden/oracles.json')
    entries = read_json(dispositions_path)
    dispositions = {(d['case'], d['cause']): d['replacement'] for d in entries}
    rows = rows_with_answers(ev, valid_only)
    graded = score_verdicts(packet, rows, mapping, oracles, dispositions=dispositions)
    scores = {mapping[x['answer_id']]['cell']: x['score'] for x in graded['grades']}
    scored = [r | {'metrics': r.get('metrics', {}) | scores[r['cell']]} for r in rows]
    if scored_rows_digest(scored) != graded['scored_rows_sha256']:
        raise SystemExit('scored rows digest mismatch')
    write_new(g / 'scores.json', dict(graded=graded, dispositions=entries))
    write_new(g / 'scored-rows.json', scored)
    print('human_sample', graded['human_sample'])
    for grade in graded['grades']:
        s = grade['score']
        print(grade['answer_id'], 'tp', s['tp'], 'fp', s['fp'],
              'recall', round(s['recall'], 2), 'precision', round(s['precision'], 2))
    return 0


def build_report(ev, g, checked_path, valid_only=False):
    # --valid-only accepts the exploratory scoring path; the declared report
    # still detects its incomplete matrix, as in finish-scored.py.
    require_new(g / 'frozen-grades.json', ev / 'report.json')
    graded = read_json(g / 'scores.json')['graded']
    frozen = freeze_grades(graded, read_json(checked_path))
    rows = read_json(g / 'scored-rows.json')
    qualification = read_json(ev / 'qualification.json').get('pass')
    value = report(rows, qualification, frozen)
    write_new(g / 'frozen-grades.json', frozen)
    write_new(ev / 'report.json', value)
    print('verdict', value['verdict'], 'gaps', value['gaps'])
    for key, contrast in value['contrasts'].items():
        print(key, 'point', round(contrast['point'], 4), 'bounds',
              [round(b, 4) for b in contrast['bounds']],
              'descriptive' if contrast['descriptive'] else 'primary')
    print('quality', json.dumps(value['quality']))
    return 0


def export(ev, g, out):
    require_new(out)
    rows = read_json(ev / 'scored.json')
    graded = {r['cell']: r['metrics'] for r in read_json(g / 'scored-rows.json')}
    lines = []
    for row in sorted(rows, key=lambda r: r['cell']):
        metrics = {k: v for k, v in row['metrics'].items() if k not in SCORE_KEYS}
        score = {k: graded[row['cell']][k] for k in SCORE_KEYS} if row['cell'] in graded else None
        lines.append(dict(cell=row['cell'], case=row['case'], arm=row['arm'], rep=row['rep'],
                          status=row['status'], valid=valid_cell(row), recipe_errors=recipe_errors(row),
                          wall_s=round(row['wall_s'], 3), identity=row['identity'], metrics=metrics,
                          score=score, graded='exploratory' if score is not None else 'not graded (RECIPE_INVALID)'))
    text = ''.join(json.dumps(line, sort_keys=True) + '\n' for line in lines)
    for banned in ('answer', 'findings', 'cause', 'goal'):
        if f'"{banned}"' in text:
            raise ValueError(f'export would publish withheld field: {banned}')
    with out.open('x', encoding='utf-8') as output:
        output.write(text)
    print(len(lines), 'rows ->', out)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('judge', 'score', 'report', 'export'):
        command = commands.add_parser(name)
        command.add_argument('ev', type=Path, help='run evidence directory')
        command.add_argument('g', type=Path, help='grading directory (empty for judge)')
        if name == 'judge':
            command.add_argument('--accepted-prefix', default=ACCEPTED)
        else:
            command.add_argument('arg', type=Path,
                                 help={'score': 'dispositions.json', 'report': 'checked_ids.json',
                                       'export': 'new output.jsonl'}[name])
        if name in ('judge', 'score', 'report'):
            command.add_argument('--valid-only', action='store_true')
        if name in ('judge', 'score'):
            command.add_argument('--oracles', type=Path, default=TASK / 'hidden/oracles.json')
        if name == 'score':
            command.add_argument('--normalizations', type=Path,
                                 help='defaults to optional G/normalizations.json')
    args = parser.parse_args(argv)
    if args.command == 'judge':
        return judge(args.ev, args.g, args.valid_only, args.accepted_prefix, args.oracles)
    if args.command == 'score':
        return score(args.ev, args.g, args.arg, args.valid_only, args.normalizations, args.oracles)
    if args.command == 'report':
        return build_report(args.ev, args.g, args.arg, args.valid_only)
    return export(args.ev, args.g, args.arg)


if __name__ == '__main__':
    raise SystemExit(main())
