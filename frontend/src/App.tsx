import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import * as monaco from 'monaco-editor';
import { WorkspaceController } from './workspace';
import { TabBar } from './components/TabBar';
import { EditorPane } from './components/EditorPane';
import { ConflictBanner } from './components/ConflictBanner';
import { RenameDialog } from './components/RenameDialog';
import { ApiError } from './api';

interface RenameTarget {
  docId: string;
  line: number;
  col: number;
}

export default function App() {
  const controller = useMemo(() => new WorkspaceController(), []);
  useSyncExternalStore(controller.subscribe, controller.getTick);

  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    controller.init().catch((e: unknown) => setError(String(e)));
  }, [controller]);

  const active = controller.activeId
    ? controller.docs.get(controller.activeId) ?? null
    : null;

  const showError = (e: unknown) =>
    setError(e instanceof ApiError ? `${e.message}（${e.reason}）` : String(e));

  const onNewDoc = async () => {
    const id = window.prompt('新文档 id：');
    if (!id) return;
    try {
      await controller.createDocument(id);
    } catch (e) {
      showError(e);
    }
  };

  const onSave = () => {
    if (controller.activeId) {
      controller.saveDocument(controller.activeId).catch(showError);
    }
  };

  const onRename = () => {
    const ed = editorRef.current;
    const pos = ed?.getPosition();
    if (!controller.activeId || !pos) return;
    setRenameTarget({
      docId: controller.activeId,
      line: pos.lineNumber - 1, // Monaco 1 起始 → 协议 0 起始
      col: pos.column - 1,
    });
  };

  return (
    <div className="app">
      <header className="toolbar">
        <button onClick={() => void onNewDoc()}>新建文档</button>
        <button onClick={onSave} disabled={!active}>
          保存（Ctrl+S）
        </button>
        <button onClick={onRename} disabled={!active}>
          重命名符号…
        </button>
        <span className="spacer" />
        <span className="status">
          工作区修订 {controller.workspaceRevision} ·{' '}
          {controller.connected ? '已连接' : '连接中断'}
        </span>
      </header>

      {error && (
        <div className="error-bar" onClick={() => setError(null)}>
          {error}（点击关闭）
        </div>
      )}

      <TabBar controller={controller} />

      {active?.conflict && (
        <ConflictBanner
          state={active}
          onReload={() => controller.resolveConflictReload(active.id)}
          onKeep={() => void controller.resolveConflictKeep(active.id)}
        />
      )}

      <main className="editor-area">
        {active ? (
          <EditorPane key={active.id} state={active} onSave={onSave} editorRef={editorRef} />
        ) : (
          <div className="empty">没有打开的文档</div>
        )}
      </main>

      {renameTarget && (
        <RenameDialog
          controller={controller}
          target={renameTarget}
          onClose={() => setRenameTarget(null)}
        />
      )}
    </div>
  );
}
