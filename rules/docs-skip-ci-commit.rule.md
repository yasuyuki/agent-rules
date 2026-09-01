---
id: docs-skip-ci-commit
title: ドキュメントのみ更新時の CI スキップ
summary: ドキュメントだけのコミットには [skip ci] を含め、コードまたは設定を含むコミットには付けない。
tools: [cursor, claude, codex]
---

変更がドキュメントだけのコミットでは、CI を起動しないよう commit message の件名または本文に
`[skip ci]` を含める。既存の commit message の形式は維持する。

次をすべて満たすときだけ適用する。

1. stage した対象が説明文だけであり、たとえば Markdown、reStructuredText、または docs 配下の文書である
2. アプリコード、設定、CI、依存関係、テスト、ビルド成果物、またはコメント以外の変更を含まない

コードまたは設定が1ファイルでも含まれる場合は `[skip ci]` を付けない。迷ったらスキップしない。
ユーザーが CI の実行またはスキップを明示した場合は、その指示を優先する。
