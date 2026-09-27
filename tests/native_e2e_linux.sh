#!/usr/bin/env bash
# Prepare a disposable GitHub-hosted Linux VM for an authenticated native cell.
set -euo pipefail

scenario=${1:?scenario required}
claude_model=claude-haiku-4-5-20251001
codex_model=gpt-6-luna
case "$scenario" in
  pair) vendors=(claude codex) ;;
  all) vendors=(claude codex agy cursor) ;;
  claude|codex|agy|cursor) vendors=("$scenario") ;;
  *) exit 2 ;;
esac

sudo useradd --create-home --shell /bin/bash native-e2e
sudo chmod 700 /home/native-e2e
sudo chmod -R o-rwx "$GITHUB_WORKSPACE"
for vendor in "${vendors[@]}"; do
  case "$vendor" in
    claude) key=ANTHROPIC_API_KEY ;;
    codex) key=OPENAI_API_KEY ;;
    agy) key=GEMINI_API_KEY ;;
    cursor) key=CURSOR_API_KEY ;;
  esac
  if ! sudo -n --preserve-env="$key" -u native-e2e python3 -c \
      'import os,sys; sys.exit(not os.environ.get(sys.argv[1]))' "$key"; then
    printf 'probe user cannot receive %s through isolated launcher\n' "$key" >&2
    exit 1
  fi
done
for vendor in "${vendors[@]}"; do
  case "$vendor" in
    claude) key=ANTHROPIC_API_KEY; model=$claude_model ;;
    codex) key=OPENAI_API_KEY; model=$codex_model ;;
    *) continue ;;
  esac
  sudo -n --preserve-env="$key" -u native-e2e python3 - "$vendor" "$model" <<'PY'
import os
import sys
import urllib.error
import urllib.request

vendor, model = sys.argv[1:]
if vendor == 'claude':
    url = 'https://api.anthropic.com/v1/models/' + model
    headers = {'x-api-key': os.environ['ANTHROPIC_API_KEY'],
               'anthropic-version': '2023-06-01'}
else:
    url = 'https://api.openai.com/v1/models/' + model
    headers = {'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']}
request = urllib.request.Request(
    url, headers=headers,
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            print(f'{vendor} model preflight HTTP {response.status}', file=sys.stderr)
        else:
            print(f'{vendor} model preflight passed')
except urllib.error.HTTPError as error:
    print(f'{vendor} model preflight HTTP {error.code}', file=sys.stderr)
except (urllib.error.URLError, TimeoutError):
    print(f'{vendor} model preflight network failure', file=sys.stderr)
PY
done
cd /tmp
tools_root=/opt/agent-rules-native-tools
sudo install -d -m 755 -o "$(id -un)" "$tools_root"
export HOME="$tools_root"
export PATH="$tools_root/.local/bin:$tools_root/npm/bin:$PATH"

for vendor in "${vendors[@]}"; do
  case "$vendor" in
    claude)
      npm install --global --prefix "$tools_root/npm" @anthropic-ai/claude-code@2.1.283
      cli="$tools_root/npm/bin/claude"
      expected='2.1.283 (Claude Code)'
      model=$claude_model
      ;;
    codex)
      npm install --global --prefix "$tools_root/npm" @openai/codex@0.157.1
      cli="$tools_root/npm/bin/codex"
      expected='codex-cli 0.157.1'
      model=$codex_model
      ;;
    agy)
      curl -fsSL https://antigravity.google/cli/install.sh -o "$RUNNER_TEMP/agy-install.sh"
      bash "$RUNNER_TEMP/agy-install.sh" --skip-aliases --skip-path
      cli="$tools_root/.local/bin/agy"
      expected='1.2.0'
      model='gemini-3.5-flash-medium'
      sudo -u native-e2e mkdir -p /home/native-e2e/.gemini/antigravity-cli
      printf '%s\n' '{"modelProvider":"gemini","enableTerminalSandbox":true,"permissions":{"allow":["command(python3)"]}}' \
        | sudo -u native-e2e tee /home/native-e2e/.gemini/antigravity-cli/settings.json >/dev/null
      ;;
    cursor)
      curl -fsSL https://cursor.com/install -o "$RUNNER_TEMP/cursor-install.sh"
      bash "$RUNNER_TEMP/cursor-install.sh"
      cli="$tools_root/.local/bin/agent"
      expected='2026.09.10-fd3934a'
      model='gpt-5'
      sudo -u native-e2e mkdir -p /home/native-e2e/.cursor
      printf '%s\n' '{"version":1,"editor":{"vimMode":false},"permissions":{"allow":["Shell(python3)"],"deny":["Shell(sudo)"]}}' \
        | sudo -u native-e2e tee /home/native-e2e/.cursor/cli-config.json >/dev/null
      ;;
  esac

  actual=$($cli --version 2>/dev/null)
  if [[ "$actual" != "$expected" ]]; then
    printf 'native CLI version drift: expected %s, got %s\n' "$expected" "$actual" >&2
    exit 1
  fi
  if ! sudo -n -u native-e2e test -x "$cli"; then
    echo 'probe user cannot execute the installed native CLI' >&2
    exit 1
  fi
  upper=${vendor^^}
  printf '%s\n' "NATIVE_CLI_$upper=$cli" "NATIVE_MODEL_$upper=$model" \
    "NATIVE_VERSION_$upper=$actual" >> "$GITHUB_ENV"
  if [[ "$scenario" != all && "$scenario" != pair ]]; then
    printf '%s\n' "NATIVE_CLI=$cli" "NATIVE_MODEL=$model" >> "$GITHUB_ENV"
  fi
done

if sudo -n -u native-e2e test -r "$GITHUB_WORKSPACE"; then
  echo 'probe user can read the source checkout' >&2
  exit 1
fi

if [[ " ${vendors[*]} " == *' codex '* ]]; then
  printf '%s' "$OPENAI_API_KEY" | sudo -n -u native-e2e env HOME=/home/native-e2e \
    "$tools_root/npm/bin/codex" login --with-api-key >/dev/null
  sudo -n -u native-e2e env HOME=/home/native-e2e CODEX_HOME=/home/native-e2e/.codex \
    python3 - "$tools_root/npm/bin/codex" <<'PY'
import json
from pathlib import Path
import subprocess
import sys

cli = sys.argv[1]
home = Path('/home/native-e2e/.codex')
catalog = json.loads(subprocess.check_output([cli, 'debug', 'models', '--bundled'],
                                             stderr=subprocess.DEVNULL))
matches = [model for model in catalog['models'] if model['slug'] == 'gpt-6-luna']
if (len(matches) != 1 or matches[0].get('use_responses_lite') is not True
        or matches[0].get('tool_mode') != 'code_mode_only'):
    raise RuntimeError('pinned Codex model catalog changed; review native tool setup')
matches[0]['use_responses_lite'] = False
matches[0]['tool_mode'] = None
catalog_path = home / 'native-e2e-models.json'
catalog_path.write_text(json.dumps(catalog))
if (home / 'config.toml').exists():
    raise RuntimeError('isolated Codex profile already has a model configuration')
effective = json.loads(subprocess.check_output([cli, 'debug', 'models',
                                                 '-c', f'model_catalog_json="{catalog_path}"'],
                                                stderr=subprocess.DEVNULL))
chosen = [model for model in effective['models'] if model['slug'] == 'gpt-6-luna']
if (len(chosen) != 1 or chosen[0].get('use_responses_lite') is not False
        or chosen[0].get('tool_mode') is not None):
    raise RuntimeError('isolated Codex catalog override was not loaded')
print('isolated Codex standard Responses catalog prepared')
PY
fi
