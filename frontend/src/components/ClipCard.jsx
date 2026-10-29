import React, { useState } from 'react';
import {
  Play,
  Copy,
  Check,
  Quote,
  Tag,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Download,
  Loader2,
  ShieldCheck,
  Zap,
  Volume2,
  Video,
  Flame,
  Sliders,
  Settings2
} from 'lucide-react';

export default function ClipCard({
  clip,
  onPreview,
  isSelected = false,
  onToggleSelect,
  onDownload,
  isDownloading = false,
  onRenderShort,
  isRenderingShort = false,
  renderedShort = null,
  onViewShort
}) {
  const [copiedField, setCopiedField] = useState(null);
  const [seoExpanded, setSeoExpanded] = useState(false);
  const [policyExpanded, setPolicyExpanded] = useState(false);
  const [studioDrawerOpen, setStudioDrawerOpen] = useState(false);

  // Render Studio Customization Options
  const [captionStyle, setCaptionStyle] = useState('creator_classic');
  const [renderLang, setRenderLang] = useState('auto');
  const [qualityPreset, setQualityPreset] = useState('final');
  const [dynamicZoom, setDynamicZoom] = useState(true);
  const [creditOverlay, setCreditOverlay] = useState(true);
  const [debugMode, setDebugMode] = useState(false);

  const copyToClipboard = (text, fieldName) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handleStartRender = () => {
    if (onRenderShort) {
      onRenderShort(clip, {
        caption_style: captionStyle,
        language: renderLang,
        quality_preset: qualityPreset,
        dynamic_zoom: dynamicZoom,
        credit_overlay: creditOverlay,
        debug_mode: debugMode
      });
    }
  };

  // Color mappings based on virality score
  const getScoreColor = (score) => {
    if (score >= 80) return { stroke: '#10b981', bg: 'bg-emerald-500/10', text: 'text-emerald-500', border: 'border-emerald-500/30' };
    if (score >= 65) return { stroke: '#3b82f6', bg: 'bg-blue-500/10', text: 'text-blue-500', border: 'border-blue-500/30' };
    if (score >= 50) return { stroke: '#f59e0b', bg: 'bg-amber-500/10', text: 'text-amber-500', border: 'border-amber-500/30' };
    return { stroke: '#ef4444', bg: 'bg-rose-500/10', text: 'text-rose-500', border: 'border-rose-500/30' };
  };

  const colors = getScoreColor(clip.virality_score);
  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (clip.virality_score / 100) * circumference;

  const subScoreItems = [
    { label: 'Hook (30%)', value: clip.sub_scores.hook_strength },
    { label: 'Emotion (20%)', value: clip.sub_scores.emotional_intensity },
    { label: 'Novelty (20%)', value: clip.sub_scores.insight_or_novelty },
    { label: 'Shareability (15%)', value: clip.sub_scores.shareability },
    { label: 'Clarity (10%)', value: clip.sub_scores.standalone_clarity },
    { label: 'Pacing (5%)', value: clip.sub_scores.retention_pacing },
  ];

  return (
    <div className={`rounded-2xl border transition-all duration-300 p-5 sm:p-6 flex flex-col gap-4 backdrop-blur-xl ${
      isSelected
        ? 'border-rose-500/60 bg-rose-50/20 dark:bg-rose-950/20 shadow-lg shadow-rose-500/5'
        : 'border-neutral-200/90 dark:border-neutral-800/80 bg-white dark:bg-neutral-900/70 shadow-md hover:shadow-xl'
    }`}>
      {/* Top Bar: Select Checkbox, Rank, Title, Score Gauge */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className="flex items-center gap-2 shrink-0 pt-0.5">
            <input
              type="checkbox"
              checked={isSelected}
              onChange={onToggleSelect}
              className="w-4 h-4 rounded border-neutral-300 dark:border-neutral-700 text-rose-600 focus:ring-rose-500 cursor-pointer"
              title="Select clip for batch operations"
            />
            <span className="w-8 h-8 rounded-xl bg-neutral-100 dark:bg-neutral-800 text-neutral-800 dark:text-neutral-200 font-bold text-sm flex items-center justify-center border border-neutral-200 dark:border-neutral-700">
              #{clip.rank}
            </span>
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${colors.bg} ${colors.text} ${colors.border}`}>
                {clip.score_label}
              </span>

              {clip.is_most_replayed && (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-gradient-to-r from-rose-500 to-amber-500 text-white shadow-sm shadow-rose-500/25">
                  <Flame className="w-3 h-3" />
                  <span>Most Replayed</span>
                  {clip.replay_peak && <span className="opacity-95 font-mono">({Math.round(clip.replay_peak * 100)}%)</span>}
                </span>
              )}

              <span className="text-xs font-mono font-medium text-neutral-500 dark:text-neutral-400">
                {clip.start_formatted} &ndash; {clip.end_formatted}
              </span>
              <span className="text-xs px-2 py-0.5 rounded-md bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400 font-mono">
                {clip.duration}s
              </span>
            </div>
            <h3 className="text-base sm:text-lg font-bold text-neutral-900 dark:text-white leading-tight">
              {clip.seo.title}
            </h3>
          </div>
        </div>

        {/* Circular Virality Gauge */}
        <div className="shrink-0 flex flex-col items-center">
          <div className="relative w-16 h-16 flex items-center justify-center">
            <svg className="w-16 h-16 transform -rotate-90">
              <circle
                cx="32"
                cy="32"
                r={radius}
                className="stroke-neutral-200 dark:stroke-neutral-800"
                strokeWidth="4"
                fill="transparent"
              />
              <circle
                cx="32"
                cy="32"
                r={radius}
                stroke={colors.stroke}
                strokeWidth="4"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="transparent"
                className="transition-all duration-1000 ease-out"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-base font-extrabold text-neutral-900 dark:text-white leading-none">
                {Math.round(clip.virality_score)}
              </span>
              <span className="text-[9px] uppercase tracking-wider text-neutral-400 mt-0.5">Score</span>
            </div>
          </div>
        </div>
      </div>

      {/* Hook Line Callout */}
      {clip.hook_line && (
        <div className="p-3 rounded-xl bg-neutral-50 dark:bg-neutral-950/50 border border-neutral-200/70 dark:border-neutral-800/70 flex items-start gap-2.5">
          <Quote className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <span className="text-[10px] font-bold uppercase tracking-wider text-neutral-400 block mb-0.5">Hook Opening</span>
            <p className="text-xs italic text-neutral-700 dark:text-neutral-300 font-medium leading-relaxed">
              &ldquo;{clip.hook_line}&rdquo;
            </p>
          </div>
        </div>
      )}

      {/* Editorial Reasoning */}
      <p className="text-xs text-neutral-600 dark:text-neutral-400 leading-relaxed">
        {clip.reasoning}
      </p>

      {/* Sub-Score Breakdown Bars */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 pt-2 border-t border-neutral-100 dark:border-neutral-800/60">
        {subScoreItems.map((item, idx) => (
          <div key={idx} className="space-y-1">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-neutral-500 dark:text-neutral-400 font-medium">{item.label}</span>
              <span className="font-mono font-semibold text-neutral-700 dark:text-neutral-300">
                {Math.round(item.value)}
              </span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-neutral-100 dark:bg-neutral-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-rose-500 to-indigo-500 transition-all duration-500"
                style={{ width: `${Math.min(100, Math.max(0, item.value))}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Studio Render Customization Drawer (Collapsible) */}
      <div className="rounded-xl border border-neutral-200/80 dark:border-neutral-800/80 bg-neutral-50/80 dark:bg-neutral-950/40 overflow-hidden">
        <button
          onClick={() => setStudioDrawerOpen(!studioDrawerOpen)}
          className="w-full p-2.5 flex items-center justify-between text-xs font-semibold text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-900/60 transition-colors"
        >
          <span className="flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400">
            <Sliders className="w-3.5 h-3.5" />
            <span>9:16 Render Studio Settings</span>
          </span>
          <span className="flex items-center gap-1 text-[11px] text-neutral-400">
            <span>{captionStyle === 'creator_classic' ? 'Creator Classic' : captionStyle === 'active_word_pop' ? 'Word Pop' : 'Clean Outline'}</span>
            {studioDrawerOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </span>
        </button>

        {studioDrawerOpen && (
          <div className="p-3.5 pt-1 space-y-3 border-t border-neutral-200/60 dark:border-neutral-800/60 text-xs">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Caption Style */}
              <div>
                <label className="block text-[11px] font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                  Subtitles Style Preset
                </label>
                <select
                  value={captionStyle}
                  onChange={(e) => setCaptionStyle(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 text-xs text-neutral-800 dark:text-neutral-200 focus:outline-none"
                >
                  <option value="creator_classic">Creator Classic (Yellow on Red Box)</option>
                  <option value="active_word_pop">Active Word Pop (Yellow Spoken Word)</option>
                  <option value="clean_outline">Clean Outline (White + Black Shadow)</option>
                </select>
              </div>

              {/* Language */}
              <div>
                <label className="block text-[11px] font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                  Transcription &amp; Subtitle Script
                </label>
                <select
                  value={renderLang}
                  onChange={(e) => setRenderLang(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 text-xs text-neutral-800 dark:text-neutral-200 focus:outline-none"
                >
                  <option value="auto">Auto-Detect Audio</option>
                  <option value="en">English (Roman)</option>
                  <option value="hinglish">Hinglish (Hindi spoken in Roman letters)</option>
                  <option value="hi">Hindi (Devanagari script)</option>
                </select>
              </div>

              {/* Quality Preset */}
              <div>
                <label className="block text-[11px] font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                  Export Quality Preset
                </label>
                <select
                  value={qualityPreset}
                  onChange={(e) => setQualityPreset(e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 text-xs text-neutral-800 dark:text-neutral-200 focus:outline-none"
                >
                  <option value="final">Final Master (1080x1920 60fps 20 Mbps, loudnorm)</option>
                  <option value="preview">Fast Preview (720x1280 30fps fast)</option>
                </select>
              </div>

              {/* Toggles */}
              <div className="flex flex-col gap-1.5 justify-center pt-1">
                <label className="flex items-center gap-2 cursor-pointer text-[11px] text-neutral-700 dark:text-neutral-300">
                  <input
                    type="checkbox"
                    checked={dynamicZoom}
                    onChange={(e) => setDynamicZoom(e.target.checked)}
                    className="w-3.5 h-3.5 rounded text-indigo-600"
                  />
                  <span>Solo Dynamic Zoom Cuts (1.08x &harr; 1.24x)</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer text-[11px] text-neutral-700 dark:text-neutral-300">
                  <input
                    type="checkbox"
                    checked={creditOverlay}
                    onChange={(e) => setCreditOverlay(e.target.checked)}
                    className="w-3.5 h-3.5 rounded text-indigo-600"
                  />
                  <span>Safe-Zone Creator Attribution Banner</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer text-[11px] text-neutral-700 dark:text-neutral-300">
                  <input
                    type="checkbox"
                    checked={debugMode}
                    onChange={(e) => setDebugMode(e.target.checked)}
                    className="w-3.5 h-3.5 rounded text-indigo-600"
                  />
                  <span>Generate Debug Video (Face Boxes &amp; Speaker Meters)</span>
                </label>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Action Buttons Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-neutral-100 dark:border-neutral-800">
        <div className="flex items-center gap-2">
          {/* Preview Raw Video */}
          <button
            onClick={() => onPreview(clip)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-xs font-semibold text-neutral-700 dark:text-neutral-200 hover:border-neutral-300 dark:hover:border-neutral-600 transition-colors shadow-sm"
          >
            <Play className="w-3.5 h-3.5 text-rose-500" />
            <span>Preview Source</span>
          </button>

          {/* Download Raw Segment */}
          <button
            onClick={() => onDownload(clip)}
            disabled={isDownloading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-xs font-semibold text-neutral-700 dark:text-neutral-200 hover:border-neutral-300 dark:hover:border-neutral-600 transition-colors shadow-sm disabled:opacity-50"
          >
            {isDownloading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-rose-500" />
            ) : (
              <Download className="w-3.5 h-3.5 text-neutral-500" />
            )}
            <span>{isDownloading ? 'Cutting...' : 'Download MP4'}</span>
          </button>

          {/* Render 9:16 Short Button */}
          {renderedShort ? (
            <button
              onClick={() => onViewShort(renderedShort)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold shadow-md shadow-emerald-600/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
            >
              <Video className="w-3.5 h-3.5" />
              <span>View 9:16 Short</span>
            </button>
          ) : (
            <button
              onClick={handleStartRender}
              disabled={isRenderingShort}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-rose-600 via-pink-600 to-indigo-600 hover:from-rose-500 hover:to-indigo-500 text-white text-xs font-bold shadow-md shadow-rose-600/20 transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
            >
              {isRenderingShort ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Rendering Short...</span>
                </>
              ) : (
                <>
                  <Video className="w-3.5 h-3.5" />
                  <span>Render 9:16 Short</span>
                </>
              )}
            </button>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* YouTube Compliance Toggle */}
          <button
            onClick={() => setPolicyExpanded(!policyExpanded)}
            className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400 hover:underline transition-colors"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Policy Compliance</span>
            {policyExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>

          {/* SEO Metadata Toggle */}
          <button
            onClick={() => setSeoExpanded(!seoExpanded)}
            className="inline-flex items-center gap-1 text-xs font-medium text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white transition-colors"
          >
            <span>SEO Metadata</span>
            {seoExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* Collapsible YouTube Policy & Fair Use Info */}
      {policyExpanded && (
        <div className="p-3.5 rounded-xl bg-emerald-50/60 dark:bg-emerald-950/20 border border-emerald-200/70 dark:border-emerald-800/40 text-xs space-y-1.5 animate-in fade-in duration-200">
          <div className="flex items-center gap-1.5 font-bold text-emerald-800 dark:text-emerald-300 mb-1">
            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>YouTube Reused Content &amp; Fair Use Safe Harbor</span>
          </div>
          <p className="text-[11px] text-emerald-700 dark:text-emerald-400 leading-relaxed">
            YouTube strictly flags raw podcast rips as "Reused Content". When you click <strong>"Render 9:16 Short"</strong>, ClipScout automatically applies creator-grade transformative editing:
          </p>
          <ul className="list-disc list-inside text-[11px] text-neutral-700 dark:text-neutral-300 space-y-0.5">
            <li><strong>Speaker-Aware Hard Cuts:</strong> YuNet tracking + mouth motion VAD switches between speakers VN-style.</li>
            <li><strong>Finish-the-Thought Trim:</strong> Word timestamp audio analysis extends cuts so thoughts never end mid-word.</li>
            <li><strong>High-Visibility ASS Subtitles:</strong> Animated bold typography placed in the upper safe-zone.</li>
            <li><strong>Original Creator Attribution:</strong> Clean attribution banner burned for the first 6 seconds.</li>
            <li><strong>Loudnorm Mastered Export:</strong> Broadcast-compliant audio mastered to -14 LUFS.</li>
          </ul>
        </div>
      )}

      {/* Collapsible SEO Block */}
      {seoExpanded && (
        <div className="mt-2 p-4 rounded-xl bg-neutral-50 dark:bg-neutral-950/60 border border-neutral-200/80 dark:border-neutral-800/80 space-y-3 animate-in fade-in duration-200">
          <div className="flex items-center justify-between pb-2 border-b border-neutral-200 dark:border-neutral-800">
            <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Distribution &amp; Fair Use Metadata</span>
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-mono font-medium">
              SEO Score: {Math.round(clip.seo.seo_score || 80)}/100
            </span>
          </div>

          {/* Title */}
          <div>
            <div className="flex items-center justify-between text-xs text-neutral-500 mb-1">
              <span>Optimized Title (&le; 60 chars)</span>
              <button
                onClick={() => copyToClipboard(clip.seo.title, 'title')}
                className="hover:text-indigo-600 flex items-center gap-1"
              >
                {copiedField === 'title' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                <span>{copiedField === 'title' ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
            <p className="text-xs font-medium text-neutral-800 dark:text-neutral-200 bg-white dark:bg-neutral-900 p-2 rounded-lg border border-neutral-200 dark:border-neutral-800">
              {clip.seo.title}
            </p>
          </div>

          {/* Description */}
          <div>
            <div className="flex items-center justify-between text-xs text-neutral-500 mb-1">
              <span>Short Video Description</span>
              <button
                onClick={() => copyToClipboard(clip.seo.description, 'desc')}
                className="hover:text-indigo-600 flex items-center gap-1"
              >
                {copiedField === 'desc' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                <span>{copiedField === 'desc' ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
            <p className="text-xs text-neutral-700 dark:text-neutral-300 bg-white dark:bg-neutral-900 p-2 rounded-lg border border-neutral-200 dark:border-neutral-800">
              {clip.seo.description}
            </p>
          </div>

          {/* Hashtags */}
          {clip.seo.hashtags && clip.seo.hashtags.length > 0 && (
            <div>
              <div className="flex items-center justify-between text-xs text-neutral-500 mb-1">
                <span>Hashtags ({clip.seo.hashtags.length})</span>
                <button
                  onClick={() => copyToClipboard(clip.seo.hashtags.join(' '), 'hashtags')}
                  className="hover:text-indigo-600 flex items-center gap-1"
                >
                  {copiedField === 'hashtags' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                  <span>{copiedField === 'hashtags' ? 'Copied' : 'Copy All'}</span>
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {clip.seo.hashtags.map((tag, i) => (
                  <span
                    key={i}
                    className="text-[11px] px-2 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800/50"
                  >
                    {tag.startsWith('#') ? tag : `#${tag}`}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}