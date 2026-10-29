import React from 'react';
import { Clock, Video, User, ExternalLink, Flame, Activity } from 'lucide-react';

export default function VideoHeader({ video, totalClips, clips = [] }) {
  if (!video) return null;

  const heatmap = video.heatmap || [];
  const hasHeatmap = heatmap.length > 0 && video.duration > 0;

  // Build SVG path for replay heatmap sparkline
  const svgWidth = 600;
  const svgHeight = 44;
  let heatmapPath = '';
  let heatmapArea = '';

  if (hasHeatmap) {
    const points = heatmap.map((p) => {
      const midTime = (p.start_time + p.end_time) / 2;
      const x = Math.min(svgWidth, Math.max(0, (midTime / video.duration) * svgWidth));
      const val = Math.min(1, Math.max(0, p.value || 0));
      const y = svgHeight - val * (svgHeight - 8) - 4;
      return { x, y };
    });

    if (points.length > 1) {
      heatmapPath = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)} ` +
        points.slice(1).map((pt) => `L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(' ');
      heatmapArea = `${heatmapPath} L ${svgWidth} ${svgHeight} L 0 ${svgHeight} Z`;
    }
  }

  return (
    <div className="w-full max-w-4xl mx-auto mb-8 p-5 sm:p-6 rounded-2xl border border-neutral-200/80 dark:border-neutral-800/80 bg-neutral-50/70 dark:bg-neutral-900/60 backdrop-blur-xl flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row items-center gap-5">
        {video.thumbnail_url && (
          <div className="relative w-full sm:w-44 h-28 shrink-0 rounded-xl overflow-hidden shadow-md group">
            <img
              src={video.thumbnail_url}
              alt={video.title}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
            <div className="absolute inset-0 bg-black/20 group-hover:bg-black/10 transition-colors" />
            <div className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded bg-black/80 text-white text-[10px] font-mono font-medium flex items-center gap-1">
              <Clock className="w-3 h-3" />
              <span>{video.duration_formatted}</span>
            </div>
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400 border border-red-200/60 dark:border-red-900/50">
              <Video className="w-3 h-3" />
              <span>YouTube Source</span>
            </span>

            {hasHeatmap && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/10 text-rose-500 border border-rose-500/30">
                <Flame className="w-3 h-3" />
                <span>Audience Replay Heatmap Boost Active</span>
              </span>
            )}

            <span className="text-xs text-neutral-400">&bull;</span>
            <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
              {totalClips} Short-Form Candidates Identified
            </span>
          </div>

          <h2 className="text-base sm:text-lg font-bold text-neutral-900 dark:text-white line-clamp-2 leading-snug">
            {video.title}
          </h2>

          <div className="flex items-center gap-4 mt-2 text-xs text-neutral-500 dark:text-neutral-400">
            <div className="flex items-center gap-1.5">
              <User className="w-3.5 h-3.5" />
              <span className="font-medium text-neutral-700 dark:text-neutral-300">{video.channel}</span>
            </div>
            {video.video_id && (
              <a
                href={`https://www.youtube.com/watch?v=${video.video_id}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                <span>Watch full episode</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      </div>

      {/* Audience Replay Heatmap Sparkline with Clip Markers */}
      {hasHeatmap && (
        <div className="pt-3 border-t border-neutral-200/60 dark:border-neutral-800/60">
          <div className="flex items-center justify-between text-[11px] text-neutral-500 dark:text-neutral-400 mb-1.5 font-medium">
            <span className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-rose-500" />
              <span>YouTube "Most Replayed" Audience Curve &bull; Top Peaks Highlighted</span>
            </span>
            <span className="text-[10px] text-neutral-400">Pink markers = Extracted Clips</span>
          </div>

          <div className="relative w-full h-11 bg-neutral-900/40 rounded-xl overflow-hidden border border-neutral-200/50 dark:border-neutral-800/80 px-1 py-0.5">
            <svg
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              preserveAspectRatio="none"
              className="w-full h-full"
            >
              <defs>
                <linearGradient id="heatmapGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.45" />
                  <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Shaded Area Under Curve */}
              {heatmapArea && (
                <path d={heatmapArea} fill="url(#heatmapGrad)" />
              )}

              {/* Curve Line */}
              {heatmapPath && (
                <path d={heatmapPath} fill="none" stroke="#f43f5e" strokeWidth="2" strokeLinecap="round" />
              )}

              {/* Clip Start Markers */}
              {clips.map((clip, i) => {
                if (!clip.start || !video.duration) return null;
                const xPos = Math.min(svgWidth - 2, Math.max(2, (clip.start / video.duration) * svgWidth));
                return (
                  <g key={i}>
                    <line
                      x1={xPos}
                      y1="0"
                      x2={xPos}
                      y2={svgHeight}
                      stroke={clip.is_most_replayed ? '#ec4899' : '#38bdf8'}
                      strokeWidth={clip.is_most_replayed ? '2.5' : '1.5'}
                      strokeDasharray={clip.is_most_replayed ? 'none' : '3,2'}
                      opacity="0.9"
                    />
                    <circle
                      cx={xPos}
                      cy="5"
                      r={clip.is_most_replayed ? '3.5' : '2'}
                      fill={clip.is_most_replayed ? '#ec4899' : '#38bdf8'}
                    />
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
      )}
    </div>
  );
}
