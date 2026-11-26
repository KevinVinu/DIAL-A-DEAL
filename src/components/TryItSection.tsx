import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Phone,
  PhoneOff,
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  RotateCcw,
  Sparkles,
  Globe,
  CheckCircle2,
  Clock,
  Zap,
  User,
  Building,
  Calendar,
} from 'lucide-react';

type CallState = 'idle' | 'connecting' | 'speaking' | 'listening' | 'ended';

interface TranscriptItem {
  id: string;
  sender: 'ai' | 'customer';
  text: string;
  timestamp: string;
}

// Language code mapping – matches backend SUPPORTED_LANGUAGES + Sarvam auto-detection ('unknown')
const LANG_CODES: Record<string, string> = {
  'Auto-Detect (All 5 Languages)': 'unknown',
  'English (en-IN)': 'en-IN',
  'Hindi (hi-IN)': 'hi-IN',
  'Tamil (ta-IN)': 'ta-IN',
  'Telugu (te-IN)': 'te-IN',
  'Malayalam (ml-IN)': 'ml-IN',
};

const LANGUAGES = [
  'Auto-Detect (All 5 Languages)',
  'English (en-IN)',
  'Hindi (hi-IN)',
  'Tamil (ta-IN)',
  'Telugu (te-IN)',
  'Malayalam (ml-IN)',
];

const TARGET_SAMPLE_RATE = 16000;

function downsampleTo16k(input: Float32Array, inputRate: number): Float32Array {
  if (inputRate === TARGET_SAMPLE_RATE) return input;
  const ratio = inputRate / TARGET_SAMPLE_RATE;
  const outLen = Math.max(1, Math.floor(input.length / ratio));
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j++) {
      sum += input[j];
      count++;
    }
    out[i] = count > 0 ? sum / count : input[start] || 0;
  }
  return out;
}

function encodeWav16kMono(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, 'WAVEfmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // Mono
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunkSize)));
  }
  return btoa(binary);
}

const BACKEND_WS_URL = 'ws://localhost:8000';

