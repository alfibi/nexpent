import { useState, useEffect, useRef } from "react";
import { Send, Sparkles, Target, BarChart2, Landmark, Lightbulb } from 'lucide-react';
import { apiRequest } from "../lib/api";
import { loadCachedResource, readCachedResource } from "../lib/resourceCache";

export default function Advisor() {
  const [insights, setInsights] = useState(() => readCachedResource("aiInsights")?.insights || []);
  const [chatHistory, setChatHistory] = useState([
    { role: "assistant", content: "Hi! I've analyzed your finances. What would you like to explore?" }
  ]);
  const [message, setMessage] = useState("");
  const [loadingChat, setLoadingChat] = useState(false);
  const chatEndRef = useRef(null);

  useEffect(() => {
    async function fetchInsights() {
      try {
        const res = await loadCachedResource("aiInsights");
        setInsights(res.insights || []);
      } catch (err) {
        console.error(err);
      }
    }
    fetchInsights();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  async function handleSend() {
    if (!message.trim()) return;
    const userMsg = { role: "user", content: message };
    setChatHistory(prev => [...prev, userMsg]);
    setMessage("");
    setLoadingChat(true);

    try {
      const res = await apiRequest("/api/ai/chat", {
        method: "POST",
        body: { message: userMsg.content }
      });
      setChatHistory(prev => [...prev, { role: "assistant", content: res.message }]);
    } catch (err) {
      setChatHistory(prev => [...prev, { role: "assistant", content: "Error connecting to advisor." }]);
    } finally {
      setLoadingChat(false);
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <div style={{ fontSize: "12px", color: "var(--text3)", marginBottom: "2px" }}>Powered by AI</div>
          <div className="page-title">Advisor</div>
        </div>
        <div style={{ width: "40px", height: "40px", borderRadius: "12px", background: "linear-gradient(135deg, var(--accent), var(--accent2))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "20px" }}><Sparkles size={16} color="white" /></div>
      </div>
      
      {insights.length > 0 && insights.slice(0, 2).map((ins, idx) => (
        <div key={ins.id} className="ai-insight" style={idx % 2 !== 0 ? { background: "linear-gradient(135deg, rgba(16,217,160,0.1), rgba(16,217,160,0.05))", borderColor: "rgba(16,217,160,0.2)" } : {}}>
          <div className="ai-badge" style={idx % 2 !== 0 ? { background: "rgba(16,217,160,0.15)", color: "var(--accent3)" } : {}}><Sparkles size={16} /> {ins.title}</div>
          <div style={{ fontSize: "14px", color: "var(--text)", lineHeight: 1.5 }}>
            {ins.summary}
          </div>
        </div>
      ))}
      {insights.length === 0 && (
         <div style={{ padding: "10px", textAlign: "center", color: "var(--text3)", fontSize: "13px", fontStyle: "italic", marginBottom: "20px" }}>
           Start a chat below to generate personalized insights.
         </div>
      )}
      
      <div style={{ marginBottom: "20px", marginTop: "24px", height: "300px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "10px", paddingRight: "10px" }}>
        {chatHistory.map((msg, idx) => (
          <div key={idx} className="chat-msg" style={{ textAlign: msg.role === 'user' ? 'right' : 'left' }}>
            {msg.role === 'assistant' && <div className="chat-name">Nexpent AI</div>}
            <div className={`chat-bubble chat-${msg.role === 'user' ? 'user' : 'ai'}`}>
              {msg.content}
            </div>
          </div>
        ))}
        {loadingChat && (
          <div className="chat-msg">
            <div className="chat-name">Nexpent AI</div>
            <div className="chat-bubble chat-ai">
              <span className="pulse" style={{ display: 'inline-block', width: '8px', height: '8px', background: 'var(--text2)', borderRadius: '50%', marginRight: '4px' }}></span>
              <span className="pulse" style={{ display: 'inline-block', width: '8px', height: '8px', background: 'var(--text2)', borderRadius: '50%', marginRight: '4px', animationDelay: '0.2s' }}></span>
              <span className="pulse" style={{ display: 'inline-block', width: '8px', height: '8px', background: 'var(--text2)', borderRadius: '50%', animationDelay: '0.4s' }}></span>
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>
      
      <div className="chat-chips">
        <div className="chip" onClick={() => setMessage("Monthly summary")}><BarChart2 size={16} /> Monthly summary</div>
        <div className="chip" onClick={() => setMessage("How to save $500/mo?")}><Lightbulb size={16} /> Save $500/mo</div>
        <div className="chip" onClick={() => setMessage("Give me investment tips")}><Landmark size={16} /> Invest tips</div>
      </div>
      
      <div className="chat-input-row">
        <input 
           className="chat-input" 
           placeholder="Ask anything about your finances…" 
           value={message}
           onChange={e => setMessage(e.target.value)}
           onKeyDown={e => e.key === 'Enter' && handleSend()}
           disabled={loadingChat}
        />
        <button className="chat-send" onClick={handleSend} disabled={loadingChat || !message.trim()}><Send size={16} /></button>
      </div>
    </>
  );
}
