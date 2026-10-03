import { useEffect, useRef } from 'react';
import * as monaco from 'monaco-editor';
import type { DocState } from '../workspace';

interface Props {
  state: DocState;
  onSave: () => void;
  editorRef: React.MutableRefObject<monaco.editor.IStandaloneCodeEditor | null>;
}

export function EditorPane({ state, onSave, editorRef }: Props) {
  const divRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ed = monaco.editor.create(divRef.current!, {
      model: state.model,
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 14,
    });
    ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, onSave);
    editorRef.current = ed;
    return () => {
      editorRef.current = null;
      ed.dispose();
    };
    // 每个文档一个模型，模型不变则不重建编辑器
  }, [state.model, onSave, editorRef]);

  return (
    <div className="editor-wrap">
      <div className="doc-meta">
        修订 {state.serverRevision}
        {state.dirty ? ' · 未提交' : ' · 已保存'}
      </div>
      <div ref={divRef} className="editor" />
    </div>
  );
}
