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

同じ作業の Git 更新と、変更の所有・受入・統合の判断は lead が担う。分担する変更範囲を割り当て、
merge・検証・commit・push の対象を確定する間は競合するファイル更新も止める。別 clone/host を
含め同じ remote topic の更新担当は一時点で一つとし、既存 task/Issue に担当と保存先 commit を
残して引き継ぐ。後任は対象 remote を取得して再開する。local lease や Git lock を host 間の排他と
扱わない。他の作業中 checkout を切り替えず、agent ごとの branch や同期用 task を作らない。

同名 remote の取込みは同じ作業の同期であり、別 task の受入や統合完了ではない。確認済みの同じ
repo・宛先・作業範囲を操作 owner の正規入口で通常 merge し、競合や途中操作も同じ task で解消する。
元 commit と完了済みの保全処理を保持し、HEAD が変わればその HEAD で再検証する。旧検証を新 HEAD の
受入へ流用せず、同期だけで accepted/integrated や退役可能にしない。push の許可と宛先は共通
preflight に従う。別 source への無条件の付替えや intent の破棄、同じ変更の再commit で再開を代用しない。

default と複数 task の共有統合先は受入済み成果の統合に使い、別 task の直接開発先と兼用しない。
完了した所有変更は秘密・ユーザーデータ・他者成果を除いて保存し、受入済みの正確な
内容を依存順に登録統合先から実際の remote default まで通常統合する。topic の保存だけで完了にしない。
競合・検証失敗・中断は同じ対象と状態を保持して解消し、新 branch や履歴書換えへ逃がさない。

再生成可能な所有生成物は根拠を確認して解消する。固有情報は承認された別管理先への保存・読戻しを
完了してから元を扱う。dirty を残す例外は、適用可能な全代替案が回復不能な問題を生じると確認できる
場合だけとし、根拠・担当・次操作を正本に残す。所有不明や手間だけを不可逆な危険とみなさない。

不要になった checkout の退役は、保全結果・実際の統合・対象 identity・外部利用終了を確認して行う。
未統合成果物、依存・統合先として参照される登録、repository 本体、hook source、runtime を退役させない。
利用 lease と Git の管理 lock を混同せず、実体と登録の消失を確認し branch/commit を保持する。
強制削除、無条件 unlock、台帳手編集、全 branch の一括統合・定期掃除で迂回しない。

cherry-pick、rebase、reset、force push、履歴書換えの既存承認境界を守る。既存 hook の無効化・
上書きや新旧 writer の並行採用を統合・移行の代用にしない。通常の直接 Git 操作や強制終了を
lifecycle CLI がすべて捕捉できるとは扱わない。
