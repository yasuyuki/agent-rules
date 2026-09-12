---
id: git-branch-management
title: 作業とブランチの対応
summary: 関連作業を既存 topic/worktree へ継続し、独立作業を分離して登録と Git 操作を照合する。
---

作業開始時に既存要求への参照と成果物を確認する。同じ未完了成果物は登録済みの topic と
worktree を再利用する。独立した成果物は確認済み remote default branch から別 topic・別
worktree を作る。未統合成果物に依存する別成果物は親 topic を起点にし、依存先と統合先を登録する。
名前だけで関係を推測しない。default branch は統合用であり、通常の直接開発には使わない。
default branch への push 許可は直接開発の許可ではない。

公開 `bin/place.py branch` の `install` / `begin` / `check` / `retire` を使う。登録は Git
common directory に置き、製品の進捗台帳を複製しない。既存採用には履歴の起点を明示し、
導入前の履歴を遡及して違反にしない。別 clone での再開は同じ作業識別子で再登録し、
remote 履歴と照合する。ローカル操作許可を別 host へコピーしない。

同じ worktree の Git 更新は lead が担当する。他の作業が使用中の checkout を切り替えない。
検証済みの成果物は依頼範囲内で親から子の順に通常 merge で統合する。登録された統合先で
`prepare-merge` により移送元・移送先を固定し、`git merge --no-ff --no-commit` で準備する。
統合結果を検証してから commit する。元・先が変われば許可を取り直す。

統合が完了し、その checkout を使い続ける予定がなくなったら `retire` で登録を解除する。
完了は台帳の統合記録と統合先の履歴で判定し、`git branch --merged`、branch 名、更新日時では
判定しない。未統合の成果物、他の登録が依存先または統合先とする登録、repository 本体の
checkout、登録された hook source や runtime を含む checkout は retire しない。retire は登録と
worktree を外すだけで branch と commit は残す。作業識別子を指定して1件ずつ行い、一括削除や
期間・件数による定期的な掃除は行わない。`git worktree remove` の直接実行、directory の削除、
`git worktree prune`、台帳の手編集で登録を消したことにしない。

cherry-pick は通常禁止。本人が承認した元 commit・移送先・理由だけを `allow-cherry-pick` に
登録する。承認済みの範囲を再確認しない。rebase・reset・force push・履歴書換えの既存承認境界を
維持する。拒否・競合・中断で変更を自動 reset / stash / 削除しない。再試行は保持された状態から行う。
retire の拒否も同じで、削除で回避しない。

hook は登録と Git 状態を検査する。機能上の関連性と検証の妥当性は lead が判断する。
`cherry-pick --no-commit` 後の変更由来と、同じ fast-forward を生むコマンドの違いは判別できない。
これらによる規則の迂回を禁止する。意図的な設定無効化を隔離で防ぐ機構ではなく、完全遮断とは
説明しない。既存 hook の共存を保存できないときは上書きせず導入を止める。
