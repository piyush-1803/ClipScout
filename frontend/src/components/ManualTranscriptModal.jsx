import React, { useState } from 'react';
import { X, FileText, Upload, Sparkles } from 'lucide-react';

export default function ManualTranscriptModal({ isOpen, onClose, onSubmit, isSubmitting }) {
  const [manualText, setManualText] = useState('');
  const [fileName, setFileName] = useState('');

  if (!isOpen) return null;

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (event) => {
      setManualText(event.target.result || '');
    };
    reader.readAsText(file);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!manualText.trim()) return;
    onSubmit(manualText);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-xl rounded-2xl bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-2xl p-6">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-neutral-200 dark:border-neutral-800">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-neutral-900 dark:text-white">
                Provide Manual Transcript
              </h3>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                Paste transcript text with [mm:ss] tags or upload an .srt / .vtt file
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-neutral-400 hover:text-neutral-600 dark:hover:text-white rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-semibold text-neutral-700 dark:text-neutral-300">
                Transcript Content
              </label>
              <label className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:underline cursor-pointer flex items-center gap-1">
                <Upload className="w-3.5 h-3.5" />
                <span>{fileName ? `Loaded: ${fileName}` : 'Upload .srt / .vtt'}</span>
                <input
                  type="file"
                  accept=".srt,.vtt,.txt"
                  className="hidden"
                  onChange={handleFileUpload}
                />
              </label>
            </div>

            <textarea
              rows={10}
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              placeholder={`Example formats accepted:

[00:15] Welcome to today's episode where we break down viral retention.
[00:25] The single most important hook strategy is curiosity loops.

Or paste complete SRT / WebVTT subtitles directly here.`}
              className="w-full text-xs font-mono p-3 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 resize-none"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !manualText.trim()}
              className="px-5 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white shadow-md shadow-indigo-600/20 transition-all"
            >
              {isSubmitting ? 'Processing...' : 'Use This Transcript'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
