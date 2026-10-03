import { useState } from 'react';
import type { DocState } from '../workspace';

interface Props {
  state: DocState;
  onReload: () => void;
  onKeep: () => void;
}

export function ConflictBanner({ state, onReload, onKeep }: Props) {
  const [showServer, setShowServer] = useState(false);
  return (
    <div className="conflict-banner">
      <div className="conflict-row">
        {state.deletedOnServer ? (
          <span>⚠ 该文档已在服务器上删除，本地修改未提交。</span>
        ) : (
          <span>
            ⚠ 服务器已有新版本（修订 {state.shadowRevision}），你的本地修改未提交。
          </span>
        )}
        <button onClick={() => setShowServer((v) => !v)}>
          {showServer ? '隐藏服务器版本' : '查看服务器版本'}
        </button>
        {!state.deletedOnServer && (
          <button onClick={onReload}>加载服务器版本（丢弃本地）</button>
        )}
        <button onClick={onKeep}>
          {state.deletedOnServer ? '以本地内容重新创建' : '保留本地并强制保存'}
        </button>
      </div>
      {showServer && state.serverShadow !== null && (
        <pre className="server-shadow">{state.serverShadow}</pre>
      )}
    </div>
  );
}
