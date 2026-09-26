#!/usr/bin/env bash
# Prepare a disposable GitHub-hosted Linux VM for an authenticated native cell.
set -euo pipefail

scenario=${1:?scenario required}
case "$scenario" in
  pair) vendors=(claude codex) ;;
  all) vendors=(claude codex agy cursor) ;;
  claude|codex|agy|cursor) vendors=("$scenario") ;;
  *) exit 2 ;;
esac

sudo useradd --create-home --shell /bin/bash native-e2e
sudo chmod 700 /home/native-e2e
sudo chmod -R o-rwx "$GITHUB_WORKSPACE"
cd /tmp
tools_root=/opt/agent-rules-native-tools
sudo install -d -m 755 -o "$(id -un)" "$tools_root"
export HOME="$tools_root"
export PATH="$tools_root/.local/bin:$tools_root/npm/bin:$PATH"

for vendor in "${vendors[@]}"; do
  case "$vendor" in
    claude)
      npm install --global --prefix "$tools_root/npm" @anthropic-ai/claude-code@2.1.278
      cli="$tools_root/npm/bin/claude"
      expected='2.1.278 (Claude Code)'
      model='claude-haiku-4-5-20251001'
      ;;
    codex)
      npm install --global --prefix "$tools_root/npm" @openai/codex@0.157.1
      cli="$tools_root/npm/bin/codex"
      expected='codex-cli 0.157.1'
      model='gpt-6-luna'
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
fi
