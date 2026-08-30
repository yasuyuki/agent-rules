---
id: phased-plan-execution
title: フェーズ分割プランの実行
summary: 名指しされたフェーズだけを実行し、受け入れ条件は追跡ファイルの1行にする。完了は記録せず文書を削除する。
---

`<repo>/.claude/plan-phases/<slug>/` にフェーズファイルがある作業では、ユーザーが該当 phase を
名指ししたときだけ扱う。範囲指定も名指しとして扱う。完了しても次の phase へ連鎖しない。
連続実行は、ユーザーが対象範囲を明示した場合だけ番号順に進め、前提が不足するか
ユーザー応答が必要なら停止する。それ以外は簡潔に報告して終了する。

phase の受け入れ条件は、リポジトリ内の追跡されたファイルを1行で呼び出して判定できる形にする。
実行ホストと作業ディレクトリはその1行の内側に置く。1行で書けないなら phase を分割するか
phase にしない。ユーザーへ実行を依頼するときも渡すのはその1行だけとし、複数行のコマンドを
その場で組み立てて渡さない。

phase 文書には、その1行と、機械が判定できない事項だけを書く。状態、完了記録、依存 revision、
再取得できる値を書かない。index に状態や進捗の欄を作らない。受け入れ条件が通ったら、その phase
文書と、index にその phase を指す行があればその行も、両方を削除する。phase directory と index は
残っている作業だけを表し、完了の記録は commit が持つ。

phase directory は `<repo>/.claude/plan-phases/<slug>/` とする。リポジトリ root 自体が `.claude` の
場合は `<repo>/plan-phases/<slug>/` を使う。slug directory の外に phase 文書を置かない。

計画ハーネスが作る単一の plan file は scratch であり、永続的な記録を置かない。残すべき内容は
phase directory または commit message へ移す。
