import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Sparkles,
  Search,
  SlidersHorizontal,
  Download,
  Copy,
  Check,
  RotateCcw,
  AlertCircle,
  FileText,
  Sliders,
  ExternalLink,
  ChevronDown,
  Loader2,
  CheckSquare,
  Square,
  Package,
  Zap,
  ShieldCheck,
  X
} from 'lucide-react';

import Navbar from './components/Navbar';
import SettingsPanel from './components/SettingsPanel';
import ProgressBar from './components/ProgressBar';
import VideoHeader from './components/VideoHeader';
import ClipCard from './components/ClipCard';
import YouTubePreviewModal from './components/YouTubePreviewModal';
import ShortsPreviewModal from './components/ShortsPreviewModal';
import ManualTranscriptModal from './components/ManualTranscriptModal';

const BACKEND_URL = 'http://localhost:8000';

export default function App() {
  // Theme state
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('clipscout_theme');
    return saved !== null ? saved === 'dark' : true;
  });

  // Settings state
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [provider, setProvider] = useState('gemini');
  const [model, setModel] = useState(() => {
    const saved = localStorage.getItem('clipscout_model');
    if (!saved || saved === 'gemini-2.5-flash' || saved === 'gemini-2.0-flash') return 'auto';
    return saved;
  });
  const [baseUrl, setBaseUrl] = useState('https://api.groq.com/openai/v1');
  const [rememberKey, setRememberKey] = useState(() => {
    return localStorage.getItem('clipscout_remember_key') === 'true';
  });
  const [apiKey, setApiKey] = useState(() => {
    if (localStorage.getItem('clipscout_remember_key') === 'true') {
      return localStorage.getItem('clipscout_api_key') || '';
    }
    return '';
  });
  const [targetClips, setTargetClips] = useState(10);
  const [language, setLanguage] = useState('same as transcript');

  // Input & analysis state
  const [videoUrl, setVideoUrl] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [progressEvent, setProgressEvent] = useState(null);
  const [videoMetadata, setVideoMetadata] = useState(null);
  const [transcriptSegments, setTranscriptSegments] = useState([]);
  const [clips, setClips] = useState([]);
  const [errorState, setErrorState] = useState(null);

  // Selection & Download state
  const [selectedClipKeys, setSelectedClipKeys] = useState(new Set());
  const [downloadingClipKey, setDownloadingClipKey] = useState(null);
  const [isBatchDownloading, setIsBatchDownloading] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState(null);

  // 9:16 Shorts Rendering state
  const [renderedShortsMap, setRenderedShortsMap] = useState({});
  const [renderingClipKey, setRenderingClipKey] = useState(null);
  const [isBatchRenderingShorts, setIsBatchRenderingShorts] = useState(false);
  const [activeShortModal, setActiveShortModal] = useState(null);
  const [activeRenderJob, setActiveRenderJob] = useState(null);
  const activeEventSourceRef = useRef(null);
  const [systemCaps, setSystemCaps] = useState(null);
  const [systemWarning, setSystemWarning] = useState(null);

  // Check system capabilities on mount
  useEffect(() => {
    fetch(`${BACKEND_URL}/api/system-check`)
      .then((r) => r.json())
      .then((data) => {
        setSystemCaps(data);
        if (!data.ffmpeg_found || !data.libass_available) {
          setSystemWarning(
            'Full Gyan.FFmpeg build with libass is required for creator-grade dynamic captions. Run "winget install Gyan.FFmpeg" in PowerShell, then restart.'
          );
        }
      })
      .catch(() => {});
  }, []);

  // Filter & Sort state
  const [sortBy, setSortBy] = useState('virality'); // 'virality' | 'seo' | 'time'
  const [minScore, setMinScore] = useState(0);
  const [copiedAll, setCopiedAll] = useState(false);

  // Modals
  const [previewClip, setPreviewClip] = useState(null);
  const [manualTranscriptModalOpen, setManualTranscriptModalOpen] = useState(false);
  const [manualTranscriptData, setManualTranscriptData] = useState(null);

  const abortControllerRef = useRef(null);

  // Apply dark mode class to root
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('clipscout_theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('clipscout_theme', 'light');
    }
  }, [darkMode]);

  // Handle remember key and model updates
  useEffect(() => {
    localStorage.setItem('clipscout_remember_key', String(rememberKey));
    if (rememberKey) {
      localStorage.setItem('clipscout_api_key', apiKey);
    } else {
      localStorage.removeItem('clipscout_api_key');
    }
  }, [apiKey, rememberKey]);

  useEffect(() => {
    if (model) {
      localStorage.setItem('clipscout_model', model);
    }
  }, [model]);

  // Analysis trigger
  const handleStartAnalysis = async (customSegments = null) => {
    if (!videoUrl.trim()) {
      setErrorState({
        title: 'Missing YouTube URL',
        message: 'Please paste a valid YouTube video URL or Podcast link above.',
        showManual: false
      });
      return;
    }

    if (!apiKey.trim()) {
      setSettingsOpen(true);
      setErrorState({
        title: 'API Key Required',
        message: 'Please provide your free LLM API key in Settings before analyzing.',
        showManual: false
      });
      return;
    }

    setErrorState(null);
    setIsAnalyzing(true);
    setSelectedClipKeys(new Set());
    setRenderedShortsMap({});
    setProgressEvent({
      stage: 'fetching',
      progress: 3.0,
      message: 'Connecting to YouTube and transcript engine...'
    });

    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch(`${BACKEND_URL}/api/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey.trim()
        },
        body: JSON.stringify({
          video_id: '',
          url: videoUrl.trim(),
          segments: customSegments || manualTranscriptData,
          output_language: language,
          target_clips: targetClips,
          model: model.trim(),
          provider: provider,
          base_url: provider === 'openai_compat' ? baseUrl.trim() : null
        }),
        signal: abortControllerRef.current.signal
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server responded with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6);
            try {
              const event = JSON.parse(jsonStr);
              setProgressEvent(event);

              if (event.video) {
                setVideoMetadata(event.video);
              }

              if (event.stage === 'error') {
                setErrorState({
                  title: 'Analysis Failed',
                  message: event.error || event.message || 'An error occurred during analysis.',
                  showManual: (event.error || '').toLowerCase().includes('transcript')
                });
                setIsAnalyzing(false);
                return;
              }

              if (event.stage === 'done') {
                if (event.results) {
                  setClips(event.results);
                }
                setIsAnalyzing(false);
                return;
              }
            } catch (parseErr) {
              console.error('Failed to parse SSE line:', jsonStr, parseErr);
            }
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setProgressEvent(null);
      } else {
        setErrorState({
          title: 'Connection / Analysis Error',
          message: err.message || 'Failed to stream analysis from backend.',
          showManual: (err.message || '').toLowerCase().includes('transcript')
        });
      }
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsAnalyzing(false);
    setProgressEvent(null);
  };

  const handleManualTranscriptSubmit = async (transcriptText) => {
    setManualTranscriptModalOpen(false);
    setIsAnalyzing(true);
    setProgressEvent({
      stage: 'fetching',
      progress: 5.0,
      message: 'Parsing provided manual transcript...'
    });

    try {
      const res = await fetch(`${BACKEND_URL}/api/transcript`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: videoUrl.trim(),
          manual_transcript: transcriptText
        })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Could not parse manual transcript.');
      }

      setVideoMetadata(data.video);
      setManualTranscriptData(data.segments);
      setTranscriptSegments(data.segments);
      await handleStartAnalysis(data.segments);
    } catch (err) {
      setErrorState({
        title: 'Manual Transcript Parsing Failed',
        message: err.message,
        showManual: true
      });
      setIsAnalyzing(false);
      setProgressEvent(null);
    }
  };

  // Filtered & Sorted Clips
  const processedClips = useMemo(() => {
    let result = [...clips].filter((c) => c.virality_score >= minScore);

    if (sortBy === 'virality') {
      result.sort((a, b) => b.virality_score - a.virality_score);
    } else if (sortBy === 'seo') {
      result.sort((a, b) => (b.seo?.seo_score || 0) - (a.seo?.seo_score || 0));
    } else if (sortBy === 'time') {
      result.sort((a, b) => a.start - b.start);
    }

    return result;
  }, [clips, minScore, sortBy]);

  // Selection toggles
  const getClipKey = (clip) => `${clip.start}-${clip.end}`;

  const handleToggleSelect = (clip) => {
    const key = getClipKey(clip);
    setSelectedClipKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectedClipKeys.size === processedClips.length) {
      setSelectedClipKeys(new Set());
    } else {
      const allKeys = new Set(processedClips.map(getClipKey));
      setSelectedClipKeys(allKeys);
    }
  };

  // 1. Direct Single 9:16 Short Render (Streaming Studio Job)
  const handleRenderSingleShort = async (clip, options = {}) => {
    const key = getClipKey(clip);
    setRenderingClipKey(key);

    const initialJob = {
      job_id: 'pending',
      stage: 'queued',
      progress: 5,
      message: 'Submitting render job to queue...',
      clip,
      options
    };
    setActiveRenderJob(initialJob);
    setActiveShortModal({
      clip_title: clip.seo?.title || `clip_${clip.rank}`,
      duration: clip.duration,
      seo_package: clip.seo || {},
      seo_metadata: clip.seo || {}
    });

    try {
      const res = await fetch(`${BACKEND_URL}/api/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_id: videoMetadata?.video_id || '',
          clip_index: clip.rank || 1,
          clip_title: clip.seo?.title || `clip_${clip.rank}`,
          channel_name: videoMetadata?.channel || 'Creator',
          start: clip.start,
          end: clip.end,
          hook_line: clip.hook_line || '',
          seo_metadata: clip.seo ? {
            title: clip.seo.title,
            description: clip.seo.description,
            hashtags: clip.seo.hashtags,
            keywords: clip.seo.keywords,
            seo_score: clip.seo.seo_score
          } : {},
          caption_style: options.caption_style || 'creator_classic',
          language: options.language || 'auto',
          quality_preset: options.quality_preset || 'final',
          dynamic_zoom: options.dynamic_zoom !== undefined ? options.dynamic_zoom : true,
          credit_overlay: options.credit_overlay !== undefined ? options.credit_overlay : true,
          debug_mode: Boolean(options.debug_mode),
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Render submission failed: ${res.status}`);
      }

      const { job_id } = await res.json();
      setActiveRenderJob((prev) => ({ ...prev, job_id }));

      if (activeEventSourceRef.current) {
        activeEventSourceRef.current.close();
      }

      const es = new EventSource(`${BACKEND_URL}/api/render/${job_id}/events`);
      activeEventSourceRef.current = es;

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setActiveRenderJob((prev) => ({ ...prev, ...data }));

          if (data.stage === 'done') {
            es.close();
            setRenderingClipKey(null);
            const cleanSlug = (clip.seo?.title || 'clip').replace(/[^\w\s-]/g, '').trim().slice(0, 40).replace(/\s+/g, '_');
            const rankStr = String(clip.rank || 1).padStart(2, '0');
            const finishedShort = {
              job_id,
              filename: 'final.mp4',
              duration: clip.duration,
              clip_title: clip.seo?.title,
              output_files: data.outputs || {},
              seo_package: clip.seo || {},
              output_dir: `outputs/${videoMetadata?.video_id}/clip_${rankStr}_${cleanSlug}`
            };
            setRenderedShortsMap((prev) => ({ ...prev, [key]: finishedShort }));
            setActiveShortModal(finishedShort);
          } else if (data.stage === 'error') {
            es.close();
            setRenderingClipKey(null);
            alert(`Rendering failed: ${data.error || data.message}`);
          }
        } catch {}
      };

      es.onerror = () => {
        es.close();
        setRenderingClipKey(null);
      };

    } catch (err) {
      alert(`Render failed: ${err.message}`);
      setRenderingClipKey(null);
      setActiveRenderJob(null);
    }
  };

  const handleCancelRenderJob = async (job_id) => {
    if (!job_id || job_id === 'pending') return;
    try {
      await fetch(`${BACKEND_URL}/api/render/${job_id}/cancel`, { method: 'POST' });
      if (activeEventSourceRef.current) {
        activeEventSourceRef.current.close();
      }
      setActiveRenderJob(null);
      setRenderingClipKey(null);
    } catch {}
  };

  const handleRerenderClipWithNudges = ({ startNudge, endNudge }) => {
    if (!activeRenderJob?.clip) return;
    const modifiedClip = {
      ...activeRenderJob.clip,
      start: Math.max(0, activeRenderJob.clip.start + startNudge),
      end: activeRenderJob.clip.end + endNudge
    };
    handleRenderSingleShort(modifiedClip, activeRenderJob.options || {});
  };

  // 2. Batch 9:16 Shorts Render & Download (.zip)
  const handleBatchRenderShorts = async () => {
    const targetClipsToRender = selectedClipKeys.size > 0
      ? processedClips.filter((c) => selectedClipKeys.has(getClipKey(c)))
      : processedClips;

    if (targetClipsToRender.length === 0) {
      alert('No clips available to edit.');
      return;
    }

    setIsBatchRenderingShorts(true);
    setDownloadNotice(
      `Batch rendering ${targetClipsToRender.length} ready-to-publish 9:16 Shorts with FFmpeg (subtitles, audio SFX, Fair Use descriptions)...`
    );

    try {
      const res = await fetch(`${BACKEND_URL}/api/render-shorts-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_id: videoMetadata?.video_id || '',
          video_title: videoMetadata?.title || 'Podcast Highlights',
          channel_name: videoMetadata?.channel || 'Creator',
          clips: targetClipsToRender.map((c) => ({
            video_id: videoMetadata?.video_id || '',
            video_title: videoMetadata?.title || 'Podcast Highlight',
            channel_name: videoMetadata?.channel || 'Creator',
            start: c.start,
            end: c.end,
            hook_title: c.seo?.title || 'Viral Moment',
            hook_line: c.hook_line || '',
            reasoning: c.reasoning || '',
            hashtags: c.seo?.hashtags || [],
            segments: transcriptSegments || [],
            add_sfx: true
          }))
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Batch 9:16 render failed with status ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `clipscout_${videoMetadata?.video_id || 'shorts'}_ready_916_shorts_bundle.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setDownloadNotice(
        `✓ Packaged ${targetClipsToRender.length} 9:16 Shorts with METADATA_AND_DESCRIPTIONS.txt in ZIP!`
      );
      setTimeout(() => setDownloadNotice(null), 4000);
    } catch (err) {
      alert(`Batch 9:16 Shorts generation failed: ${err.message}`);
      setDownloadNotice(null);
    } finally {
      setIsBatchRenderingShorts(false);
    }
  };

  // Direct Single Raw Clip Download
  const handleDownloadSingleClip = async (clip) => {
    const key = getClipKey(clip);
    setDownloadingClipKey(key);
    setDownloadNotice(`Downloading raw clip "${clip.seo.title || 'Clip'}" (${clip.duration}s)...`);

    try {
      const res = await fetch(`${BACKEND_URL}/api/download-clip`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_id: videoMetadata?.video_id || '',
          start: clip.start,
          end: clip.end,
          title: clip.seo?.title || `clip_${clip.rank}`
        })
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Download failed with status ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const cleanTitle = (clip.seo?.title || `clip_${clip.rank}`)
        .replace(/[^\w\s-]/g, '')
        .trim()
        .slice(0, 40);
      a.download = `${cleanTitle}_${clip.start_formatted.replace(':', 'm')}s.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setDownloadNotice(`Downloaded: ${clip.seo?.title || 'Clip'}`);
      setTimeout(() => setDownloadNotice(null), 3500);
    } catch (err) {
      alert(`Clip download failed: ${err.message}`);
      setDownloadNotice(null);
    } finally {
      setDownloadingClipKey(null);
    }
  };

  // Export JSON
  const handleExportJSON = () => {
    const exportData = {
      video: videoMetadata,
      generated_at: new Date().toISOString(),
      model,
      total_clips: clips.length,
      clips
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `clipscout-${videoMetadata?.video_id || 'clips'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Export CSV
  const handleExportCSV = () => {
    const headers = [
      'Rank',
      'Title',
      'Start_Seconds',
      'End_Seconds',
      'Start_Formatted',
      'End_Formatted',
      'Duration_Seconds',
      'Virality_Score',
      'Score_Label',
      'Hook_Line',
      'Reasoning',
      'Hook_Strength',
      'Emotional_Intensity',
      'Insight_Novelty',
      'Shareability',
      'Clarity',
      'Pacing',
      'Description',
      'Hashtags',
      'Keywords'
    ];

    const rows = clips.map((c) => [
      c.rank,
      `"${(c.seo.title || '').replace(/"/g, '""')}"`,
      c.start,
      c.end,
      c.start_formatted,
      c.end_formatted,
      c.duration,
      c.virality_score,
      `"${c.score_label}"`,
      `"${(c.hook_line || '').replace(/"/g, '""')}"`,
      `"${(c.reasoning || '').replace(/"/g, '""')}"`,
      c.sub_scores.hook_strength,
      c.sub_scores.emotional_intensity,
      c.sub_scores.insight_or_novelty,
      c.sub_scores.shareability,
      c.sub_scores.standalone_clarity,
      c.sub_scores.retention_pacing,
      `"${(c.seo.description || '').replace(/"/g, '""')}"`,
      `"${(c.seo.hashtags || []).join(' ')}"`,
      `"${(c.seo.keywords || []).join(', ')}"`
    ]);

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `clipscout-${videoMetadata?.video_id || 'clips'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Copy All Metadata to Clipboard
  const handleCopyAll = () => {
    const summary = clips
      .map(
        (c) =>
          `### [${c.start_formatted} - ${c.end_formatted}] #${c.rank}: ${c.seo.title}\n` +
          `Score: ${c.virality_score}/100 (${c.score_label}) | Duration: ${c.duration}s\n` +
          `Hook: "${c.hook_line}"\n` +
          `Why: ${c.reasoning}\n` +
          `Description: ${c.seo.description}\n` +
          `Hashtags: ${(c.seo.hashtags || []).join(' ')}\n`
      )
      .join('\n---\n\n');

    navigator.clipboard.writeText(summary);
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2500);
  };

  return (
    <div className="min-h-screen transition-colors duration-200 bg-neutral-100/50 dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 flex flex-col font-sans">
      {/* Navigation Header */}
      <Navbar
        darkMode={darkMode}
        setDarkMode={setDarkMode}
        settingsOpen={settingsOpen}
        setSettingsOpen={setSettingsOpen}
        hasKey={Boolean(apiKey)}
      />

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-8">
        {/* Settings Panel (Collapsible) */}
        <SettingsPanel
          isOpen={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          provider={provider}
          setProvider={setProvider}
          apiKey={apiKey}
          setApiKey={setApiKey}
          rememberKey={rememberKey}
          setRememberKey={setRememberKey}
          model={model}
          setModel={setModel}
          baseUrl={baseUrl}
          setBaseUrl={setBaseUrl}
          targetClips={targetClips}
          setTargetClips={setTargetClips}
          language={language}
          setLanguage={setLanguage}
          backendUrl={BACKEND_URL}
        />

        {/* System Capability Warning Banner (Gyan FFmpeg + libass) */}
        {systemWarning && (
          <div className="max-w-4xl mx-auto mb-6 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-600 dark:text-amber-400 text-xs flex items-center justify-between gap-3 shadow-sm">
            <div className="flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 shrink-0 text-amber-500" />
              <span className="leading-relaxed">{systemWarning}</span>
            </div>
            <button
              onClick={() => setSystemWarning(null)}
              className="p-1 hover:text-neutral-900 dark:hover:text-white rounded-md"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Hero Section & Search Input */}
        <div className="text-center max-w-2xl mx-auto mb-8">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20 mb-3">
            <Zap className="w-3.5 h-3.5" />
            <span>AI Viral Moment Scouting + Ready-to-Publish 9:16 Shorts Studio</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-neutral-900 dark:text-white">
            Transform podcasts into ready-to-publish 9:16 Shorts.
          </h1>
          <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
            Paste a link to identify the highest-retention clips, auto-edit them into 9:16 vertical format with dynamic captions, sound effects, and YouTube Fair Use compliance.
          </p>

          {/* Search Bar Container */}
          <div
            className="mt-6 flex flex-col sm:flex-row items-center gap-2.5 max-w-xl mx-auto"
          >
            <div className="relative w-full">
              <input
                type="text"
                value={videoUrl}
                onChange={(e) => setVideoUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleStartAnalysis();
                  }
                }}
                placeholder="Paste YouTube URL (watch, youtu.be, shorts, or live)..."
                disabled={isAnalyzing}
                className="w-full text-sm px-4 py-3.5 pl-11 rounded-2xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900/90 text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-rose-500/40 shadow-sm"
              />
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-400" />
            </div>

            <button
              type="button"
              onClick={() => handleStartAnalysis()}
              disabled={isAnalyzing || !videoUrl}
              className="w-full sm:w-auto px-6 py-3.5 rounded-2xl bg-gradient-to-r from-rose-600 to-indigo-600 hover:from-rose-500 hover:to-indigo-500 text-white font-semibold text-sm shadow-md shadow-rose-600/20 disabled:opacity-50 transition-all shrink-0 flex items-center justify-center gap-2 cursor-pointer"
            >
              <Sparkles className="w-4 h-4" />
              <span>{isAnalyzing ? 'Scouting...' : 'Analyze'}</span>
            </button>
          </div>

          {/* Key shortcut reminder */}
          {!apiKey && (
            <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-2">
              ⚠️ Remember to click <span className="font-semibold underline cursor-pointer" onClick={() => setSettingsOpen(true)}>Set API Key</span> to add your free Gemini key.
            </p>
          )}
        </div>

        {/* Download notification banner */}
        {downloadNotice && (
          <div className="max-w-2xl mx-auto mb-6 p-3 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-800 text-indigo-900 dark:text-indigo-200 text-xs flex items-center gap-2 animate-in fade-in duration-200 shadow-md">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-600 shrink-0" />
            <span className="font-medium">{downloadNotice}</span>
          </div>
        )}

        {/* Live SSE Progress Bar */}
        {isAnalyzing && (
          <ProgressBar progressEvent={progressEvent} onCancel={handleCancel} />
        )}

        {/* Error Alert Box */}
        {errorState && (
          <div className="max-w-2xl mx-auto my-6 p-4 rounded-2xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 text-rose-900 dark:text-rose-200 flex flex-col sm:flex-row items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-semibold">{errorState.title}</h4>
              <p className="text-xs text-rose-700 dark:text-rose-300 mt-1 leading-relaxed">
                {errorState.message}
              </p>
              {errorState.showManual && (
                <button
                  onClick={() => setManualTranscriptModalOpen(true)}
                  className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white shadow-sm"
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>Paste Manual Transcript or Upload .SRT</span>
                </button>
              )}
              {errorState.message && errorState.message.toLowerCase().includes('429') && (
                <button
                  onClick={() => setSettingsOpen(true)}
                  className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-amber-600 hover:bg-amber-500 text-white shadow-sm"
                >
                  <Cpu className="w-3.5 h-3.5" />
                  <span>Open Settings to switch model or provider</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* Results Area */}
        {clips.length > 0 && (
          <div className="mt-8 animate-in fade-in duration-300">
            {/* Video Header metadata with Heatmap Sparkline */}
            <VideoHeader video={videoMetadata} totalClips={clips.length} clips={clips} />

            {/* Controls Bar: Sort, Filter, Select All, Direct Downloads, Export */}
            <div className="max-w-4xl mx-auto mb-6 p-4 rounded-2xl border border-neutral-200/80 dark:border-neutral-800/80 bg-white/80 dark:bg-neutral-900/60 backdrop-blur-xl flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-4">
                {/* Select All Checkbox */}
                <button
                  onClick={handleSelectAll}
                  className="flex items-center gap-1.5 text-xs font-medium text-neutral-700 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-white"
                  title="Select or deselect all clips for batch download or 9:16 render"
                >
                  {selectedClipKeys.size > 0 && selectedClipKeys.size === processedClips.length ? (
                    <CheckSquare className="w-4 h-4 text-rose-600" />
                  ) : (
                    <Square className="w-4 h-4 text-neutral-400" />
                  )}
                  <span>
                    {selectedClipKeys.size > 0
                      ? `${selectedClipKeys.size} selected`
                      : 'Select All'}
                  </span>
                </button>

                {/* Sort selector */}
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-neutral-500 font-medium">Sort:</span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="px-2.5 py-1.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-neutral-800 dark:text-neutral-200 text-xs focus:outline-none"
                  >
                    <option value="virality">🔥 Virality Score</option>
                    <option value="seo">🚀 SEO Score</option>
                    <option value="time">⏱️ Chronological</option>
                  </select>
                </div>

                {/* Min Score slider */}
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-neutral-500 font-medium">Min:</span>
                  <input
                    type="range"
                    min="0"
                    max="85"
                    step="5"
                    value={minScore}
                    onChange={(e) => setMinScore(Number(e.target.value))}
                    className="w-16 accent-rose-600 cursor-pointer"
                  />
                  <span className="font-mono font-bold text-neutral-700 dark:text-neutral-300">
                    {minScore}+
                  </span>
                </div>
              </div>

              {/* Action Buttons: Batch 9:16 Shorts Render, Raw Zip, Copy All, Export */}
              <div className="flex flex-wrap items-center gap-2">
                {/* 1. Batch Render All Selected into 9:16 Shorts */}
                <button
                  onClick={handleBatchRenderShorts}
                  disabled={isBatchRenderingShorts}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-rose-600 via-pink-600 to-indigo-600 hover:from-rose-500 hover:to-indigo-500 text-white text-xs font-bold shadow-md shadow-rose-600/20 disabled:opacity-50 transition-all cursor-pointer"
                  title="Render all selected clips into ready-to-publish 9:16 Shorts with subtitles and sound effects in a ZIP bundle"
                >
                  {isBatchRenderingShorts ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Zap className="w-3.5 h-3.5" />
                  )}
                  <span>
                    {isBatchRenderingShorts
                      ? 'Rendering Shorts...'
                      : selectedClipKeys.size > 0
                      ? `Batch 9:16 Shorts (${selectedClipKeys.size})`
                      : 'Batch All 9:16 Shorts'}
                  </span>
                </button>

                <button
                  onClick={handleCopyAll}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-700/60 text-neutral-800 dark:text-neutral-200 text-xs font-medium transition-colors"
                  title="Copy all candidate summaries to clipboard"
                >
                  {copiedAll ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copiedAll ? 'Copied!' : 'Copy All'}</span>
                </button>

                <button
                  onClick={handleExportCSV}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-700/60 text-neutral-800 dark:text-neutral-200 text-xs font-medium transition-colors"
                  title="Export results to CSV"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>CSV</span>
                </button>

                <button
                  onClick={handleExportJSON}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-700/60 text-neutral-800 dark:text-neutral-200 text-xs font-medium transition-colors"
                  title="Export complete JSON"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>JSON</span>
                </button>
              </div>
            </div>

            {/* List of Clip Cards */}
            <div className="max-w-4xl mx-auto space-y-4">
              {processedClips.length > 0 ? (
                processedClips.map((clip) => {
                  const key = getClipKey(clip);
                  return (
                    <ClipCard
                      key={`${clip.rank}-${clip.start}`}
                      clip={clip}
                      onPreview={(c) => setPreviewClip(c)}
                      isSelected={selectedClipKeys.has(key)}
                      onToggleSelect={() => handleToggleSelect(clip)}
                      onDownload={(c) => handleDownloadSingleClip(c)}
                      isDownloading={downloadingClipKey === key}
                      onRenderShort={(c, opts) => handleRenderSingleShort(c, opts)}
                      isRenderingShort={renderingClipKey === key}
                      renderedShort={renderedShortsMap[key]}
                      onViewShort={(shortResult) => setActiveShortModal(shortResult)}
                    />
                  );
                })
              ) : (
                <div className="text-center py-12 p-6 rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 text-neutral-500">
                  <p className="text-sm">No clips match your minimum score filter of {minScore}+.</p>
                  <button
                    onClick={() => setMinScore(0)}
                    className="mt-2 text-xs text-indigo-600 dark:text-indigo-400 font-semibold hover:underline"
                  >
                    Reset Filter
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* YouTube Iframe Preview Modal */}
      <YouTubePreviewModal
        isOpen={Boolean(previewClip)}
        onClose={() => setPreviewClip(null)}
        videoId={videoMetadata?.video_id}
        clip={previewClip}
      />

      {/* Rendered 9:16 Short Player & Studio Publisher Drawer */}
      <ShortsPreviewModal
        isOpen={Boolean(activeShortModal)}
        onClose={() => {
          setActiveShortModal(null);
          setActiveRenderJob(null);
        }}
        shortData={activeShortModal}
        videoMetadata={videoMetadata}
        renderJob={activeRenderJob}
        onCancelJob={handleCancelRenderJob}
        onRerenderClip={handleRerenderClipWithNudges}
        backendUrl={BACKEND_URL}
      />

      {/* Manual Transcript Modal */}
      <ManualTranscriptModal
        isOpen={manualTranscriptModalOpen}
        onClose={() => setManualTranscriptModalOpen(false)}
        onSubmit={handleManualTranscriptSubmit}
        isSubmitting={isAnalyzing}
      />

      {/* Footer */}
      <footer className="mt-16 py-6 border-t border-neutral-200 dark:border-neutral-800 text-center text-xs text-neutral-500 dark:text-neutral-400">
        <p>ClipScout &bull; Ready-to-Publish 9:16 Shorts Studio &bull; YouTube Fair Use Compliant</p>
      </footer>
    </div>
  );
}
