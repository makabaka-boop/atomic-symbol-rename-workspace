import * as monaco from 'monaco-editor';
import { api, ApiError } from './api';
import type { DocDiagnostics, RenamePlan, WsMessage } from './types';

export const MAX_DOCUMENTS = 20;

export interface DocState {
  id: string;
  model: monaco.editor.ITextModel;
  /** 模型内容对应的服务器修订（本地未提交修改不改变它） */
  serverRevision: number;
  /** 有未提交的本地修改 */
  dirty: boolean;
  /** 服务器已前进且本地有未提交修改 → 冲突 */
  conflict: boolean;
  /** 文档已在服务器上被删除（本地仍有未提交内容时保留标签页） */
  deletedOnServer: boolean;
  /** 冲突时服务器最新内容，用于查看与解决 */
  serverShadow: string | null;
  shadowRevision: number;
}

type Listener = () => void;

export class WorkspaceController {
  docs = new Map<string, DocState>();
  order: string[] = [];
  activeId: string | null = null;
  workspaceRevision = 0;
  connected = false;

  private ws: WebSocket | null = null;
  /** 正在把服务器内容写进模型，避免误判为本地编辑 */
  private applyingRemote = new Set<string>();
  private listeners = new Set<Listener>();
  private tick = 0;

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getTick = (): number => this.tick;

  private notify() {
    this.tick += 1;
    this.listeners.forEach((f) => f());
  }

  async init(): Promise<void> {
    const { documents, workspace_revision } = await api.listDocuments();
    this.workspaceRevision = workspace_revision;
    for (const meta of documents) await this.openDocument(meta.id, false);
    this.activeId = this.order[0] ?? null;
    this.connect();
    this.notify();
  }

  // ---- WebSocket ----

