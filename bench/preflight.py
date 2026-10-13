"""Only executed under the cell's clean environment and sandbox."""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    values = dict(line.split('=', 1) for line in (Path(os.environ['HERMES_HOME']) / '.env').read_text().splitlines())
    key = values['GLM_API_KEY'].strip().strip('"\'')
    rows = []
    for model in ('glm-5.3', 'glm-5.2', 'glm-5.1'):
        for attempt in (1, 2):
            request = urllib.request.Request(values['GLM_BASE_URL'] + '/chat/completions',
                data=json.dumps({'model': model, 'max_tokens': 1, 'messages': [{'role': 'user', 'content': 'ping'}]}).encode(),
                headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
            quota = False
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
                quota = status == 429 or bool(re.search(r'quota|balance|rate.?limit|usage.?limit', error.read().decode(errors='replace'), re.I))
            except Exception as error:
                status = type(error).__name__
            row = {'model': model, 'status': status, 'attempt': attempt, 'quota': quota, 'label': 'OBSERVED'}
            rows.append(row)
            if not quota:
                break
            if attempt == 2:
                row['quota_stop'] = True
                print(json.dumps(rows))
                return
            time.sleep(60)
    print(json.dumps(rows))


if __name__ == '__main__':
    main()
