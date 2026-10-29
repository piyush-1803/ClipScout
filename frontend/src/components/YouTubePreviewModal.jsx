import React, { useEffect, useRef, useState } from 'react';
import { X, Play, Pause, RotateCcw } from 'lucide-react';

export default function YouTubePreviewModal({ isOpen, onClose, videoId, clip }) {
  const playerRef = useRef(null);
  const containerRef = useRef(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const checkIntervalRef = useRef(null);

  useEffect(() => {
    if (!isOpen || !videoId || !clip) return;

    // Load YouTube IFrame API script if not already on window
    const loadYT = () => {
      if (window.YT && window.YT.Player) {
        initPlayer();
      } else {
        const tag = document.createElement('script');
        tag.src = 'https://www.youtube.com/iframe_api';
        window.onYouTubeIframeAPIReady = initPlayer;
        document.body.appendChild(tag);
      }
    };

    const initPlayer = () => {
      if (playerRef.current) {
        try {
          playerRef.current.destroy();
        } catch (e) {}
      }

      playerRef.current = new window.YT.Player('clip-youtube-iframe', {
        videoId: videoId,
        playerVars: {
          autoplay: 1,
          start: Math.floor(clip.start),
          end: Math.ceil(clip.end),
          controls: 1,
          modestbranding: 1,
          rel: 0,
        },
        events: {
          onReady: (event) => {
            event.target.seekTo(clip.start, true);
            event.target.playVideo();
            setIsPlaying(true);
          },
          onStateChange: (event) => {
            if (event.data === window.YT.PlayerState.PLAYING) {
              setIsPlaying(true);
              startEndCheck();
            } else {
              setIsPlaying(false);
              stopEndCheck();
            }
          }
        }
      });
    };

    loadYT();

    return () => {
      stopEndCheck();
      if (playerRef.current) {
        try {
          playerRef.current.destroy();
        } catch (e) {}
      }
    };
  }, [isOpen, videoId, clip]);

  const startEndCheck = () => {
    stopEndCheck();
    checkIntervalRef.current = setInterval(() => {
      if (playerRef.current && typeof playerRef.current.getCurrentTime === 'function') {
        const currentTime = playerRef.current.getCurrentTime();
        if (currentTime >= clip.end) {
          playerRef.current.pauseVideo();
          setIsPlaying(false);
          stopEndCheck();
        }
      }
    }, 250);
  };

  const stopEndCheck = () => {
    if (checkIntervalRef.current) {
      clearInterval(checkIntervalRef.current);
      checkIntervalRef.current = null;
    }
  };

  const restartClip = () => {
    if (playerRef.current) {
      playerRef.current.seekTo(clip.start, true);
      playerRef.current.playVideo();
      setIsPlaying(true);
    }
  };

  const togglePlay = () => {
    if (!playerRef.current) return;
    if (isPlaying) {
      playerRef.current.pauseVideo();
    } else {
      playerRef.current.playVideo();
    }
  };

  if (!isOpen || !clip) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl rounded-2xl bg-neutral-900 border border-neutral-800 shadow-2xl overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="p-4 flex items-center justify-between border-b border-neutral-800 text-white">
          <div>
            <h3 className="text-sm font-semibold truncate max-w-md">
              Preview: {clip.seo.title || 'Clip Preview'}
            </h3>
            <p className="text-xs text-neutral-400">
              {clip.start_formatted} &rarr; {clip.end_formatted} ({clip.duration}s)
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-neutral-400 hover:text-white rounded-lg hover:bg-neutral-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Video Embed */}
        <div className="relative aspect-video bg-black flex items-center justify-center">
          <div id="clip-youtube-iframe" className="w-full h-full" />
        </div>

        {/* Controls footer */}
        <div className="p-3 bg-neutral-950 flex items-center justify-between border-t border-neutral-800">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-medium flex items-center gap-1.5 transition-colors"
            >
              {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              <span>{isPlaying ? 'Pause' : 'Play'}</span>
            </button>
            <button
              onClick={restartClip}
              className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-medium flex items-center gap-1.5 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Replay Clip</span>
            </button>
          </div>

          <span className="text-[11px] text-neutral-400">
            Auto-pauses at {clip.end_formatted}
          </span>
        </div>
      </div>
    </div>
  );
}
