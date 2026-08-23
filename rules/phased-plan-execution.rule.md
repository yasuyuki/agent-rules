---
id: phased-plan-execution
title: フェーズ分割プランの実行
summary: 名前で指定されたフェーズだけを実行し、明示的な連続実行指示がない限り次へ進まない。
tools: [cursor, claude, codex]
---

`<repo>/.claude/plan-phases/<slug>/` にフェーズファイルがある作業では、ユーザーが該当 phase を
名指ししたときだけ扱う。範囲指定も名指しとして扱う。完了しても次の phase へ連鎖しない。
連続実行は、ユーザーが対象範囲を明示した場合だけ番号順に進める。

phase 完了時は phase index の該当行を更新する。連続実行中で次の phase が明示範囲内なら前提を
照合して続け、前提が不足するかユーザー応答が必要なら停止する。それ以外は簡潔に報告して終了する。

phase directory は `<repo>/.claude/plan-phases/<slug>/` とする。リポジトリ root 自体が `.claude` の
場合は `<repo>/plan-phases/<slug>/` を使う。phase の受け入れ条件の検証が最も多く走るリポジトリが
その directory を所有し、作成後は追跡対象であることを確認する。slug directory の外に phase 文書を
置かない。

各 `phase-NN-*.md` には次を必ず含める。

- 目的、対象範囲、対象外、関連ファイルまたはサブシステム
- 守るべき制約と不変条件、受け入れ条件、必須の検証コマンド、報告形式
- 実行ホストと agent の起動ディレクトリ

計画ハーネスが作る単一の plan file は scratch であり、永続的な記録を置かない。残すべき内容は
phase directory または commit message へ移す。
