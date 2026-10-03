import { useState } from 'react';
import { ApiError } from '../api';
import type { RenamePlan } from '../types';
import type { WorkspaceController } from '../workspace';

interface Props {
  controller: WorkspaceController;
  target: { docId: string; line: number; col: number };
  onClose: () => void;
}

const REASON_TEXT: Record<string, string> = {
  DOC_CHANGED: '相关文档已被修改，整批未应用',
  INDEX_STALE: '工作区索引已失效，整批未应用',
  NAME_CONFLICT: '已存在同名声明，整批未应用',
  PLAN_EXPIRED: '预览计划已过期，请重新预览',
  PLAN_USED: '该预览计划已被应用',
  PLAN_NOT_FOUND: '预览计划不存在',
  NO_SYMBOL: '该位置没有可重命名的符号',
  BAD_NAME: '新名字必须是 ASCII 标识符且不能是关键字',
};

export function RenameDialog({ controller, target, onClose }: Props) {
  const [newName, setNewName] = useState('');
  const [plan, setPlan] = useState<RenamePlan | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const dirtyBlockers = plan ? controller.renameBlockedByDirty(plan) : [];

  const doPreview = async () => {
    setMessage(null);
    try {
      const p = await controller.previewRename(
        target.docId,
        target.line,
        target.col,
        newName,
      );
      setPlan(p);
    } catch (e) {
      setPlan(null);
      setMessage(
        e instanceof ApiError
          ? REASON_TEXT[e.reason] ?? e.message
          : String(e),
      );
    }
  };

  const doApply = async () => {
    if (!plan) return;
    setMessage(null);
    try {
      await controller.confirmRename(plan.plan_id);
      onClose();
    } catch (e) {
      setMessage(
        e instanceof ApiError
          ? `${REASON_TEXT[e.reason] ?? e.message}（未改动任何文档）`
          : String(e),
      );
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>跨文件重命名</h3>
        <div className="row">
          <input
            autoFocus
            placeholder="新名字（ASCII 标识符）"
            value={newName}
            onChange={(e) => {
              setNewName(e.target.value);
              setPlan(null);
            }}
          />
          <button onClick={() => void doPreview()} disabled={!newName}>
            预览
          </button>
        </div>

        {plan && (
          <div className="plan">
            <p>
              <code>{plan.old_name}</code> → <code>{plan.new_name}</code>
              （索引版本 {plan.index_version}）
            </p>
            <ul>
              {plan.edits.map((e) => (
                <li key={e.doc_id}>
                  <b>{e.doc_id}</b>（基准修订 {e.base_revision}）：{e.ranges.length} 处
                  <ul>
                    {e.ranges.map((r, i) => (
                      <li key={i}>
                        第 {r.line + 1} 行，列 {r.start + 1}–{r.end + 1}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
            {dirtyBlockers.length > 0 && (
              <p className="warn-text">
                以下文档有未提交的本地修改，请先保存或放弃：{dirtyBlockers.join('、')}
              </p>
            )}
            <div className="row">
              <button
                onClick={() => void doApply()}
                disabled={dirtyBlockers.length > 0}
              >
                确认应用（单事务提交）
              </button>
              <button onClick={onClose}>取消</button>
            </div>
          </div>
        )}

        {message && <p className="error-text">{message}</p>}
      </div>
    </div>
  );
}
