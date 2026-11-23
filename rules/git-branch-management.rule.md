---
id: git-branch-management
title: 作業とブランチの対応
summary: 関連作業を既存 topic/worktree へ継続し、独立作業を分離して登録と Git 操作を照合する。
---

task は成果物・要求の単位であり、agent や session の単位ではない。同じ未完了成果物は既存の
task/topic/worktree を再利用する。独立して並行更新する成果物だけを確認済み remote default branch
から別 topic/worktree へ、未統合成果物への依存は親 topic から始めて
依存先と統合先を登録する。名前で関係を推測せず、default branch は統合用で通常の直接開発には使わない。
その push 許可も直接開発の許可ではない。

workspace 契約の owner は独立 package `workspace-lifecycle`。採用済み環境の明示入口を使い、
新 source の install を旧 registry・hook の切替許可にしない。未移行 consumer は固定済み旧 source を
使い続ける。操作契約は採用版 CLI の help に従い、登録や許可を host 間で移さない。
funkot-player と funkot-autodj（`feat/player-ui`）、および管理系の agent-environment、agent-rules、
agent-runtime、agent-skills、work-records、workspace-lifecycle-native の新しい task は、Windows の session で
`wl`（workspace-lifecycle-native）を使って始める。切替より前に始めた task は、
workspace-lifecycle のまま完了か退役まで進める。

同じ作業の Git 更新と、変更の所有・受入・統合の判断は lead が担う。
完了した所有変更は秘密・ユーザーデータ・他者成果を除いて保存し、受入済みの正確な
内容を依存順に登録統合先から実際の remote default まで通常統合する。topic の保存だけで完了にしない。
Target integration は登録した統合先に届いた状態を指す。Issue は **Default integration**、
つまり受入済み成果が repository の remote default branch に届いたことを確認してから close する。
統合先が feature branch の場合は、その成果を default branch に届けてから close する。

同名 remote の取込み、別 clone/host との担当の引継ぎ、dirty の解消、checkout の退役を行うときは
skill `git-topic-lifecycle` を読む。

cherry-pick、rebase、reset、force push、履歴書換えの既存承認境界を守る。既存 hook の無効化・
上書きや新旧 writer の並行採用を統合・移行の代用にしない。

## task 完了時の checkout 退役

- legacy workspace-lifecycle は task worktree の外から `retire --users-released` を実行し、
  `reclaim --preservation-evidence <統合 commit の URL>` で recovery copy を回収する。
  worktree 内から実行した `finish` の退役は pending のまま残る。
- `wl` は `wl retire` または `wl finish --retire` で slot を空ける。recovery copy の回収手順はない。
  `wl finish --retire` を呼んだ session はその task の作業を終了する。続ける作業は新しい
  `wl begin` で始める。
