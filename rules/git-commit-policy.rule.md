---
id: git-commit-policy
title: Git commit の既定
summary: 検証済みの自分の変更を commit し、OSS または private の topic branch と明示許可された default branch は原則 push する。
---

作業が完了し、ユーザーに判断を仰ぐ理由がなければ、ターンを終える前に commit する。commit するのは
自分が加えた変更だけであり、作業前の `git status` を把握していない場合は commit しない。

commit は次をすべて満たすときだけ行う。

- 変更が完了し、必須の検証が通っている、または検証不要な変更である
- 対象が Git repository である
- stage 対象に秘密情報、実ユーザーデータ、資格情報、local-data store、ignore 対象がない。
  machine 固有の path は公開 repo へ入れず、private 環境の配置宣言や運用文書に必要な場合だけ残す
- 無関係な変更または作業前からの dirty state と混在していない
- ユーザーが保留を指示していない

無関係な dirty state はそのまま保ち、自分の変更を分離して stage できれば進める。
検証失敗はまず自分で解決する。分離できない変更や解消できない失敗だけを報告して判断を仰ぐ。

commit 後、push 前に環境が指定する正本の `bin/push_preflight.py` を対象 repo に対して実行する。
入力と出力は同入口の `--help` を参照し、判定表や宛先選択を規約側で再実装しない。
指定された private policy は必ず渡し、読取不能を省略で迂回しない。入口が利用できなければ
不足を報告し、独自判断で push しない。

入力にする明示的な push / hold、OSS / 非 OSS 指定はユーザーの指示に基づく。
一時保存はユーザー指示または今回の作業記録にその目的が明記された場合だけとし、
WIP 件名や将来消える可能性から推測しない。policy の許可追加も本人の明示指示を要する。

JSON の `decision` と `reason` を読み、`push` のときだけ `push_argv` を対象 repo で通常実行する。
`hold` は理由を報告し、`ask` は既存権限で不足情報を調べてから必要な判断だけを尋ねる。
拒否・認証失敗時は原因未解消の再試行、別 remote、force push で回避しない。
許可済みの同じ repo・宛先・範囲なら、登録された正規経路で修復し、再検証・preflight 後に続けてよい。
元 commit・dirty・remote 更新を保持し、無関係な履歴の取込み、承認の流用、hook 解除、
state 直編集や自動 reset / stash / clean で解消しない。分離不能な変更や権限不足は報告する。

force push、rebase、reset、tag、release、または履歴の書き換えは commit や通常の push と別の操作で
あり、明示的なユーザー承認が必要である。`git add -A` と `git commit -a` で他者の変更を巻き込まない。
ドキュメントだけの commit には `docs-skip-ci-commit` に従い `[skip ci]` を含め、コードまたは設定を
含む commit には付けない。完了報告には commit SHA と、push した場合は push 先を記す。
