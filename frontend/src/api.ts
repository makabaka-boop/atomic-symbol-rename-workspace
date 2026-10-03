import type { ApplyResult, DocMeta, RenamePlan } from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    public reason: string,
    message: string,
    public extra: Record<string, unknown>,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail: Record<string, unknown> = {};
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'object') detail = body.detail;
      else if (body && typeof body.detail === 'string') detail = { message: body.detail };
    } catch {
      /* 保留默认值 */
    }
    throw new ApiError(
      res.status,
      (detail.reason as string) ?? 'UNKNOWN',
      (detail.message as string) ?? res.statusText,
      detail,
    );
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  listDocuments: () =>
    request<{ documents: DocMeta[]; workspace_revision: number }>('/api/documents'),

  getDocument: (id: string) =>
    request<{ id: string; content: string; revision: number }>(
      `/api/documents/${encodeURIComponent(id)}`,
    ),

  createDocument: (id: string, content: string) =>
    request<{ id: string; revision: number }>('/api/documents', {
      method: 'POST',
      ...json({ id, content }),
    }),

  saveDocument: (id: string, content: string, baseRevision: number) =>
    request<{ id: string; revision: number }>(
      `/api/documents/${encodeURIComponent(id)}`,
      { method: 'PUT', ...json({ content, base_revision: baseRevision }) },
    ),

  deleteDocument: (id: string) =>
    request<{ id: string }>(`/api/documents/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  renamePreview: (docId: string, line: number, col: number, newName: string) =>
    request<RenamePlan>('/api/rename/preview', {
      method: 'POST',
      ...json({ doc_id: docId, line, col, new_name: newName }),
    }),

  renameApply: (planId: string) =>
    request<ApplyResult>('/api/rename/apply', {
      method: 'POST',
      ...json({ plan_id: planId }),
    }),
};
