import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock3,
  LoaderCircle,
  Mic,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

import { fetchCapabilities, sendFeedback, streamChat } from '../../api/client';
import type { Capabilities, ChatResponse, MapAction } from '../../api/types';

interface ChatPanelProps {
  open: boolean;
  onClose: () => void;
  onApply: (action: MapAction) => void;
  onNotify: (title: string, detail?: string, kind?: 'info' | 'success' | 'warning') => void;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  response?: ChatResponse;
}

export function ChatPanel({ open, onClose, onApply, onNotify }: ChatPanelProps) {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    fetchCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
    return () => abortRef.current?.abort();
  }, []);
  useEffect(() => {
    if (messages.length > 0 || status) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, status]);

  const sendPrompt = async (content: string) => {
    if (!content || busy || !capabilities?.chat) return;
    let transcript = [...messages, { role: 'user' as const, content }];
    while (transcript.length > 11 || transcript[0]?.role !== 'user') transcript = transcript.slice(1);
    setMessages(transcript);
    setInput('');
    setBusy(true);
    setError(null);
    setStatus('Starting analysis');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await streamChat(
        transcript.map(({ role, content: value }) => ({ role, content: value })),
        (name, payload) => {
          if (name === 'step_started') setStatus('Running analysis');
          if (name === 'step_completed') setStatus((payload as { detail: string }).detail);
        },
        controller.signal,
      );
      setMessages([...transcript, { role: 'assistant', content: response.reply, response }]);
      setStatus('');
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Assistant failed');
    } finally {
      setBusy(false);
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void sendPrompt(input.trim());
  };
  const latestResponse = [...messages].reverse().find((message) => message.response)?.response;

  return (
    <aside className={`chat-panel ${open ? 'open' : ''}`} aria-hidden={!open} inert={!open}>
      <header className="chat-header">
        <div className="copilot-title"><Sparkles size={18} /><h2>AI Copilot <span>BETA</span></h2></div>
        <button className="icon-button quiet" type="button" title="Close copilot" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="chat-scroll">
        <form className="copilot-prompt" onSubmit={submit}>
          <span>Ask anything about the market</span>
          <textarea
            aria-label="Ask the property assistant"
            maxLength={500}
            rows={3}
            placeholder="Find undervalued terraced homes near stations with recent planning activity."
            value={input}
            onChange={(event) => setInput(event.target.value)}
            disabled={busy || !capabilities?.chat}
          />
          <div className="prompt-actions">
            <Mic size={17} />
            <button className="run-agent-button" type="submit" title="Send message" disabled={busy || !input.trim() || !capabilities?.chat}>
              {busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />} Run agent
            </button>
            <Send className="send-hint" size={16} />
          </div>
        </form>

        <section className="agent-process-card" aria-label="Agent process">
          <div className="card-heading">
            <span>{busy ? 'Agent is running...' : 'Agent process'}</span>
            <button type="button" onClick={() => latestResponse ? setExpanded(expanded === latestResponse.run_id ? null : latestResponse.run_id) : onNotify('No agent run yet', 'Ask a market question to see execution steps.', 'info')}>View details <ArrowRight size={13} /></button>
          </div>
          <ol className="agent-steps">
            <li className="done"><CheckCircle2 size={17} /><span>Scanning visible map area</span><b>Completed</b></li>
            <li className={messages.length || busy ? 'done' : ''}>{messages.length || busy ? <CheckCircle2 size={17} /> : <Circle size={17} />}<span>Analyzing price anomalies</span><b>{messages.length || busy ? 'Completed' : 'Ready'}</b></li>
            <li className={busy ? 'active' : ''}>{busy ? <LoaderCircle className="spin" size={17} /> : <Clock3 size={17} />}<span>Checking planning applications</span><b>{busy ? 'In progress' : 'Pending'}</b></li>
            <li><Circle size={17} /><span>Preparing investment summary</span><b>Pending</b></li>
          </ol>
        </section>

        <div className="chat-transcript" aria-live="polite">
          {messages.length === 0 && <div className="chat-empty"><strong>Try a market question</strong><span>SQL answers stay grounded in local transactions. RAG citations are used for methodology and limitations.</span></div>}
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`message ${message.role}`}>
              <p>{message.content}</p>
              {message.response?.citations.map((citation) => (
                <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer">{citation.publisher}: {citation.title}{citation.section ? ` · ${citation.section}` : ''}</a>
              ))}
              {message.response?.map_action && (
                <button className="apply-button" type="button" onClick={() => onApply(message.response!.map_action!)}><Check size={16} /> {message.response.map_action.label}</button>
              )}
              {message.response && (
                <div className="response-meta">
                  <button type="button" onClick={() => setExpanded(expanded === message.response!.run_id ? null : message.response!.run_id)}>
                    {expanded === message.response.run_id ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {message.response.steps.length} steps · {message.response.metrics.latency_ms} ms
                  </button>
                  {capabilities?.feedback && <><button type="button" title="Helpful" onClick={() => void sendFeedback(message.response!.run_id, 1).then(() => onNotify('Feedback sent', 'Marked helpful.', 'success')).catch(() => onNotify('Feedback unavailable', 'LangSmith feedback is not active locally.', 'warning'))}><ThumbsUp size={14} /></button><button type="button" title="Not helpful" onClick={() => void sendFeedback(message.response!.run_id, -1).then(() => onNotify('Feedback sent', 'Marked not helpful.', 'success')).catch(() => onNotify('Feedback unavailable', 'LangSmith feedback is not active locally.', 'warning'))}><ThumbsDown size={14} /></button></>}
                </div>
              )}
              {message.response && expanded === message.response.run_id && <ol className="steps-list">{message.response.steps.map((step) => <li key={`${step.name}-${step.duration_ms}`}><span>{step.name.replaceAll('_', ' ')}</span><small>{step.detail} · {step.duration_ms} ms</small></li>)}</ol>}
            </div>
          ))}
          {busy && <div className="message assistant pending">{status}</div>}
          {error && <p className="error-copy">{error}</p>}
          {!capabilities?.chat && capabilities && <p className="muted">Assistant unavailable in this environment.</p>}
          <div ref={bottomRef} />
        </div>

        <section className="ai-insights-card">
          <div className="card-heading"><span>AI insights</span><small>3 new</small></div>
          <button type="button" onClick={() => void sendPrompt('Highlight SE1 on the map.')}><strong>Undervalued pocket in SE1</strong><span>Avg. £640k (-12%) vs predicted value</span><b>High confidence</b></button>
          <button type="button" onClick={() => void sendPrompt('Highlight N1 on the map.')}><strong>High growth area: N1</strong><span>+11% p.a. growth YoY</span><b>High confidence</b></button>
          <button type="button" onClick={() => void sendPrompt('Explain planning activity spike in E2 using the loaded market data.')}><strong>Planning activity spike in E2</strong><span>+32% vs last 12 months</span><b className="medium">Medium confidence</b></button>
        </section>

        <section className="suggested-actions-card">
          <div className="card-heading"><span>Suggested actions</span></div>
          <div className="action-grid">
            <button type="button" onClick={() => onNotify('Watchlist created', 'Current AI criteria saved for this session.', 'success')}>Create watchlist</button>
            <button type="button" onClick={() => void sendPrompt('Generate a concise area report for the visible London property map.')}>Generate area report</button>
            <button type="button" onClick={() => void sendPrompt('Explain the price spike in E2 using the loaded sales data.')}>Explain price spike</button>
            <button type="button" onClick={() => void sendPrompt('Find similar property deals under £800k in SW11.')}>Find similar deals</button>
          </div>
          <small>AI can make mistakes. Verify important information.</small>
        </section>
      </div>
    </aside>
  );
}
