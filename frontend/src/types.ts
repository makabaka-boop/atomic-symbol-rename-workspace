// 与后端约定的协议类型。位置一律为 0 起始行号 + UTF-16 代码单元列。

export interface DocMeta {
  id: string;
  revision: number;
}

export interface DiagnosticItem {
  line: number;
  start: number;
  end: number;
  severity: 'error' | 'warning';
  message: string;
}

export interface DocDiagnostics {
  doc_id: string;
  revision: number;
  diagnostics: DiagnosticItem[];
}

export interface WorkspaceChange {
  doc_id: string;
  revision?: number;
  deleted?: boolean;
}

export type WsMessage =
  | { type: 'hello'; workspace_revision: number; documents: DocMeta[] }
  | { type: 'workspace_revision'; revision: number; changes: WorkspaceChange[] }
  | { type: 'diagnostics'; docs: DocDiagnostics[] };

export interface RenameRange {
  line: number;
  start: number;
  end: number;
}

export interface RenameEdit {
  doc_id: string;
  base_revision: number;
  ranges: RenameRange[];
}

export interface RenamePlan {
  plan_id: string;
  old_name: string;
  new_name: string;
  index_version: number;
  edits: RenameEdit[];
}

export interface ApplyResult {
  workspace_revision: number;
  changes: { doc_id: string; revision: number }[];
}
