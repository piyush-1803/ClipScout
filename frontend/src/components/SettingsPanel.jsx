import React, { useState, useEffect } from 'react';
import { Eye, EyeOff, CheckCircle2, AlertCircle, Loader2, Sparkles, ShieldCheck, ChevronUp, RefreshCw, Cpu } from 'lucide-react';

export default function SettingsPanel({
  isOpen,
  onClose,
  provider,
  setProvider,
  apiKey,
  setApiKey,
  rememberKey,
  setRememberKey,
  model,
  setModel,
  baseUrl,
  setBaseUrl,
  targetClips,
  setTargetClips,
  language,
  setLanguage,
  backendUrl = 'http://localhost:8000'
}) {
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [availableModels, setAvailableModels] = useState([]);

  if (!isOpen) return null;

  const handleTestKey = async () => {
    if (!apiKey) {
      setTestResult({ success: false, message: 'Please enter an API key to test.' });
      return;
    }
    setTesting(true);
    setTestResult(null);

    try {
      const res = await fetch(`${backendUrl}/api/test-key`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey.trim()
        },
        body: JSON.stringify({
          provider,
          model: model.trim(),
          base_url: provider === 'openai_compat' ? baseUrl.trim() : null
        })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Connection test failed');
      }

      setTestResult({
        success: data.success,
        message: data.message || 'Key verified successfully!'
      });
      if (data.model && data.model !== 'auto') {
        setModel(data.model);
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err.message || 'Failed to connect to provider.'
      });
    } finally {
      setTesting(false);
    }
  };

  const handleFetchModels = async () => {
    setFetchingModels(true);
    try {
      const res = await fetch(`${backendUrl}/api/list-models`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey ? apiKey.trim() : ''
        },
        body: JSON.stringify({
          provider,
          base_url: provider === 'openai_compat' ? baseUrl.trim() : null
        })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.models && data.models.length > 0) {
          setAvailableModels(data.models);
        }
      }
    } catch (e) {
      console.error('Could not auto-fetch models:', e);
    } finally {
      setFetchingModels(false);
    }
  };

  const handleProviderChange = (e) => {
    const nextProvider = e.target.value;
    setProvider(nextProvider);
    setTestResult(null);
    setAvailableModels([]);
    if (nextProvider === 'gemini') {
      setModel('auto');
    } else {
      setModel('llama-3.3-70b-versatile');
      if (!baseUrl) setBaseUrl('https://api.groq.com/openai/v1');
    }
  };

  const geminiPresets = [
    { id: 'auto', label: '✨ Auto-Detect (Recommended)' },
    { id: 'gemini-1.5-flash', label: '🚀 1.5 Flash (Standard)' },
    { id: 'gemini-2.0-flash', label: '🔥 2.0 Flash' },
    { id: 'gemini-2.0-flash-exp', label: '⚡ 2.0 Flash Exp' },
    { id: 'gemini-1.5-pro', label: '🧠 1.5 Pro' },
  ];

  const openaiPresets = [
    { id: 'llama-3.3-70b-versatile', label: '🦙 Llama 3.3 70B' },
    { id: 'deepseek-r1-distill-llama-70b', label: '🐋 DeepSeek R1' },
    { id: 'gpt-4o', label: '🟢 GPT-4o' },
    { id: 'gpt-4o-mini', label: '⚡ GPT-4o Mini' },
  ];

  const currentPresets = provider === 'gemini' ? geminiPresets : openaiPresets;

  return (
    <div className="mb-8 rounded-2xl border transition-all duration-200 border-neutral-200/80 dark:border-neutral-800/80 bg-neutral-50/80 dark:bg-neutral-900/60 p-6 backdrop-blur-xl shadow-lg shadow-neutral-900/5">
      <div className="flex items-center justify-between pb-4 mb-4 border-b border-neutral-200 dark:border-neutral-800">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-2">
              <span>Provider &amp; Model Intelligence</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-mono font-medium">
                Plug &amp; Play
              </span>
            </h2>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              Complete model flexibility: choose the latest releases or type any custom model ID.
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white p-1 rounded-lg hover:bg-neutral-200/50 dark:hover:bg-neutral-800 transition-colors"
        >
          <ChevronUp className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Provider selection */}
        <div>
          <label className="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
            LLM Provider
          </label>
          <select
            value={provider}
            onChange={handleProviderChange}
            className="w-full text-sm px-3.5 py-2.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800/90 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          >
            <option value="gemini">Google Gemini (Free-Tier, Fast)</option>
            <option value="openai_compat">OpenAI-Compatible (Groq, OpenRouter, DeepSeek, Ollama)</option>
          </select>
          <p className="mt-1 text-[11px] text-neutral-500 dark:text-neutral-400">
            {provider === 'gemini'
              ? 'Works with any active Gemini model (2.0 Flash, 2.0 Flash Exp, 1.5 Flash, etc.)'
              : 'Works with any OpenAI-compatible base URL (Groq, OpenRouter, local vLLM/Ollama)'}
          </p>
        </div>

        {/* Model Selector with Auto-Detect & Presets */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-neutral-700 dark:text-neutral-300 flex items-center gap-1">
              <Cpu className="w-3.5 h-3.5 text-indigo-500" />
              <span>Model ID (Fully Plug &amp; Play)</span>
            </label>
            <button
              type="button"
              onClick={handleFetchModels}
              disabled={fetchingModels}
              className="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1 cursor-pointer"
              title="Detect live models available on this API key"
            >
              {fetchingModels ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              <span>{availableModels.length > 0 ? `Loaded (${availableModels.length})` : 'Detect Models'}</span>
            </button>
          </div>

          {/* Quick preset buttons */}
          <div className="flex flex-wrap gap-1.5 mb-2">
            {currentPresets.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setModel(p.id)}
                className={`text-[10px] px-2 py-1 rounded-lg border transition-all ${
                  model === p.id
                    ? 'bg-indigo-600 text-white border-indigo-600 font-semibold shadow-sm'
                    : 'bg-white dark:bg-neutral-800 text-neutral-700 dark:text-neutral-300 border-neutral-300 dark:border-neutral-700 hover:border-indigo-400'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Live detected models dropdown if available */}
          {availableModels.length > 0 && (
            <select
              value={availableModels.some((m) => m.id === model) ? model : ''}
              onChange={(e) => {
                if (e.target.value) setModel(e.target.value);
              }}
              className="w-full mb-2 text-xs px-3 py-1.5 rounded-xl border border-indigo-200 dark:border-indigo-800/80 bg-indigo-50/50 dark:bg-indigo-950/30 text-indigo-900 dark:text-indigo-200 focus:outline-none"
            >
              <option value="">Select from detected models on your key...</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name || m.id}
                </option>
              ))}
            </select>
          )}

          {/* Direct Editable Model Input */}
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder={provider === 'gemini' ? 'auto (recommended) or gemini-1.5-flash' : 'llama-3.3-70b-versatile'}
            className="w-full text-sm px-3.5 py-2.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800/90 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 font-mono"
          />
          <p className="mt-1 text-[11px] text-neutral-500 dark:text-neutral-400">
            {provider === 'gemini'
              ? 'Leave as "auto" for automatic detection, or pick any model active on your key.'
              : 'Type or paste any model identifier supported by your OpenAI-compatible endpoint.'}
          </p>
        </div>

        {/* Base URL (only for OpenAI-compatible) */}
        {provider === 'openai_compat' && (
          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
              API Base URL
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.groq.com/openai/v1"
              className="w-full text-sm px-3.5 py-2.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800/90 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 font-mono"
            />
          </div>
        )}

        {/* API Key */}
        <div className="md:col-span-2">
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
              {provider === 'gemini' ? 'Gemini API Key' : 'Provider API Key'}
            </label>
            <a
              href={provider === 'gemini' ? 'https://aistudio.google.com/app/apikey' : 'https://console.groq.com/keys'}
              target="_blank"
              rel="noreferrer"
              className="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Get a free API key &rarr;
            </a>
          </div>
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                setTestResult(null);
              }}
              placeholder={provider === 'gemini' ? 'AIzaSy...' : 'gsk_... or sk-...'}
              className="w-full text-sm px-3.5 py-2.5 pr-24 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800/90 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 font-mono"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="p-1.5 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700/50"
                title={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
              <button
                type="button"
                onClick={handleTestKey}
                disabled={testing || !apiKey}
                className="px-2.5 py-1 text-xs font-medium rounded-lg bg-neutral-900 hover:bg-neutral-800 dark:bg-neutral-100 dark:hover:bg-white text-white dark:text-neutral-900 disabled:opacity-40 transition-opacity flex items-center gap-1"
              >
                {testing && <Loader2 className="w-3 h-3 animate-spin" />}
                <span>Test</span>
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between mt-2">
            <label className="flex items-center gap-2 cursor-pointer select-none text-xs text-neutral-600 dark:text-neutral-400">
              <input
                type="checkbox"
                checked={rememberKey}
                onChange={(e) => setRememberKey(e.target.checked)}
                className="rounded border-neutral-300 dark:border-neutral-700 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
              />
              <span>Remember key in this browser (localStorage)</span>
            </label>
            <div className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Backend never logs or stores keys</span>
            </div>
          </div>

          {testResult && (
            <div
              className={`mt-3 p-2.5 rounded-xl text-xs flex items-start gap-2 border ${
                testResult.success
                  ? 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/60'
                  : testResult.message.includes('429') || testResult.message.includes('rate limit')
                  ? 'bg-amber-50 text-amber-900 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-800/60'
                  : 'bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800/60'
              }`}
            >
              {testResult.success ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
              ) : testResult.message.includes('429') || testResult.message.includes('rate limit') ? (
                <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 leading-relaxed">
                <span className="font-medium">{testResult.message}</span>
              </div>
            </div>
          )}
        </div>

        {/* Target Clips & Output Language */}
        <div>
          <label className="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
            Target Number of Clips: <span className="font-bold text-indigo-600 dark:text-indigo-400">{targetClips}</span>
          </label>
          <input
            type="range"
            min="3"
            max="20"
            value={targetClips}
            onChange={(e) => setTargetClips(parseInt(e.target.value, 10))}
            className="w-full accent-indigo-600 cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-neutral-400 mt-0.5">
            <span>3 clips</span>
            <span>10 (standard)</span>
            <span>20 clips</span>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-neutral-700 dark:text-neutral-300 mb-1.5">
            Output Language (SEO &amp; Titles)
          </label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full text-sm px-3.5 py-2.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800/90 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          >
            <option value="same as transcript">Auto (Same as Transcript Language)</option>
            <option value="English">English</option>
            <option value="Spanish">Spanish</option>
            <option value="French">French</option>
            <option value="German">German</option>
            <option value="Portuguese">Portuguese</option>
            <option value="Hindi">Hindi</option>
            <option value="Japanese">Japanese</option>
          </select>
        </div>
      </div>
    </div>
  );
}
