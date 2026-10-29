import React from 'react';
import { Sparkles, Sun, Moon, Sliders, KeyRound } from 'lucide-react';

export default function Navbar({ darkMode, setDarkMode, settingsOpen, setSettingsOpen, hasKey }) {
  return (
    <header className="sticky top-0 z-40 w-full backdrop-blur-xl border-b transition-colors duration-200 border-neutral-200/80 dark:border-neutral-800/80 bg-white/80 dark:bg-neutral-950/80">
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-rose-500 to-indigo-600 flex items-center justify-center shadow-md shadow-rose-500/20 text-white">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-neutral-900 via-neutral-700 to-neutral-900 dark:from-white dark:via-neutral-200 dark:to-neutral-400 bg-clip-text text-transparent">
                ClipScout
              </span>
              <span className="text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded-full bg-rose-500/10 text-rose-500 dark:bg-rose-500/20 dark:text-rose-400">
                MVP
              </span>
            </div>
            <p className="text-xs text-neutral-500 dark:text-neutral-400 -mt-0.5">
              AI Short-Form Viral Clip Finder
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Key status indicator pill */}
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full border transition-all ${
              hasKey
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800/60'
                : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-800/60'
            }`}
            title="Configure LLM API Key"
          >
            <KeyRound className="w-3.5 h-3.5" />
            <span>{hasKey ? 'Key Configured' : 'Set API Key'}</span>
          </button>

          {/* Settings toggle button */}
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className="p-2 rounded-xl text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white hover:bg-neutral-100 dark:hover:bg-neutral-800/80 transition-colors"
            title="LLM Settings"
          >
            <Sliders className="w-4 h-4" />
          </button>

          {/* Dark/Light toggle */}
          <button
            onClick={() => setDarkMode(!darkMode)}
            className="p-2 rounded-xl text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white hover:bg-neutral-100 dark:hover:bg-neutral-800/80 transition-colors"
            title={darkMode ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
          >
            {darkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </header>
  );
}