const generateSessionId = () =>
  `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

export const TryItSection: React.FC = () => {
  const [callState, setCallState] = useState<CallState>('idle');
  // Dynamic Caller Information (No hardcoded values)
  const [callerName, setCallerName] = useState('Rahul');
  const [callerAge, setCallerAge] = useState('28');
  const [callerCompany, setCallerCompany] = useState('Tech Solutions');
  const [selectedLanguage, setSelectedLanguage] = useState(LANGUAGES[0]);

  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [callSeconds, setCallSeconds] = useState(0);
  const [isMicActive, setIsMicActive] = useState(false);
  const [isSpeakerOn, setIsSpeakerOn] = useState(true);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [showEmailInput, setShowEmailInput] = useState(false);
  const [emailInput, setEmailInput] = useState('');
  const [emailError, setEmailError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const [callSummary, setCallSummary] = useState<{ booked: boolean; note: string } | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const transcriptContainerRef = useRef<HTMLDivElement>(null);

  // Real-time audio refs
  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const captureContextRef = useRef<AudioContext | null>(null);
  const processorNodeRef = useRef<ScriptProcessorNode | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const currentAudioSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const sessionIdRef = useRef<string>('');
  const isMicActiveRef = useRef<boolean>(false);
  const flushUtteranceRef = useRef<(() => void) | null>(null);
  const isAiSpeakingRef = useRef<boolean>(false);
  const isRecordingLoopActiveRef = useRef<boolean>(false);

  // Auto-scroll transcript ONLY inside its container without scrolling the browser page/window
  useEffect(() => {
    if (transcriptContainerRef.current) {
      transcriptContainerRef.current.scrollTop = transcriptContainerRef.current.scrollHeight;
    }
  }, [transcript]);

  // Duration clock
  useEffect(() => {
    if (callState === 'speaking' || callState === 'listening') {
      timerRef.current = setInterval(() => {
        setCallSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [callState]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      cleanupCall();
    };
  }, []);

  const addTranscriptItem = useCallback((sender: 'ai' | 'customer', text: string) => {
    const now = new Date();
    setTranscript((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random()}`,
        sender,
        text,
        timestamp: now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      },
    ]);
  }, []);

  const stopCurrentAudio = useCallback(() => {
    try {
      currentAudioSourceRef.current?.stop();
    } catch {}
    currentAudioSourceRef.current = null;
    isAiSpeakingRef.current = false;
  }, []);

  const playAudioBase64 = useCallback(
    async (b64: string) => {
      if (!isSpeakerOn) return;
      try {
        if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
          audioContextRef.current = new AudioContext();
        }
        const ctx = audioContextRef.current;
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        const buffer = await ctx.decodeAudioData(bytes.buffer);
        stopCurrentAudio();
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        isAiSpeakingRef.current = true;
        setCallState('speaking');
        source.onended = () => {
          currentAudioSourceRef.current = null;
          isAiSpeakingRef.current = false;
          setCallState('listening');
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'playback_finished' }));
          }
        };
        source.start();
        currentAudioSourceRef.current = source;
      } catch (err) {
        console.warn('[TryIt] Audio playback error:', err);
        isAiSpeakingRef.current = false;
        setCallState('listening');
      }
    },
    [isSpeakerOn, stopCurrentAudio]
  );

  const cleanupCall = useCallback(() => {
    isRecordingLoopActiveRef.current = false;
    isAiSpeakingRef.current = false;

    // Stop Web Audio capture graph
    try {
      processorNodeRef.current?.disconnect();
    } catch {}
    processorNodeRef.current = null;
    try {
      captureContextRef.current?.close();
    } catch {}
    captureContextRef.current = null;

    // Stop microphone tracks
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;

    // Close WebSocket
    try {
      wsRef.current?.close();
    } catch {}
    wsRef.current = null;

    // Stop any playing audio
    stopCurrentAudio();

    // Close AudioContext
    try {
      audioContextRef.current?.close();
    } catch {}
    audioContextRef.current = null;
  }, [stopCurrentAudio]);

  const handleStartCall = useCallback(async () => {
    // Reset state
    cleanupCall();
    setTranscript([]);
    setCallSeconds(0);
    setCallSummary(null);
    setShowEmailInput(false);
    setEmailInput('');
    setEmailError('');
    setStatusMessage('');
    setIsMicActive(false);
    setIsSpeakerOn(true);
    isMicActiveRef.current = false;
    setCallState('connecting');

    // 1. Request microphone with echo cancellation
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;
    } catch (err) {
      setStatusMessage('Microphone access denied. Please allow microphone permissions and try again.');
      setCallState('idle');
      return;
    }

    // 2. Build session ID and open WebSocket
    const sessionId = generateSessionId();
    sessionIdRef.current = sessionId;
    const langCode = LANG_CODES[selectedLanguage] ?? 'en-IN';

    const ws = new WebSocket(`${BACKEND_WS_URL}/ws/call/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      // Send caller profile & chosen language
      ws.send(
        JSON.stringify({
          type: 'call_init',
          language: langCode,
          caller_name: callerName.trim() || 'Valued Caller',
          caller_age: callerAge.trim() ? parseInt(callerAge, 10) : null,
          caller_company: callerCompany.trim() || 'Direct Client',
        })
      );
    };

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);

        switch (msg.type) {
          case 'call_started':
            setCallState('listening');
            startContinuousAudioCapture(stream, ws);
            break;

          case 'transcript_customer':
            setCallState('listening');
            if (msg.text?.trim()) addTranscriptItem('customer', msg.text.trim());
            break;

          case 'ai_thinking':
            setCallState('speaking');
            break;

          case 'ai_response':
            setCallState('speaking');
            if (msg.text?.trim()) addTranscriptItem('ai', msg.text.trim());
            break;

          case 'request_email_input':
            setShowEmailInput(true);
            setEmailError('');
            break;

          case 'ai_audio':
            if (msg.audio) await playAudioBase64(msg.audio);
            break;

          case 'interruption':
            stopCurrentAudio();
            setCallState('listening');
            break;

          case 'call_ended':
            setCallState('ended');
            if (msg.summary) {
              setCallSummary({ booked: msg.summary.appointment_booked ?? false, note: msg.summary.note ?? '' });
            }
            cleanupCall();
            break;

          case 'error':
            setStatusMessage(msg.message ?? 'An error occurred.');
            setCallState('ended');
            cleanupCall();
            break;

          default:
            break;
        }
      } catch (e) {
        console.error('[TryIt] WS message parse error:', e);
      }
    };

    ws.onerror = () => {
      setStatusMessage('Connection error. Is the backend running on port 8000?');
      setCallState('ended');
      cleanupCall();
    };

    ws.onclose = (evt) => {
      if (callState !== 'ended') {
        if (evt.code !== 1000) {
          setStatusMessage('Connection closed.');
        }
        setCallState('ended');
        cleanupCall();
      }
    };
  }, [selectedLanguage, callerName, callerAge, callerCompany, cleanupCall, addTranscriptItem, playAudioBase64, stopCurrentAudio]);

  /**
   * Push-to-Speak 16kHz Mono PCM WAV capture:
   * - Does NOT listen to background noise while mic is inactive.
   * - When the user clicks the Microphone button, records 16kHz 16-bit PCM WAV.
   * - Automatically sends and turns mic off after 1.2s of post-speech silence,
   *   OR sends immediately when the user clicks the Microphone button again.
   */
  const startContinuousAudioCapture = (stream: MediaStream, ws: WebSocket) => {
    isRecordingLoopActiveRef.current = true;

    const captureCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    captureContextRef.current = captureCtx;
    const source = captureCtx.createMediaStreamSource(stream);
    const processor = captureCtx.createScriptProcessor(4096, 1, 1);
    processorNodeRef.current = processor;

    const minSpeechSamples = Math.floor(TARGET_SAMPLE_RATE * 0.20);
    const maxUtteranceSamples = Math.floor(TARGET_SAMPLE_RATE * 24.0);
    const hangoverMs = 1200;
    const rmsThreshold = 0.008;

    let utteranceBuffers: Float32Array[] = [];
    let utteranceLen = 0;
    let spokeDuringRecording = false;
    let lastVoiceTime = 0;

    const flushUtterance = () => {
      if (utteranceLen >= minSpeechSamples && ws.readyState === WebSocket.OPEN) {
        const merged = new Float32Array(utteranceLen);
        let offset = 0;
        for (const buf of utteranceBuffers) {
          merged.set(buf, offset);
          offset += buf.length;
        }
        const wavBuf = encodeWav16kMono(merged);
        const b64 = arrayBufferToBase64(wavBuf);
        ws.send(JSON.stringify({ type: 'audio_chunk', audio: b64, format: 'wav', sample_rate: TARGET_SAMPLE_RATE }));
      }
      utteranceBuffers = [];
      utteranceLen = 0;
      spokeDuringRecording = false;
      isMicActiveRef.current = false;
      setIsMicActive(false);
      setIsUserSpeaking(false);
    };

    flushUtteranceRef.current = flushUtterance;

    processor.onaudioprocess = (event) => {
      if (!isRecordingLoopActiveRef.current || ws.readyState !== WebSocket.OPEN) return;

      // Only record when the user has explicitly activated the Microphone button
      if (!isMicActiveRef.current) {
        if (utteranceLen > 0) {
          utteranceBuffers = [];
          utteranceLen = 0;
          spokeDuringRecording = false;
        }
        return;
      }

      const raw = event.inputBuffer.getChannelData(0);
      const samples = downsampleTo16k(raw, captureCtx.sampleRate);

      let sumSq = 0;
      for (let i = 0; i < samples.length; i++) {
        sumSq += samples[i] * samples[i];
      }
      const rms = Math.sqrt(sumSq / samples.length);
      const now = performance.now();

      utteranceBuffers.push(samples);
      utteranceLen += samples.length;

      if (rms >= rmsThreshold) {
        spokeDuringRecording = true;
        lastVoiceTime = now;
      }

      if (utteranceLen >= maxUtteranceSamples) {
        flushUtterance();
      } else if (spokeDuringRecording && now - lastVoiceTime >= hangoverMs) {
        // User finished speaking and paused -> auto-send and turn mic off
        flushUtterance();
      }
    };

    source.connect(processor);
    processor.connect(captureCtx.destination);
  };

  const handleEndCall = useCallback(() => {
    isMicActiveRef.current = false;
    setIsMicActive(false);
    setIsUserSpeaking(false);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'call_ended' }));
    }
    setCallState('ended');
    cleanupCall();
  }, [cleanupCall]);

  const handleMicToggle = useCallback(() => {
    if (callState === 'idle' || callState === 'ended') return;
    if (!isMicActiveRef.current) {
      // Interrupt AI playback if currently speaking so user can talk immediately
      if (isAiSpeakingRef.current) {
        stopCurrentAudio();
        setCallState('listening');
      }
      isMicActiveRef.current = true;
      setIsMicActive(true);
      setIsUserSpeaking(true);
    } else {
      // User clicked mic again to finish speaking & send immediately
      flushUtteranceRef.current?.();
    }
  }, [callState, stopCurrentAudio]);

  const handleSpeakerToggle = useCallback(() => {
    const nextOn = !isSpeakerOn;
    setIsSpeakerOn(nextOn);
    if (!nextOn) stopCurrentAudio();
  }, [isSpeakerOn, stopCurrentAudio]);

  const handleReset = useCallback(() => {
    cleanupCall();
    setCallState('idle');
    setTranscript([]);
    setCallSeconds(0);
    setCallSummary(null);
    setShowEmailInput(false);
    setEmailInput('');
    setEmailError('');
    setStatusMessage('');
  }, [cleanupCall]);

  const handleConfirmEmail = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const trimmed = emailInput.trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
        setEmailError('Please enter a valid email address.');
        return;
      }
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'email_input', email: trimmed }));
        setShowEmailInput(false);
        setEmailInput('');
        setEmailError('');
      }
    },
    [emailInput]
  );

  const formatTime = (totalSeconds: number) => {
    const mins = Math.floor(totalSeconds / 60);
    const secs = totalSeconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  // 22 waveform bar base heights
  const waveformBars = [18, 35, 62, 44, 78, 92, 54, 85, 40, 68, 95, 80, 58, 88, 48, 72, 90, 60, 42, 76, 50, 24];

  return (
    <section id="tryit" className="relative py-24 sm:py-32 border-t border-white/[0.08] bg-black overflow-hidden">
      {/* Background ambient lighting */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[500px] bg-indigo-500/[0.04] rounded-full blur-[140px] pointer-events-none" />

      <div className="max-w-7xl mx-auto px-6 sm:px-8 relative z-10">
        {/* Section Header */}
        <div className="text-center mb-16 space-y-4">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900 border border-white/10 text-xs font-mono text-zinc-400">
            <Sparkles className="w-3.5 h-3.5 text-zinc-300" />
            <span>// LIVE TWO-WAY VOICE AGENT</span>
          </div>

          <h2 className="font-heading text-3xl sm:text-5xl font-bold text-white tracking-tight">
            Live Call with DIAL-a-DEAL AI
          </h2>

          <p className="text-zinc-400 max-w-2xl mx-auto text-base sm:text-lg font-sans leading-relaxed">
            Speak live into your microphone. Our autonomous agent answers questions in real-time, qualifies your requirements, and saves your details in the database.
          </p>
        </div>

        {/* Error / status banner */}
        {statusMessage && (
          <div className="mb-6 mx-auto max-w-2xl px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-mono text-center">
            ⚠ {statusMessage}
          </div>
        )}

        {/* =========================================================================
            MAIN INTERACTIVE STAGE & FLOATING VOICE CALL INTERFACE
           ========================================================================= */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">

          {/* Left Column: Dynamic Caller Profile & Controls */}
          <div className="lg:col-span-5 space-y-5">
            <div className="luxury-card rounded-2xl p-6 sm:p-7 border border-white/[0.08]">
              <div className="flex items-center justify-between pb-4 border-b border-white/[0.06] mb-5">
                <span className="text-xs font-mono uppercase tracking-widest text-zinc-400">Caller Identity</span>
                <span className="text-[11px] font-mono text-emerald-400 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Agent Ready
                </span>
              </div>

              {/* Dynamic Caller Inputs */}
              <div className="space-y-4 mb-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-1.5 mb-1.5">
                      <User className="w-3 h-3 text-zinc-400" />
                      Your Name
                    </label>
                    <input
                      type="text"
                      value={callerName}
                      onChange={(e) => setCallerName(e.target.value)}
                      disabled={callState !== 'idle' && callState !== 'ended'}
                      placeholder="e.g. Rahul Sharma"
                      className="w-full px-3.5 py-2.5 rounded-xl bg-zinc-900 border border-white/10 text-white text-xs font-sans focus:outline-none focus:border-white/30 transition-colors disabled:opacity-50"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-1.5 mb-1.5">
                      <Calendar className="w-3 h-3 text-zinc-400" />
                      Your Age
                    </label>
                    <input
                      type="number"
                      value={callerAge}
                      onChange={(e) => setCallerAge(e.target.value)}
                      disabled={callState !== 'idle' && callState !== 'ended'}
                      placeholder="e.g. 28"
                      className="w-full px-3.5 py-2.5 rounded-xl bg-zinc-900 border border-white/10 text-white text-xs font-sans focus:outline-none focus:border-white/30 transition-colors disabled:opacity-50"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-[11px] font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-1.5 mb-1.5">
                    <Building className="w-3 h-3 text-zinc-400" />
                    Company / Organization
                  </label>
                  <input
                    type="text"
                    value={callerCompany}
                    onChange={(e) => setCallerCompany(e.target.value)}
                    disabled={callState !== 'idle' && callState !== 'ended'}
                    placeholder="e.g. Acme Corp / Independent"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-zinc-900 border border-white/10 text-white text-xs font-sans focus:outline-none focus:border-white/30 transition-colors disabled:opacity-50"
                  />
                </div>
              </div>

              {/* Language Selection */}
              <div className="space-y-2 mb-6">
                <label className="text-xs font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                  <Globe className="w-3.5 h-3.5 text-zinc-400" />
                  Agent Voice Language
                </label>
                <select
                  value={selectedLanguage}
                  onChange={(e) => setSelectedLanguage(e.target.value)}
                  disabled={callState !== 'idle' && callState !== 'ended'}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-zinc-900 border border-white/10 text-zinc-200 text-xs font-mono focus:outline-none focus:border-white/30 transition-colors disabled:opacity-50"
                >
                  {LANGUAGES.map((lang) => (
                    <option key={lang} value={lang} className="bg-zinc-950 text-white">
                      {lang}
                    </option>
                  ))}
                </select>
              </div>

              {/* Big "Make a Call" Trigger Button */}
              {callState === 'idle' || callState === 'ended' ? (
                <button
                  id="make-a-call-trigger-btn"
                  onClick={handleStartCall}
                  className="w-full py-4 rounded-xl bg-white hover:bg-zinc-200 text-black font-bold text-sm tracking-tight transition-all duration-150 flex items-center justify-center gap-3 shadow-lg group cursor-pointer"
                >
                  <div className="w-7 h-7 rounded-lg bg-black text-white flex items-center justify-center transition-transform group-hover:scale-110">
                    <Phone className="w-4 h-4 fill-white" />
                  </div>
                  <span>{callState === 'ended' ? 'Make Another Call' : 'Make a Call Now'}</span>
                </button>
              ) : (
                <button
                  onClick={handleEndCall}
                  className="w-full py-4 rounded-xl bg-red-600 hover:bg-red-500 text-white font-bold text-sm tracking-tight transition-all duration-150 flex items-center justify-center gap-3 shadow-lg cursor-pointer"
                >
                  <PhoneOff className="w-4 h-4" />
                  <span>End Live Call</span>
                </button>
              )}

              {/* Feature Highlights */}
              <div className="grid grid-cols-2 gap-2 mt-5 pt-4 border-t border-white/[0.06] text-[11px] font-mono text-zinc-500">
                <div className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-zinc-400" />
                  <span>Sarvam Saaras V4 STT</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-zinc-400" />
                  <span>Groq GPT-OSS LLM</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-zinc-400" />
                  <span>Azure HD Neural TTS</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-zinc-400" />
                  <span>Direct DB Sync</span>
                </div>
              </div>
            </div>

            {/* Live Call Instructions */}
            <div className="luxury-card rounded-2xl p-5 border border-white/[0.08] text-xs font-mono text-zinc-500 space-y-3">
              <div className="text-zinc-300 font-semibold text-[11px] uppercase tracking-widest mb-1">Live Call Guidelines</div>
              {[
                ['🎙️', 'Speak clearly after the agent finishes its turn.'],
                ['🗣️', 'Ask questions about pricing, features, or book a demo.'],
                ['💾', 'Your name, age, and requirements are recorded in the CRM database.'],
              ].map(([icon, text]) => (
                <div key={text} className="flex items-start gap-2">
                  <span>{icon}</span>
                  <span>{text}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right Column: Premium Floating AI Voice Call Interface */}
          <div className="lg:col-span-7 flex justify-center">

            {/* Floating Call Container Window */}
            <div
              className={`w-full max-w-lg rounded-3xl bg-[#09090b] border border-white/[0.12] shadow-2xl p-6 sm:p-8 relative overflow-hidden transition-all duration-300 ${
                callState !== 'idle' ? 'animate-floating' : ''
              }`}
            >
              {/* Subtle top glare reflection */}
              <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-white/25 to-transparent pointer-events-none" />

              {/* Active Call Green Glow Outline when connected */}
              {callState === 'speaking' || callState === 'listening' ? (
                <div className="absolute -top-12 -right-12 w-36 h-36 bg-emerald-500/10 rounded-full blur-2xl pointer-events-none" />
              ) : null}

              {/* Card Header: Agent Identity & Active Call Indicator */}
              <div className="flex items-start justify-between pb-6 border-b border-white/[0.08]">
                <div className="flex items-center gap-4">
                  {/* AI Agent Avatar with animated glowing rings */}
                  <div className="relative w-14 h-14 flex items-center justify-center flex-shrink-0">
                    {callState !== 'idle' && callState !== 'ended' && (
                      <>
                        <div className="absolute inset-0 rounded-full border border-emerald-400/30 animate-ring-pulse-1 pointer-events-none" />
                        <div className="absolute inset-0 rounded-full border border-emerald-400/20 animate-ring-pulse-2 pointer-events-none" />
                        <div className="absolute inset-0 rounded-full border border-emerald-400/10 animate-ring-pulse-3 pointer-events-none" />
                      </>
                    )}

                    {/* Core Avatar Orb */}
                    <div
                      className={`relative w-12 h-12 rounded-2xl flex items-center justify-center font-bold text-white transition-all duration-300 ${
                        callState === 'speaking'
                          ? 'bg-gradient-to-br from-zinc-100 to-zinc-400 text-black animate-avatar-speaking'
                          : callState === 'listening'
                          ? 'bg-gradient-to-br from-emerald-500 to-emerald-700 text-white'
                          : callState === 'connecting'
                          ? 'bg-gradient-to-br from-zinc-700 to-zinc-900 text-zinc-300 animate-pulse'
                          : 'bg-zinc-800 text-zinc-400'
                      }`}
                    >
                      <Zap className={`w-6 h-6 ${callState === 'speaking' ? 'text-black' : 'text-white'}`} />
                    </div>

                    {/* Active call indicator with subtle green glow */}
                    {callState !== 'idle' && callState !== 'ended' && (
                      <span className="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-500 border-2 border-black active-call-glow" />
                    )}
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-heading font-bold text-white text-base sm:text-lg">DIAL-a-DEAL AI</h3>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 border border-white/10">
                        Alex · AI Sales Agent
                      </span>
                    </div>
                    <div className="text-xs text-zinc-400 mt-0.5">
                      Caller: <strong className="text-zinc-200">{callerName.trim() || 'Live Prospect'}</strong>
                      {callerAge.trim() ? <span className="text-zinc-500 font-mono ml-1.5">(Age: {callerAge.trim()})</span> : null}
                    </div>
                  </div>
                </div>

                {/* Call Status & Timer Badge */}
                <div className="text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        callState === 'connecting'
                          ? 'bg-amber-400 animate-ping'
                          : callState === 'speaking'
                          ? 'bg-emerald-400 animate-pulse'
                          : callState === 'listening'
                          ? 'bg-emerald-400'
                          : callState === 'ended'
                          ? 'bg-zinc-600'
                          : 'bg-zinc-700'
                      }`}
                    />
                    <span
                      className={`text-xs font-mono uppercase tracking-wider font-semibold ${
                        callState === 'connecting'
                          ? 'text-amber-400'
                          : callState === 'speaking'
                          ? 'text-emerald-400'
                          : callState === 'listening'
                          ? 'text-emerald-300'
                          : callState === 'ended'
                          ? 'text-zinc-500'
                          : 'text-zinc-600'
                      }`}
                    >
                      {callState === 'idle'
                        ? 'Standby'
                        : callState === 'connecting'
                        ? 'Connecting…'
                        : callState === 'speaking'
                        ? 'AI Speaking'
                        : isUserSpeaking
                        ? '🎙️ Speaking...'
                        : callState === 'listening'
                        ? 'Listening…'
                        : 'Call Ended'}
                    </span>
                  </div>

                  {/* Call Duration Timer */}
                  <div className="text-xs font-mono text-zinc-400 mt-1 flex items-center justify-end gap-1">
                    <Clock className="w-3 h-3 text-zinc-500" />
                    <span>{formatTime(callSeconds)}</span>
                  </div>
                </div>
              </div>

              {/* Animated Real-Time Audio Waveform */}
              <div className="my-5 p-4 rounded-2xl bg-zinc-950/80 border border-white/[0.06]">
                <div className="flex items-center justify-between text-[11px] font-mono text-zinc-500 mb-2.5">
                  <span className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${callState === 'speaking' ? 'bg-white animate-pulse' : isMicActive ? 'bg-emerald-400 animate-ping' : callState === 'listening' ? 'bg-zinc-500' : 'bg-zinc-700'}`} />
                    {isMicActive ? 'Recording… Speak now (auto-sends on pause)' : callState === 'speaking' ? 'AI Voice Active' : callState === 'listening' ? 'Click Microphone to Speak' : 'Audio Spectrum Monitor'}
                  </span>
                  <span>{selectedLanguage.split(' ')[0]} · 24kHz HD Voice</span>
                </div>

                {/* Waveform Bars */}
                <div className="flex items-center justify-between gap-1 h-14 px-1">
                  {waveformBars.map((baseHeight, idx) => {
                    const isCallActive = callState === 'speaking' || isUserSpeaking;
                    const activeHeight = callState === 'speaking' ? baseHeight : isUserSpeaking ? baseHeight * 0.8 : 10;
                    return (
                      <div
                        key={idx}
                        className={`flex-1 rounded-full transition-all duration-150 ${
                          callState === 'speaking'
                            ? 'bg-zinc-100 animate-waveform-bar'
                            : isUserSpeaking
                            ? 'bg-emerald-400 animate-waveform-bar'
                            : 'bg-zinc-800'
                        }`}
                        style={{
                          height: `${activeHeight}%`,
                          animationDelay: `${(idx % 6) * 0.12}s`,
                          animationPlayState: isCallActive ? 'running' : 'paused',
                        }}
                      />
                    );
                  })}
                </div>
              </div>

              {/* Live Conversation Transcript Panel */}
              <div className="space-y-2">
                <div className="text-[10px] font-mono uppercase tracking-widest text-zinc-500 flex items-center justify-between">
                  <span>Live Speech-to-Text Transcript</span>
                  {callState !== 'idle' && callState !== 'ended' && (
                    <span className="text-emerald-400 text-[10px] flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                      Live Stream Active
                    </span>
                  )}
                </div>

                <div
                  ref={transcriptContainerRef}
                  className="h-56 overflow-y-auto space-y-3 p-3.5 rounded-2xl bg-black/60 border border-white/[0.06] scroll-smooth"
                >
                  {transcript.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-center p-4">
                      {callState === 'connecting' ? (
                        <div className="space-y-2">
                          <div className="w-6 h-6 border-2 border-white/20 border-t-white rounded-full animate-spin mx-auto" />
                          <p className="text-xs font-mono text-zinc-400">Connecting to AI agent...</p>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <Phone className="w-6 h-6 text-zinc-600 mx-auto mb-2 opacity-50" />
                          <p className="text-xs text-zinc-400 font-medium">Click "Make a Call Now" to begin</p>
                          <p className="text-[11px] text-zinc-600 font-sans">
                            Speak naturally into your microphone to have a real two-way conversation.
                          </p>
                        </div>
                      )}
                    </div>
                  ) : (
                    transcript.map((item) => (
                      <div
                        key={item.id}
                        className={`flex flex-col ${item.sender === 'ai' ? 'items-start' : 'items-end'} animate-fade-in-up`}
                      >
                        <div className="flex items-center gap-1.5 mb-1 text-[10px] font-mono text-zinc-500">
                          <span className={item.sender === 'ai' ? 'text-zinc-200 font-semibold' : 'text-zinc-400'}>
                            {item.sender === 'ai' ? 'DIAL-a-DEAL AI' : (callerName.trim() || 'You')}
                          </span>
                          <span>·</span>
                          <span>{item.timestamp}</span>
                        </div>

                        <div
                          className={`max-w-[85%] p-3 rounded-2xl text-xs sm:text-[13px] leading-relaxed ${
                            item.sender === 'ai'
                              ? 'bg-zinc-900 border border-white/10 text-zinc-100 rounded-tl-xs'
                              : 'bg-white text-black font-medium rounded-tr-xs shadow-md'
                          }`}
                        >
                          {item.text}
                        </div>
                      </div>
                    ))
                  )}

                  {/* Transcript typing indicator during AI speaking */}
                  {callState === 'speaking' && (
                    <div className="flex items-center gap-1.5 text-zinc-500 text-[10px] font-mono pl-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-zinc-300 animate-bounce" />
                      <span className="w-1.5 h-1.5 rounded-full bg-zinc-300 animate-bounce" style={{ animationDelay: '0.15s' }} />
                      <span className="w-1.5 h-1.5 rounded-full bg-zinc-300 animate-bounce" style={{ animationDelay: '0.3s' }} />
                      <span className="ml-1 text-zinc-400">Agent speaking...</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Inline Email Confirmation Box when Agent asks for Email to schedule meeting */}
              {showEmailInput && callState !== 'idle' && callState !== 'ended' && (
                <form
                  onSubmit={handleConfirmEmail}
                  className="mt-4 p-3.5 rounded-2xl bg-zinc-900/90 border border-emerald-500/30 space-y-2 animate-fade-in-up"
                >
                  <div className="text-[11px] font-mono text-emerald-400">
                    Enter your email address for the calendar invite &amp; confirmation:
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="email"
                      value={emailInput}
                      onChange={(e) => {
                        setEmailInput(e.target.value);
                        if (emailError) setEmailError('');
                      }}
                      placeholder="name@company.com"
                      autoFocus
                      className="flex-1 px-3 py-2 rounded-xl bg-black/70 border border-white/15 text-white text-xs font-sans focus:outline-none focus:border-emerald-400"
                    />
                    <button
                      type="submit"
                      className="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-xs transition-colors cursor-pointer"
                    >
                      Confirm
                    </button>
                  </div>
                  {emailError && <div className="text-[11px] font-mono text-red-400">{emailError}</div>}
                </form>
              )}

              {/* Call Summary Banner when call completes */}
              {callState === 'ended' && (
                <div className="mt-4 p-3.5 rounded-xl bg-zinc-900/90 border border-emerald-500/30 flex items-center justify-between text-xs animate-fade-in-up">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                    <div>
                      <div className="text-white font-semibold">
                        {callSummary?.booked ? 'Appointment Booked ✓' : 'Call Saved in Database'}
                      </div>
                      <div className="text-[11px] text-zinc-400 font-mono">
                        {callSummary?.note || `Caller: ${callerName.trim() || 'Caller'} · Duration: ${formatTime(callSeconds)}`}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={handleReset}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white text-black font-semibold text-xs hover:bg-zinc-200 transition-colors"
                  >
                    <RotateCcw className="w-3 h-3" />
                    Reset
                  </button>
                </div>
              )}

              {/* Call Control Buttons (Tap-to-Speak Microphone, Speaker, End Call) */}
              <div className="mt-6 pt-5 border-t border-white/[0.08] flex items-center justify-between gap-3">
                {/* Left: Tap-to-Speak Microphone & Speaker toggle */}
                <div className="flex items-center gap-2.5">
                  <button
                    disabled={callState === 'idle' || callState === 'ended'}
                    onClick={handleMicToggle}
                    title={isMicActive ? 'Finish Speaking & Send' : 'Click to Speak'}
                    className={`h-11 px-4 rounded-2xl border flex items-center justify-center gap-2 text-xs font-semibold transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                      isMicActive
                        ? 'bg-emerald-500/20 border-emerald-400 text-emerald-300 shadow-lg shadow-emerald-500/20 animate-pulse'
                        : 'bg-zinc-900 border-white/15 text-zinc-200 hover:text-white hover:bg-zinc-800 hover:border-white/30'
                    }`}
                  >
                    <Mic className="w-4 h-4" />
                    <span>{isMicActive ? 'Send' : 'Speak'}</span>
                  </button>

                  <button
                    disabled={callState === 'idle' || callState === 'ended'}
                    onClick={handleSpeakerToggle}
                    title={isSpeakerOn ? 'Mute Audio Speaker' : 'Enable Audio Speaker'}
                    className={`w-11 h-11 rounded-2xl border flex items-center justify-center transition-all ${
                      !isSpeakerOn
                        ? 'bg-zinc-800 border-white/20 text-zinc-500'
                        : 'bg-zinc-900 border-white/10 text-zinc-300 hover:text-white hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed'
                    }`}
                  >
                    {isSpeakerOn ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
                  </button>
                </div>

                {/* Right: End / Action Call Trigger */}
                {callState === 'idle' || callState === 'ended' ? (
                  <button
                    onClick={handleStartCall}
                    className="flex-1 py-3 px-5 rounded-2xl bg-white hover:bg-zinc-200 text-black font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all shadow-md cursor-pointer"
                  >
                    <Phone className="w-3.5 h-3.5 fill-black" />
                    <span>Launch Voice Call</span>
                  </button>
                ) : (
                  <button
                    onClick={handleEndCall}
                    className="flex-1 py-3 px-5 rounded-2xl bg-red-600 hover:bg-red-500 text-white font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all shadow-lg shadow-red-600/30 cursor-pointer"
                  >
                    <PhoneOff className="w-4 h-4" />
                    <span>End Call</span>
                  </button>
                )}
              </div>

            </div>

          </div>

        </div>
      </div>
    </section>
  );
};
