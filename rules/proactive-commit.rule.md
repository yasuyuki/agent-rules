---
id: proactive-commit
title: 積極的なコミット
summary: 検証済みで一つの意図にまとまった変更は、保留指示や判断事項がなければ積極的にコミットする。
tools: [cursor, claude, codex]
---

ユーザーが commit を明示しなくても、受け入れ条件を満たす一つの意図の変更は commit する。
未コミットのまま次のターンへ持ち越さない。

次をすべて満たすときに commit する。

1. 変更が機能、修正、またはリファクタなど一つの意図にまとまっている
2. 必須のテスト、build、または指定された検証が通っている。検証不要な変更ならその理由が明確である
3. 秘密情報、ignore 対象、または一時的なデバッグ残骸を含まない
4. push、tag、release、履歴書き換えを含まない

無関係な変更の混在、検証方法の不明、秘密情報の疑い、未完了または失敗した検証、ユーザーによる
保留指示があるときは、勝手にまとめず判断を仰ぐ。commit の対象、stage 方法、message、docs-only の
CI スキップ、subagent の禁止事項は `git-commit-policy` と `docs-skip-ci-commit` に従う。
