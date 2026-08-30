---
id: rule-experiment-role-gate
title: Rule experiment role gate
summary: 実験の controller と subject の責務を分離し、baseline・測定・variant を越境変更しない。
tools: [cursor, claude, codex]
---

rule experiment では、最初に phase metadata の executor を読む。

1. controller は apparatus の宣言ファイルだけを変更し、subject workload を実装しない
2. subject は variant source、measurement、constitution、review を変更しない
3. baseline を直接変更しない
4. 低レベル launch wrapper を使わない

constitution は `CONSTITUTION.md` と `docs/IMPROVEMENT-POLICY.md` の2文書を指し、両者は同位である。
前者は装置が何であるかを、後者は purpose を失わずにどう削減し改善するかを定める。どちらも削減の
一手として消さず、変更は purpose または改善順序を変える意図的な決定として行う。

役割と phase の境界を越える必要が生じたら、実装を続けず handoff して適切な executor の指示を待つ。
