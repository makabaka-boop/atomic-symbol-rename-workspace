import React from 'react';
import { createRoot } from 'react-dom/client';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import App from './App';
import './styles.css';

self.MonacoEnvironment = { getWorker: () => new editorWorker() };

monaco.languages.register({ id: 'mini-lang' });
monaco.languages.setMonarchTokensProvider('mini-lang', {
  tokenizer: {
    root: [
      [/#.*$/, 'comment'],
      [/\b(def|use)\b/, 'keyword'],
      [/[A-Za-z_][A-Za-z0-9_]*/, 'identifier'],
    ],
  },
});

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
