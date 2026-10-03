import type { WorkspaceController } from '../workspace';

export function TabBar({ controller }: { controller: WorkspaceController }) {
  return (
    <div className="tab-bar">
      {controller.order.map((id) => {
        const st = controller.docs.get(id);
        if (!st) return null;
        const cls = [
          'tab',
          id === controller.activeId ? 'active' : '',
          st.conflict ? 'conflict' : '',
        ]
          .filter(Boolean)
          .join(' ');
        return (
          <div key={id} className={cls} onClick={() => controller.activate(id)}>
            <span>{id}</span>
            {st.dirty && <span className="dot" title="有未提交修改">●</span>}
            {st.conflict && <span className="warn" title="与服务器冲突">⚠</span>}
            <span
              className="close"
              onClick={(e) => {
                e.stopPropagation();
                controller.closeDocument(id);
              }}
            >
              ×
            </span>
          </div>
        );
      })}
    </div>
  );
}
