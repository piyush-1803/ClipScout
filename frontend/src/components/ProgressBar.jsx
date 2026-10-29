import React from 'react';
import { Loader2, XCircle, Sparkles } from 'lucide-react';

export default function ProgressBar({ progressEvent, onCancel }) {
  if (!progressEvent) return null;

  const { stage, progress = 0, message = 'Processing...', current_chunk, total_chunks } = progressEvent;

  const getStageTitle = (stg) => {
    switch (stg) {
      case 'fetching':
        return '1/4 Fetching Transcript';
      case 'chunking':
        return '2/4 Splitting Time Windows';
      case 'analyzing':
        return current_chunk && total_chunks
          ? `3/4 Analyzing Window ${current_chunk} of ${total_chunks}`
          : '3/4 AI Map Phase';
      case 'ranking':
        return '4/4 Deduplicating & Calibrating Scores';
      case 'done':
        return 'Analysis Complete!';
      default:
        return 'Processing...';
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto my-6 p-5 rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white/90 dark:bg-neutral-900/80 backdrop-blur-xl shadow-lg shadow-neutral-900/5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-gradient-to-tr from-amber-500 to-rose-500 text-white animate-pulse">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-xs font-semibold tracking-wide uppercase text-indigo-600 dark:text-indigo-400">
              {getStageTitle(stage)}
            </h3>
            <p className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
              {message}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-sm font-bold font-mono text-neutral-700 dark:text-neutral-300">
            {Math.round(progress)}%
          </span>
          {onCancel && stage !== 'done' && (
            <button
              onClick={onCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium text-rose-600 hover:text-rose-700 dark:text-rose-400 dark:hover:text-rose-300 bg-rose-50 hover:bg-rose-100 dark:bg-rose-950/40 dark:hover:bg-rose-950/60 border border-rose-200 dark:border-rose-900 transition-colors"
            >
              <XCircle className="w-3.5 h-3.5" />
              <span>Cancel</span>
            </button>
          )}
        </div>
      </div>

      {/* Progress Track */}
      <div className="w-full h-2.5 bg-neutral-100 dark:bg-neutral-800 rounded-full overflow-hidden p-0.5">
        <div
          className="h-full bg-gradient-to-r from-amber-500 via-rose-500 to-indigo-600 rounded-full transition-all duration-300 ease-out"
          style={{ width: `${Math.min(100, Math.max(5, progress))}%` }}
        />
      </div>
    </div>
  );
}
