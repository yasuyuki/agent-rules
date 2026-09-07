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

全 agent は commit 後、push の前に正本 checkout の共通 preflight を必ず実行する。
`python3 <agent-rules>/bin/push_preflight.py <repo>` を使い、明示された指示は
`--user-intent push` / `--user-intent hold`、一時保存の根拠がある場合は `--temporary`、
明示された OSS / 非 OSS 属性は `--oss yes` / `--oss no` で渡す。省略時は自動判定する。
`<agent-rules>` は環境の正本 checkout へ解決し、見つからない・実行できない場合は
`ask` として不足を報告する。自然言語による独自判定で代用しない。
JSON の `decision` と `reason` を読み、`push` のときだけ返された `push_argv` を
対象 repo で通常実行する。preflight 自体は push せず、履歴保護を解除しない。

環境が private の許可リストを指定している場合は `--policy <path>` を付ける。
JSON は `{"default_branch_push_repositories": []}` の形式で、要素は push 先 repository の
URL とする。既存の repository 識別で完全一致させ、local path、remote 名、wildcard は使わない。
追加の boolean `default_branch_push_private` / `default_branch_push_oss` は、private 全体 /
OSS 全体を許可する。省略時は false。`default_branch_push_excluded_repositories` は同形式の
URL 配列（省略時は空）で、個別許可・属性別許可より優先して default branch の自動 push を保留する。
許可の追加・属性別の有効化はユーザーの明示指示に基づき、通常の開発依頼から推測しない。
許可は default branch を理由とする保留だけを解除し、他の条件は変えない。
未指定・許可なしは従来どおり。明示的な push / hold と一時commitの判定を優先し、
その後の自動判定で指定ファイルが欠落・読取不能・形式不正なら `ask` とする。
環境が指定したファイルを省略してこの判定を迂回しない。

preflight は次の順で判定する。`push` は通常push、`hold` はpushせず理由を報告、`ask` は
判断に必要な情報だけをユーザーへ確認することを表す。判定に必要な情報の読取は先に行ってよい。
repository属性とdefault branchの照会には、下記のremote選択順で導出した同じpush候補remoteを
使う。候補を確定できなければ、その照会が必要になった段階で `ask` とする。

1. 明示的なユーザー指示を優先する。push保留なら `hold`。push依頼があれば以下の自動push条件
   （一時commit、repository属性、topic判定）を要求しないが、宛先の特定と履歴保護は省略しない。
2. 一時commitは `hold`。一時保存・後で破棄する目的がユーザー指示または今回の作業記録に
   明記されたcommitだけを該当させる。判定はleadがその根拠を示して行い、件名のWIPや
   将来消える可能性だけから推測しない。明記がなければ通常のcommitとして次へ進む。
3. push候補remoteが指すrepositoryの属性をhosting serviceのmetadataで確認する。
   privateなら対象。publicは、明示的なOSS指定、またはrepositoryのLICENSEと対応する
   OSI承認ライセンスの識別がある場合だけ対象とする。明示的な非OSS指定があれば `hold`。
   publicというだけではOSSとしない。属性不明、根拠の矛盾、認証失敗は `ask`。
4. detached HEADは `ask`。push候補remoteのdefault branchはhosting serviceのmetadata、
   それが利用できなければ `git ls-remote --symref <remote> HEAD` で取得する。
   ローカルのorigin/HEADやmain/masterという名前だけでは決めない。取得不能・矛盾は `ask`。
   current branchがdefault branchと同名、またはそのremoteのdefault branchを追跡するなら
   push候補remoteのrepositoryが除外対象、または個別・属性別のいずれでも許可されなければ `hold`。
   それ以外の名前付きbranchを、この規則のtopic branchとする。
5. 宛先を以下で一意に確定できれば `push`、できなければ `ask`。自動pushはcommit直後に行う。

push候補remoteは `branch.<current>.pushRemote` → `remote.pushDefault` →
`branch.<current>.remote` → remoteが1つだけならそれ、の順で最初の設定を使う。
設定先が不存在、ローカルの `.`、複数のpush URL、fetch先と異なるrepositoryへのpush URLなら
`ask`。複数remoteで設定がない場合はoriginという名前を優先しない。forkも同じ順で扱う。

宛先branchは、候補remoteとupstream remoteが同じならupstream branch、upstreamがないか
別remoteならcurrent branchと同名とする。これによりupstreamなしでもremoteが一意なら進める。
`remote.<remote>.push` の独自refspecやmirror設定があれば `ask` とし、複数branchを送らない。
自動pushの宛先branchがdefault branchなら、同じ個別・属性別許可と除外判定を行う。確定後は
`git push <remote> HEAD:refs/heads/<destination>` と宛先を明示する。
拒否・認証失敗は結果を報告して `hold` とし、別remoteやforce pushで再試行しない。

force push、rebase、reset、tag、release、または履歴の書き換えは commit や通常の push と別の操作で
あり、明示的なユーザー承認が必要である。`git add -A` と `git commit -a` で他者の変更を巻き込まない。
ドキュメントだけの commit には `docs-skip-ci-commit` に従い `[skip ci]` を含め、コードまたは設定を
含む commit には付けない。完了報告には commit SHA と、push した場合は push 先を記す。
