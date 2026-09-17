---
id: git-branch-management
title: 作業とブランチの対応
summary: 関連作業を既存 topic/worktree へ継続し、独立作業を分離して登録と Git 操作を照合する。
---

既存要求と成果物を照合し、同じ未完了成果物は登録済み topic/worktree を再利用する。独立した成果物は
確認済み remote default branch から別 topic/worktree へ、未統合成果物への依存は親 topic から始めて
依存先と統合先を登録する。名前で関係を推測せず、default branch は統合用で通常の直接開発には使わない。
その push 許可も直接開発の許可ではない。

公開 `bin/place.py branch` の `install`、`begin`、`check`、`retire` を使う。登録は Git common
directory のローカル状態であり、製品進捗台帳へ複製せず host 間で操作許可を移さない。既存採用では履歴の
起点を明示して導入前を遡及違反にせず、別 clone の再開は同じ作業識別子と remote 履歴で照合する。

同じ worktree の Git 更新と、関連性・検証の判断は lead が担う。他の作業中 checkout を切り替えない。
検証済み成果物は依頼範囲で親から子へ通常 merge し、登録された統合先で `prepare-merge` 後に
`git merge --no-ff --no-commit` を準備し、検証して commit する。元または先が変われば `prepare-merge` をやり直す。

統合記録と統合先履歴で統合済みと確認でき、不要になった checkout だけを `retire` する。未統合成果物、依存・統合先に参照される登録、
repository 本体、hook source、runtime は退役させない。CLI は登録と worktree だけを外し branch/commit は
残すため、task ごとに使い、直接の worktree 削除・prune・台帳編集や定期一括掃除で迂回しない。

cherry-pick は本人が承認した元 commit・宛先・理由を `allow-cherry-pick` に登録した場合だけ行う。
rebase、reset、force push、履歴書換えの既存承認境界を守る。拒否・競合・中断は状態を保って正規入口から
再開し、reset/stash/delete で回避しない。hook は登録と Git 状態を検査するが、変更由来や同じ
fast-forward を生む操作を完全には判別できない。この迂回を禁止し、hook を共存させられなければ上書きせず
導入を止める。
