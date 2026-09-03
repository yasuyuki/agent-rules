---
id: git-commit-policy
title: Git commit の既定
summary: 完了して検証済みの自分の変更だけを commit し、OSS または private repository の topic branch では原則 push する。
---

作業が完了し、ユーザーに判断を仰ぐ理由がなければ、ターンを終える前に commit する。commit するのは
自分が加えた変更だけであり、作業前の `git status` を把握していない場合は commit しない。

commit は次をすべて満たすときだけ行う。

- 変更が完了し、必須の検証が通っている、または検証不要な変更である
- 対象が Git repository である
- stage 対象に秘密情報、実ユーザー情報、実絶対パス、資格情報、local-data store、ignore 対象がない
- 無関係な変更または作業前からの dirty state と混在していない
- ユーザーが保留を指示していない

push は原則として、ユーザーの指示があるか作業上必要になるまで行わない。ただし、対象が OSS または
private repository で、作業を topic branch で行った場合は、commit 後にその commit をその場で push
する。作業上の一時的な状態記録を目的とし、後で消える可能性がある commit は push しない。push 先を
既存設定から一意に決められない場合は、推測せずユーザーへ確認する。

force push、rebase、reset、tag、release、または履歴の書き換えは commit や通常の push と別の操作で
あり、明示的なユーザー承認が必要である。`git add -A` と `git commit -a` で他者の変更を巻き込まない。
ドキュメントだけの commit には `docs-skip-ci-commit` に従い `[skip ci]` を含め、コードまたは設定を
含む commit には付けない。完了報告には commit SHA と、push した場合は push 先を記す。
