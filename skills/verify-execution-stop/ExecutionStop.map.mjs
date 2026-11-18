export const title = '実行依頼の中断と取消';

export function state(v) {
  if (v.out === 'reasonless') return '取消後に理由なしの通知';
  if (v.out === 'demand' && v.userPaused) return '中断中に継続を要求';
  if (v.review?.phase === 'interrupted') return '中断を保存、審査結果待ち';
  if (v.review?.phase === 'working') return 'Stop が審査中';
  if (!v.bound) return '実行依頼なし';
  if (v.ended === 'cancelled') return v.turnOpen ? '依頼を取消済み' : '取消済み、通知なし';
  if (v.ended === 'complete' || v.ended === 'unmanaged') return '依頼を終了';
  if (v.userPaused && !v.interrupted && !v.suspended) {
    return v.turnOpen ? '質問を実行中の依頼として扱う' : '中断の記録を失う';
  }
  if (v.suspended) return '別の依頼に切り替え、元の依頼を保留';
  if (v.interrupted) {
    if (v.out === 'handoff') return '中断理由を通知、再開待ち';
    return v.turnOpen ? '質問に応答、依頼は中断中' : '中断中、再開待ち';
  }
  if (v.resumed) return '依頼を明示的に再開';
  if (v.out === 'demand') return '作業の継続を要求';
  if (v.out === 'handoff') return '未完了の引継ぎを通知';
  return '実行依頼を受理';
}

const labels = {
  UserGivesIssue: 'Issue の作業を依頼する',
  UserPointsToOtherIssue: '別の Issue に置き換える',
  UserChats: '別の話をする',
  UserFollowsUp: '作業を再開せず質問する',
  UserResumes: '作業の再開を依頼する',
  UserSwitchesTask: '別の依頼に切り替える',
  UserCancels: '実行依頼を取り消す',
  UserInterrupts: 'ターンを中断する',
  ToolRuns: 'ツールを使う',
  StartStopReview: '作業結果の審査を始める',
  InterruptDuringReview: '審査中にターンを中断する',
  DiscardStopReview: '古い審査結果を破棄する',
  StopQuietly: '通知を出さずに終える',
  StopWhileInterrupted: '中断理由を通知する',
  StopNoNewEvidence: '新しい作業結果なしで終える',
  ReviewerContinueAccepted: '続ける作業が見つかる',
  ReviewerContinueWithoutProgress: '未完了の引継ぎを通知する',
  ReviewerUnverified: '未完了の引継ぎを通知する',
  ReviewerBlocked: '未完了の引継ぎを通知する',
  ReviewerCancelled: '取消を通知する',
  ReviewerComplete: '受入を確認する',
  ReviewerCompleteWithoutEvidence: '未完了の引継ぎを通知する',
  ReviewerUnmanaged: '実行依頼を終了する',
  ReviewerUnmanagedAfterWork: '未完了の引継ぎを通知する',
};

export function step(action, from, to) {
  if (!from.lost && to.lost) return '審査中に中断し、古い審査結果で上書き';
  if (action === 'StopWhileInterrupted' && to.out === 'reasonless') return '取消を中断として扱う';
  return labels[action] ?? labels[chartActions[action]] ?? action;
}

const chartActions = {
  ChartReview: 'StartStopReview',
  ChartInterrupt: 'UserInterrupts',
  ChartQuestion: 'UserFollowsUp',
  ChartCancel: 'UserCancels',
  ChartResume: 'UserResumes',
};
