---
id: phased-plan-execution
title: フェーズ分割プランの実行
summary: ユーザーが承認した目的と範囲を実行し、phase 文書は再開と検証に使う。
---

phase は作業を再開できる大きさに分ける道具であり、追加の承認 gate ではない。
ユーザーが目的全体を依頼したなら、その達成に必要な phase を依存順に続ける。
特定 phase や範囲だけを指定した場合はそこで止める。文書の存在だけで実行範囲を広げない。
未承認の外部操作、解消できない前提不足、ユーザーだけが決められる事項では停止する。
rule experiment の executor と証拠の境界は `rule-experiment-role-gate` に従う。

長期作業の phase 文書には目的、範囲、必要な前提、受け入れ条件と再実行できる検証 command を
書く。host と cwd が自明でなければ明示する。既存の test / build を使い、1行にするためだけの
wrapper や追加 phase は作らない。機械で判定できない事項と未検証の事項を区別する。

既存の `<repo>/.claude/plan-phases/<slug>/` を使う。repo 自体が `.claude` なら
`<repo>/plan-phases/<slug>/`。短い作業に phase 文書は不要。
受け入れ条件が通った phase 文書と index の参照を削除し、未完了だけを残す。
恒久的な手順と設計判断は README / docs へ移し、再開地点は HANDOFF に残す。
一時的な plan file にだけ再開に必要な情報を置かない。
