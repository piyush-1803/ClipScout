import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Download,
  Copy,
  Check,
  ShieldCheck,
  Sparkles,
  Video,
  Volume2,
  Info,
  Loader2,
  FolderOpen,
  RefreshCw,
  Sliders,
  Scissors,
  MessageSquare,
  FileText,
  Play,
  RotateCcw
} from 'lucide-react';

export default function ShortsPreviewModal({
  isOpen,
  onClose,
  shortData,
  videoMetadata,
  renderJob,
  onCancelJob,
  onRerenderClip,
  backendUrl = 'http://localhost:8000'
}) {
  const [activeTab, setActiveTab] = useState('postkit'); // 'postkit' | 'subtitles' | 'trim'
  const [copiedField, setCopiedField] = useState(null);
  const [folderNotice, setFolderNotice] = useState(null);

  // Subtitles restyle state
  const [captionStyle, setCaptionStyle] = useState('creator_classic');
  const [captionsData, setCaptionsData] = useState(null);
  const [isRestyling, setIsRestyling] = useState(false);

  // Video and timeline state
  const videoRef = useRef(null);
  const [shotsData, setShotsData] = useState([]);
  const [currentTime, setCurrentTime] = useState(0);

  // Trim adjustments
  const [startNudge, setStartNudge] = useState(0);
  const [endNudge, setEndNudge] = useState(0);

  // Load shots.json and captions.json when shortData is ready
  useEffect(() => {
    if (shortData?.output_files?.shots_json) {
      fetch(`${backendUrl}${shortData.output_files.shots_json}`)
        .then((r) => r.json())
        .then((data) => setShotsData(data))
        .catch(() => {});
    }
    if (shortData?.output_files?.captions_json) {
      fetch(`${backendUrl}${shortData.output_files.captions_json}`)
        .then((r) => r.json())
        .then((data) => {
          setCaptionsData(data);
          if (data.style_preset) setCaptionStyle(data.style_preset);
        })
        .catch(() => {});
    }
  }, [shortData, backendUrl]);

  if (!isOpen) return null;

  const copyToClipboard = (text, fieldName) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handleOpenFolder = async () => {
    try {
      const folderPath = shortData?.output_dir || shortData?.output_files?.final_video?.replace('/final.mp4', '');
      const res = await fetch(`${backendUrl}/api/open-folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: folderPath || '' })
      });
      if (res.ok) {
        setFolderNotice('Opened folder in system file explorer!');
      } else {
        setFolderNotice('Folder path copied to clipboard');
      }
    } catch {
      setFolderNotice('Could not open folder automatically');
    }
    setTimeout(() => setFolderNotice(null), 2500);
  };

  const handleRestyleCaptions = async () => {
    if (!shortData?.output_dir && !shortData?.output_files?.captions_json) return;
    setIsRestyling(true);
    try {
      const folderPath = shortData?.output_dir || 'outputs';
      const res = await fetch(`${backendUrl}/api/captions/rebuild`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          output_dir: folderPath,
          new_style: captionStyle,
          new_lines: captionsData?.lines || null
        })
      });
      const data = await res.json();
      if (data.success && videoRef.current) {
        // Force reload video element with timestamp cache bust
        const currentSrc = videoRef.current.src.split('?')[0];
        videoRef.current.src = `${currentSrc}?t=${Date.now()}`;
        videoRef.current.play();
      }
    } catch (e) {
      alert(`Failed to restyle: ${e.message}`);
    } finally {
      setIsRestyling(false);
    }
  };

  const handleSeekShot = (timeSec) => {
    if (videoRef.current) {
      videoRef.current.currentTime = timeSec;
      videoRef.current.play();
    }
  };

  // Resolve URLs
  const videoSrc = shortData?.output_files?.final_video
    ? `${backendUrl}${shortData.output_files.final_video}`
    : shortData?.stream_url
    ? (shortData.stream_url.startsWith('http') ? shortData.stream_url : `${backendUrl}${shortData.stream_url}`)
    : null;

  const downloadUrl = shortData?.output_files?.final_video
    ? `${backendUrl}${shortData.output_files.final_video}`
    : shortData?.download_url
    ? (shortData.download_url.startsWith('http') ? shortData.download_url : `${backendUrl}${shortData.download_url}`)
    : null;

  const debugVideoUrl = shortData?.output_files?.debug_video
    ? `${backendUrl}${shortData.output_files.debug_video}`
    : null;

  const seo = shortData?.seo_package || shortData?.seo_metadata || {};
  const clipTitle = shortData?.clip_title || shortData?.hook_title || seo.title || 'YouTube Short';
  const duration = shortData?.duration || 30;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/85 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-5xl max-h-[92vh] rounded-3xl bg-neutral-900 border border-neutral-800 shadow-2xl overflow-hidden flex flex-col md:flex-row">
        {/* Close Button Top */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-30 p-2 text-neutral-400 hover:text-white rounded-full bg-neutral-800/90 hover:bg-neutral-700 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* LEFT COLUMN: 9:16 Video Player or Live Render Progress */}
        <div className="w-full md:w-[410px] bg-black flex flex-col items-center justify-center p-5 shrink-0 border-b md:border-b-0 md:border-r border-neutral-800 relative">
          {renderJob && renderJob.stage !== 'done' && renderJob.stage !== 'error' ? (
            /* Live Rendering State */
            <div className="w-full max-w-[280px] aspect-[9/16] rounded-2xl border-2 border-dashed border-neutral-700 bg-neutral-950 p-5 flex flex-col items-center justify-center text-center space-y-4">
              <div className="relative">
                <div className="w-16 h-16 rounded-full border-4 border-rose-500/20 border-t-rose-500 animate-spin" />
                <Video className="w-6 h-6 text-rose-500 absolute inset-0 m-auto" />
              </div>

              <div>
                <span className="text-[10px] uppercase font-bold tracking-wider text-rose-400 block mb-1">
                  Rendering 9:16 Short
                </span>
                <h4 className="text-sm font-bold text-white line-clamp-1">{clipTitle}</h4>
                <p className="text-xs text-neutral-400 mt-1 leading-relaxed">
                  {renderJob.message || 'Processing video pipeline...'}
                </p>
              </div>

              {/* Progress Bar */}
              <div className="w-full space-y-1.5">
                <div className="flex justify-between text-[11px] text-neutral-400 font-mono">
                  <span>{renderJob.stage}</span>
                  <span>{Math.round(renderJob.progress || 0)}%</span>
                </div>
                <div className="w-full h-2 rounded-full bg-neutral-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-rose-500 via-pink-500 to-indigo-500 transition-all duration-300"
                    style={{ width: `${Math.min(100, Math.max(5, renderJob.progress || 0))}%` }}
                  />
                </div>
              </div>

              {/* Cancel Button */}
              {onCancelJob && (
                <button
                  onClick={() => onCancelJob(renderJob.job_id)}
                  className="px-3 py-1.5 rounded-lg border border-neutral-700 hover:border-neutral-600 text-xs text-neutral-400 hover:text-white transition-colors"
                >
                  Cancel Render
                </button>
              )}
            </div>
          ) : (
            /* Completed Video Player */
            <div className="w-full flex flex-col items-center">
              <div className="relative w-full max-w-[270px] aspect-[9/16] rounded-2xl overflow-hidden shadow-2xl border-4 border-neutral-800 bg-neutral-950 flex items-center justify-center group">
                {videoSrc ? (
                  <video
                    ref={videoRef}
                    src={videoSrc}
                    controls
                    autoPlay
                    loop
                    playsInline
                    onTimeUpdate={(e) => setCurrentTime(e.target.currentTime)}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="text-center p-4 text-neutral-500 text-xs">
                    Video unavailable
                  </div>
                )}
                {/* Shorts 9:16 Watermark Pill */}
                <div className="absolute top-3 left-3 px-2 py-0.5 rounded-full bg-black/60 backdrop-blur-md text-white text-[10px] font-medium flex items-center gap-1 pointer-events-none">
                  <Video className="w-3 h-3 text-red-500" />
                  <span>Shorts 9:16</span>
                </div>
              </div>

              {/* Speaker Cut Timeline Strip */}
              {shotsData.length > 0 && (
                <div className="w-full max-w-[270px] mt-3">
                  <div className="flex items-center justify-between text-[10px] text-neutral-400 mb-1">
                    <span className="font-semibold text-neutral-300">Director Cuts ({shotsData.length})</span>
                    <span>{currentTime.toFixed(1)}s / {duration}s</span>
                  </div>
                  <div className="w-full h-4 bg-neutral-800 rounded-md overflow-hidden flex cursor-pointer border border-neutral-700">
                    {shotsData.map((shot, idx) => {
                      const shotDur = shot.end_time - shot.start_time;
                      const widthPct = (shotDur / duration) * 100;
                      const isCurrent = currentTime >= shot.start_time && currentTime <= shot.end_time;
                      const colors = [
                        'bg-rose-500 hover:bg-rose-400',
                        'bg-blue-500 hover:bg-blue-400',
                        'bg-emerald-500 hover:bg-emerald-400',
                        'bg-amber-500 hover:bg-amber-400'
                      ];
                      const col = colors[(shot.face_track_id || idx) % colors.length];

                      return (
                        <div
                          key={idx}
                          onClick={() => handleSeekShot(shot.start_time)}
                          className={`h-full border-r border-black/40 transition-opacity ${col} ${isCurrent ? 'opacity-100 ring-2 ring-white z-10' : 'opacity-75'}`}
                          style={{ width: `${Math.max(2, widthPct)}%` }}
                          title={`Shot #${idx + 1}: ${shot.speaker_label} (${shot.start_time}s - ${shot.end_time}s)`}
                        />
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Studio Controls, Post Kit, Captions Restyle */}
        <div className="flex-1 flex flex-col overflow-y-auto p-5 sm:p-6 text-neutral-100">
          {/* Header Tags */}
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>YouTube Shorts Ready &bull; Fair Use Compliant</span>
            </span>
            <span className="text-xs text-neutral-400 font-mono">
              {duration}s
            </span>
          </div>

          <h2 className="text-lg font-bold text-white line-clamp-2">
            {clipTitle}
          </h2>

          {/* Studio Navigation Tabs */}
          <div className="flex items-center gap-2 mt-4 border-b border-neutral-800 pb-2">
            <button
              onClick={() => setActiveTab('postkit')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                activeTab === 'postkit'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Post Kit &amp; SEO</span>
            </button>

            <button
              onClick={() => setActiveTab('subtitles')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                activeTab === 'subtitles'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <Sliders className="w-3.5 h-3.5" />
              <span>Restyle Subtitles</span>
            </button>

            <button
              onClick={() => setActiveTab('trim')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                activeTab === 'trim'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              <Scissors className="w-3.5 h-3.5" />
              <span>Trim Nudge</span>
            </button>
          </div>

          {/* TAB 1: POST KIT & SEO */}
          {activeTab === 'postkit' && (
            <div className="space-y-4 mt-3 flex-1">
              {/* Title with Copy Button */}
              <div>
                <div className="flex items-center justify-between text-xs text-neutral-400 mb-1">
                  <span className="font-semibold text-neutral-300">YouTube Shorts Title</span>
                  <button
                    onClick={() => copyToClipboard(seo.title || clipTitle, 'title')}
                    className="hover:text-indigo-400 flex items-center gap-1 text-xs"
                  >
                    {copiedField === 'title' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedField === 'title' ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>
                <div className="p-2.5 rounded-xl bg-neutral-950 border border-neutral-800 text-xs font-mono text-neutral-200">
                  {seo.title || clipTitle}
                </div>
              </div>

              {/* Description with Copy Button */}
              <div>
                <div className="flex items-center justify-between text-xs text-neutral-400 mb-1">
                  <span className="font-semibold text-neutral-300">Description with Original Source Credit</span>
                  <button
                    onClick={() => copyToClipboard(seo.description || '', 'desc')}
                    className="hover:text-indigo-400 flex items-center gap-1 text-xs"
                  >
                    {copiedField === 'desc' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedField === 'desc' ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>
                <textarea
                  readOnly
                  rows={4}
                  value={seo.description || `High dialogue moment from ${videoMetadata?.title || 'podcast'}.\n\nFull episode: https://www.youtube.com/watch?v=${videoMetadata?.video_id || ''}\nOriginal channel: ${videoMetadata?.channel || ''}`}
                  className="w-full p-2.5 rounded-xl bg-neutral-950 border border-neutral-800 text-xs font-mono text-neutral-300 resize-none focus:outline-none"
                />
              </div>

              {/* Suggested Pinned Comment */}
              <div>
                <div className="flex items-center justify-between text-xs text-neutral-400 mb-1">
                  <span className="font-semibold text-neutral-300 flex items-center gap-1">
                    <MessageSquare className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Suggested Pinned Comment</span>
                  </span>
                  <button
                    onClick={() => copyToClipboard(`🔥 What was your biggest takeaway from this? Full episode here: https://www.youtube.com/watch?v=${videoMetadata?.video_id || ''}`, 'comment')}
                    className="hover:text-indigo-400 flex items-center gap-1 text-xs"
                  >
                    {copiedField === 'comment' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedField === 'comment' ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>
                <div className="p-2.5 rounded-xl bg-neutral-950 border border-neutral-800 text-xs font-mono text-neutral-300">
                  🔥 What was your biggest takeaway from this? Watch the full discussion here: https://www.youtube.com/watch?v={videoMetadata?.video_id || ''}
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: SUBTITLES & RE-BURN */}
          {activeTab === 'subtitles' && (
            <div className="space-y-4 mt-3 flex-1">
              <div className="p-3 rounded-xl bg-neutral-950 border border-neutral-800 space-y-2">
                <label className="block text-xs font-semibold text-neutral-300">
                  Choose Style Preset
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  <button
                    onClick={() => setCaptionStyle('creator_classic')}
                    className={`p-2.5 rounded-lg border text-left text-xs transition-colors ${
                      captionStyle === 'creator_classic'
                        ? 'border-rose-500 bg-rose-500/10 text-white font-bold'
                        : 'border-neutral-800 bg-neutral-900 text-neutral-400'
                    }`}
                  >
                    <div className="font-semibold mb-0.5">Creator Classic</div>
                    <div className="text-[10px] opacity-75">Yellow text, solid red box</div>
                  </button>

                  <button
                    onClick={() => setCaptionStyle('active_word_pop')}
                    className={`p-2.5 rounded-lg border text-left text-xs transition-colors ${
                      captionStyle === 'active_word_pop'
                        ? 'border-indigo-500 bg-indigo-500/10 text-white font-bold'
                        : 'border-neutral-800 bg-neutral-900 text-neutral-400'
                    }`}
                  >
                    <div className="font-semibold mb-0.5">Word Pop</div>
                    <div className="text-[10px] opacity-75">White with spoken word yellow</div>
                  </button>

                  <button
                    onClick={() => setCaptionStyle('clean_outline')}
                    className={`p-2.5 rounded-lg border text-left text-xs transition-colors ${
                      captionStyle === 'clean_outline'
                        ? 'border-emerald-500 bg-emerald-500/10 text-white font-bold'
                        : 'border-neutral-800 bg-neutral-900 text-neutral-400'
                    }`}
                  >
                    <div className="font-semibold mb-0.5">Clean Outline</div>
                    <div className="text-[10px] opacity-75">Bold white, black drop shadow</div>
                  </button>
                </div>

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={handleRestyleCaptions}
                    disabled={isRestyling}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition-all disabled:opacity-50"
                  >
                    {isRestyling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                    <span>{isRestyling ? 'Re-burning (< 3s)...' : 'Re-burn Subtitles Now'}</span>
                  </button>
                </div>
              </div>

              {/* Editable Lines Preview */}
              {captionsData?.lines && (
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold text-neutral-400 block">
                    Caption Lines ({captionsData.lines.length})
                  </span>
                  <div className="max-h-48 overflow-y-auto space-y-1 pr-1 font-mono text-xs">
                    {captionsData.lines.map((line, idx) => (
                      <div key={idx} className="flex items-center gap-2 p-1.5 rounded-lg bg-neutral-950 border border-neutral-800">
                        <span className="text-[10px] text-neutral-500 shrink-0 w-16">
                          {line.start}s - {line.end}s
                        </span>
                        <input
                          type="text"
                          value={line.text}
                          onChange={(e) => {
                            const updated = [...captionsData.lines];
                            updated[idx].text = e.target.value;
                            setCaptionsData({ ...captionsData, lines: updated });
                          }}
                          className="flex-1 bg-transparent text-neutral-200 focus:outline-none focus:text-white"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: TRIM NUDGE */}
          {activeTab === 'trim' && (
            <div className="space-y-4 mt-3 flex-1 text-xs">
              <div className="p-4 rounded-xl bg-neutral-950 border border-neutral-800 space-y-3">
                <span className="font-semibold text-neutral-300 block">
                  Fine-Tune Clip Start &amp; End
                </span>
                <p className="text-neutral-400 text-[11px] leading-relaxed">
                  ClipScout automatically snapped the cut to speech sentence boundaries. If you want to expand or contract the cut, adjust below and click re-render:
                </p>

                <div className="grid grid-cols-2 gap-4 pt-1">
                  <div className="space-y-1.5">
                    <span className="text-[11px] text-neutral-400">Start Boundary Nudge</span>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setStartNudge((prev) => prev - 0.5)}
                        className="px-2.5 py-1.5 rounded-lg bg-neutral-900 border border-neutral-700 text-xs font-mono font-bold hover:bg-neutral-800"
                      >
                        -0.5s
                      </button>
                      <span className="font-mono text-neutral-300 w-12 text-center">{startNudge > 0 ? `+${startNudge}` : startNudge}s</span>
                      <button
                        onClick={() => setStartNudge((prev) => prev + 0.5)}
                        className="px-2.5 py-1.5 rounded-lg bg-neutral-900 border border-neutral-700 text-xs font-mono font-bold hover:bg-neutral-800"
                      >
                        +0.5s
                      </button>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <span className="text-[11px] text-neutral-400">End Boundary Nudge</span>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setEndNudge((prev) => prev - 0.5)}
                        className="px-2.5 py-1.5 rounded-lg bg-neutral-900 border border-neutral-700 text-xs font-mono font-bold hover:bg-neutral-800"
                      >
                        -0.5s
                      </button>
                      <span className="font-mono text-neutral-300 w-12 text-center">{endNudge > 0 ? `+${endNudge}` : endNudge}s</span>
                      <button
                        onClick={() => setEndNudge((prev) => prev + 0.5)}
                        className="px-2.5 py-1.5 rounded-lg bg-neutral-900 border border-neutral-700 text-xs font-mono font-bold hover:bg-neutral-800"
                      >
                        +0.5s
                      </button>
                    </div>
                  </div>
                </div>

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={() => {
                      if (onRerenderClip) {
                        onRerenderClip({
                          startNudge,
                          endNudge
                        });
                      }
                    }}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-rose-600 to-indigo-600 hover:from-rose-500 hover:to-indigo-500 text-white text-xs font-bold shadow-md"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    <span>Apply Trim &amp; Re-render</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Action Footer */}
          <div className="mt-4 pt-3 border-t border-neutral-800 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={handleOpenFolder}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-xs font-medium transition-colors"
                title="Reveal output files on computer"
              >
                <FolderOpen className="w-3.5 h-3.5 text-amber-400" />
                <span>Open Folder</span>
              </button>
              {folderNotice && <span className="text-[11px] text-emerald-400">{folderNotice}</span>}

              {debugVideoUrl && (
                <a
                  href={debugVideoUrl}
                  download="debug_faces.mp4"
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-xs font-medium transition-colors"
                >
                  <Video className="w-3.5 h-3.5 text-blue-400" />
                  <span>Debug Video</span>
                </a>
              )}
            </div>

            {downloadUrl && (
              <a
                href={downloadUrl}
                download={shortData?.filename || 'ready_short_916.mp4'}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-rose-600 via-pink-600 to-indigo-600 hover:from-rose-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-rose-600/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                <Download className="w-4 h-4" />
                <span>Download Master 9:16 Short</span>
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