  private connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.notify();
    };
    ws.onclose = () => {
      this.connected = false;
      this.notify();
      setTimeout(() => this.connect(), 1000);
    };
    ws.onmessage = (ev) => {
      void this.handleMessage(JSON.parse(ev.data as string) as WsMessage);
    };
  }

  private async handleMessage(msg: WsMessage): Promise<void> {
    if (msg.type === 'hello') {
      // 重连后按服务器状态重新对齐
      this.workspaceRevision = msg.workspace_revision;
      const serverIds = msg.documents.map((d) => d.id);
      for (const id of [...this.order]) {
        if (!serverIds.includes(id)) this.markDeleted(id);
      }
      for (const meta of msg.documents) {
        await this.applyRemoteChange(meta.id, meta.revision);
      }
    } else if (msg.type === 'workspace_revision') {
      this.workspaceRevision = msg.revision;
      for (const ch of msg.changes) {
        if (ch.deleted) this.markDeleted(ch.doc_id);
        else if (ch.revision !== undefined) {
          await this.applyRemoteChange(ch.doc_id, ch.revision);
        }
      }
    } else {
      this.applyDiagnostics(msg.docs);
      return; // 标记不进 React 状态，无需 notify
    }
    this.notify();
  }

  private markDeleted(id: string) {
    const st = this.docs.get(id);
    if (!st) return;
    if (st.dirty) {
      st.deletedOnServer = true;
      st.conflict = true;
    } else {
      this.closeDocument(id);
    }
  }

  private async applyRemoteChange(id: string, revision: number) {
    const st = this.docs.get(id);
    if (!st) return;
    if (revision <= st.serverRevision) return; // 已是最新（含自己保存的回声）
    const remote = await api.getDocument(id);
    if (remote.revision <= st.serverRevision) return;
    if (!st.dirty) {
      this.applyingRemote.add(id);
      try {
        st.model.setValue(remote.content);
      } finally {
        this.applyingRemote.delete(id);
      }
      st.serverRevision = remote.revision;
      st.conflict = false;
      st.serverShadow = null;
    } else {
      // 本地未提交文字保留，只记录服务器新版本并显示冲突
      st.conflict = true;
      st.serverShadow = remote.content;
      st.shadowRevision = remote.revision;
    }
  }

  private applyDiagnostics(payload: DocDiagnostics[]) {
    for (const d of payload) {
      const st = this.docs.get(d.doc_id);
      if (!st) continue;
      // 异步旧诊断不能覆盖新文本：修订不一致或本地已有未提交修改时丢弃
      if (st.dirty || st.serverRevision !== d.revision) continue;
      monaco.editor.setModelMarkers(
        st.model,
        'mini-lang',
        d.diagnostics.map((x) => ({
          severity:
            x.severity === 'error'
              ? monaco.MarkerSeverity.Error
              : monaco.MarkerSeverity.Warning,
          message: x.message,
          startLineNumber: x.line + 1,
          startColumn: x.start + 1,
          endLineNumber: x.line + 1,
          endColumn: x.end + 1,
        })),
      );
    }
  }

  // ---- 文档管理 ----

  async openDocument(id: string, activate = true): Promise<void> {
    if (this.docs.has(id)) {
      if (activate) this.activeId = id;
      this.notify();
      return;
    }
    const d = await api.getDocument(id);
    const model = monaco.editor.createModel(
      d.content,
      'mini-lang',
      monaco.Uri.parse(`inmemory://doc/${encodeURIComponent(id)}`),
    );
    const st: DocState = {
      id,
      model,
      serverRevision: d.revision,
      dirty: false,
      conflict: false,
      deletedOnServer: false,
      serverShadow: null,
      shadowRevision: d.revision,
    };
    model.onDidChangeContent(() => {
      if (this.applyingRemote.has(id)) return;
      st.dirty = true;
      this.notify();
    });
    this.docs.set(id, st);
    this.order.push(id);
    if (activate) this.activeId = id;
    this.notify();
  }

  async createDocument(id: string): Promise<void> {
    if (this.docs.size >= MAX_DOCUMENTS) {
      throw new Error(`工作区最多 ${MAX_DOCUMENTS} 个文档`);
    }
    await api.createDocument(id, '');
    await this.openDocument(id);
  }

  closeDocument(id: string) {
    const st = this.docs.get(id);
    if (!st) return;
    st.model.dispose();
    this.docs.delete(id);
    this.order = this.order.filter((x) => x !== id);
    if (this.activeId === id) {
      this.activeId = this.order[this.order.length - 1] ?? null;
    }
    this.notify();
  }

  activate(id: string) {
    this.activeId = id;
    this.notify();
  }

  // ---- 保存与冲突解决 ----

  async saveDocument(id: string): Promise<void> {
    const st = this.docs.get(id);
    if (!st) return;
    try {
      const res = await api.saveDocument(id, st.model.getValue(), st.serverRevision);
      st.serverRevision = res.revision;
      st.dirty = false;
      st.conflict = false;
      st.serverShadow = null;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const remote = await api.getDocument(id);
        st.conflict = true;
        st.serverShadow = remote.content;
        st.shadowRevision = remote.revision;
      } else {
        throw e;
      }
    }
    this.notify();
  }

  /** 加载服务器版本，丢弃本地未提交修改 */
  resolveConflictReload(id: string) {
    const st = this.docs.get(id);
    if (!st || st.serverShadow === null) return;
    this.applyingRemote.add(id);
    try {
      st.model.setValue(st.serverShadow);
    } finally {
      this.applyingRemote.delete(id);
    }
    st.serverRevision = st.shadowRevision;
    st.dirty = false;
    st.conflict = false;
    st.deletedOnServer = false;
    st.serverShadow = null;
    this.notify();
  }

  /** 保留本地文字，以服务器最新修订为基准强制提交 */
  async resolveConflictKeep(id: string): Promise<void> {
    const st = this.docs.get(id);
    if (!st) return;
    if (st.deletedOnServer) {
      // 服务器已删除：以当前内容重新创建
      await api.createDocument(id, st.model.getValue());
      const fresh = await api.getDocument(id);
      st.serverRevision = fresh.revision;
    } else {
      const res = await api.saveDocument(id, st.model.getValue(), st.shadowRevision);
      st.serverRevision = res.revision;
    }
    st.dirty = false;
    st.conflict = false;
    st.deletedOnServer = false;
    st.serverShadow = null;
    this.notify();
  }

  // ---- 跨文件重命名 ----

  previewRename(docId: string, line: number, col: number, newName: string) {
    return api.renamePreview(docId, line, col, newName);
  }

  /** 计划涉及的文档中仍有本地未提交修改的 id 列表（应用前必须先保存） */
  renameBlockedByDirty(plan: RenamePlan): string[] {
    return plan.edits.map((e) => e.doc_id).filter((id) => this.docs.get(id)?.dirty);
  }

  async confirmRename(planId: string): Promise<void> {
    // 成功后服务器会广播 workspace_revision，各文档随之更新
    await api.renameApply(planId);
  }
}
