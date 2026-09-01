---
id: git-commit-policy
title: Git commit の既定
summary: 完了して検証済みの自分の変更だけを commit し、push・履歴操作・曖昧な差分はユーザー判断へ回す。
---

作業が完了し、ユーザーに判断を仰ぐ理由がなければ、ターンを終える前に commit する。commit するのは
自分が加えた変更だけであり、作業前の `git status` を把握していない場合は commit しない。

commit は次をすべて満たすときだけ行う。

- 変更が完了し、必須の検証が通っている、または検証不要な変更である
- 対象が Git repository である
- stage 対象に秘密情報、実ユーザー情報、実絶対パス、資格情報、local-data store、ignore 対象がない
- 無関係な変更または作業前からの dirty state と混在していない
- ユーザーが保留を指示していない

push、force、rebase、reset、tag、release、または履歴の書き換えは commit と別の操作であり、明示的な
ユーザー承認が必要である。`git add -A` と `git commit -a` で他者の変更を巻き込まない。ドキュメント
だけの commit には `docs-skip-ci-commit` に従い `[skip ci]` を含め、コードまたは設定を含む commit には
付けない。完了報告には commit SHA を記す。
