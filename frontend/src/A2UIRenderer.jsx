/**
 * A2UIRenderer.jsx — A2UI JSON Blueprint → React Components
 *
 * 核心概念：
 *   後端送來的不是 HTML，而是描述「應顯示哪些元件」的 JSON blueprint。
 *   Renderer 根據 component.type 映射到對應的 React 元件，
 *   並透過 binding path 實現雙向資料綁定（React state）。
 *
 *   Button 按下時，依 action.context 從 state 收集資料，
 *   透過 onAction(actionName, data) 送回後端。
 */

import { useState, useCallback } from "react";

// ── 主元件：Surface ──────────────────────────────────────

export default function A2UISurface({ spec, onAction }) {
  // 深拷貝 dataModel 作為 React state（雙向綁定）
  const [model, setModel] = useState(() =>
    spec.dataModel ? JSON.parse(JSON.stringify(spec.dataModel)) : {}
  );
  const [submitted, setSubmitted] = useState(false);

  // 更新 model 中的某個路徑值 "/booking/name" → model.booking.name
  const setByPath = useCallback((path, value) => {
    if (!path) return;
    setModel((prev) => {
      const next = JSON.parse(JSON.stringify(prev));
      const parts = path.split("/").filter(Boolean);
      let obj = next;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!(parts[i] in obj)) obj[parts[i]] = {};
        obj = obj[parts[i]];
      }
      obj[parts[parts.length - 1]] = value;
      return next;
    });
  }, []);

  // 從 model 讀取某個路徑的值
  const getByPath = useCallback(
    (path) => {
      if (!path) return "";
      const parts = path.split("/").filter(Boolean);
      let obj = model;
      for (const p of parts) {
        if (obj == null) return "";
        obj = obj[p];
      }
      return obj ?? "";
    },
    [model]
  );

  // Button 觸發 action
  const handleAction = useCallback(
    (actionName, contextDef) => {
      if (submitted) return;
      setSubmitted(true);
      const data = {};
      for (const ctx of contextDef) {
        data[ctx.key] = getByPath(ctx.binding);
      }
      onAction(actionName, data);
    },
    [submitted, getByPath, onAction]
  );

  // 找第一個 Text h2/h3 作為 title
  const titleComp = spec.components.find(
    (c) => c.component.type === "Text" && (c.component.variant === "h2" || c.component.variant === "h3")
  );
  const otherComps = spec.components.filter((c) => c !== titleComp);

  return (
    <div className="a2ui-surface">
      {titleComp && (
        <>
          <div className="a2ui-surface-title">{titleComp.component.text}</div>
          <div className="a2ui-surface-subtitle">請填寫以下資訊</div>
        </>
      )}
      {otherComps.map((comp) => (
        <ComponentRenderer
          key={comp.id}
          comp={comp}
          getByPath={getByPath}
          setByPath={setByPath}
          onAction={handleAction}
          submitted={submitted}
        />
      ))}
    </div>
  );
}

// ── 元件分派 ──────────────────────────────────────────────

function ComponentRenderer({ comp, getByPath, setByPath, onAction, submitted }) {
  const { type } = comp.component;
  switch (type) {
    case "Text":       return <TextComp spec={comp.component} />;
    case "TextField":  return <TextFieldComp spec={comp.component} getByPath={getByPath} setByPath={setByPath} />;
    case "TextArea":   return <TextAreaComp spec={comp.component} getByPath={getByPath} setByPath={setByPath} />;
    case "DateInput":  return <DateInputComp spec={comp.component} getByPath={getByPath} setByPath={setByPath} />;
    case "Select":     return <SelectComp spec={comp.component} getByPath={getByPath} setByPath={setByPath} />;
    case "Rating":     return <RatingComp spec={comp.component} getByPath={getByPath} setByPath={setByPath} />;
    case "Button":     return <ButtonComp spec={comp.component} onAction={onAction} submitted={submitted} />;
    case "Card":       return <CardComp spec={comp.component} />;
    default:           return <p style={{ color: "#767676", fontSize: "0.82rem" }}>[未知元件: {type}]</p>;
  }
}

// ── Text ──────────────────────────────────────────────────

function TextComp({ spec }) {
  // title 已由 Surface 處理，其他 Text (subtitle / body) 才顯示
  if (spec.variant === "h2" || spec.variant === "h3") return null;
  if (spec.variant === "subtitle") {
    return <p style={{ fontSize: "0.85rem", color: "#8C1515", marginBottom: 10 }}>{spec.text}</p>;
  }
  return <p style={{ fontSize: "0.9rem", marginBottom: 8 }}>{spec.text}</p>;
}

// ── TextField ─────────────────────────────────────────────

function TextFieldComp({ spec, getByPath, setByPath }) {
  return (
    <div className="a2ui-field">
      <label>
        {spec.label}
        {spec.required && <span className="req">*</span>}
      </label>
      <input
        type="text"
        placeholder={spec.placeholder || ""}
        value={getByPath(spec.binding)}
        onChange={(e) => setByPath(spec.binding, e.target.value)}
      />
    </div>
  );
}

// ── TextArea ──────────────────────────────────────────────

function TextAreaComp({ spec, getByPath, setByPath }) {
  return (
    <div className="a2ui-field">
      <label>
        {spec.label}
        {spec.required && <span className="req">*</span>}
      </label>
      <textarea
        placeholder={spec.placeholder || ""}
        rows={spec.rows || 3}
        value={getByPath(spec.binding)}
        onChange={(e) => setByPath(spec.binding, e.target.value)}
      />
    </div>
  );
}

// ── DateInput ─────────────────────────────────────────────

function DateInputComp({ spec, getByPath, setByPath }) {
  return (
    <div className="a2ui-field">
      <label>
        {spec.label}
        {spec.required && <span className="req">*</span>}
      </label>
      <input
        type="date"
        value={getByPath(spec.binding)}
        onChange={(e) => setByPath(spec.binding, e.target.value)}
      />
    </div>
  );
}

// ── Select ────────────────────────────────────────────────

function SelectComp({ spec, getByPath, setByPath }) {
  const current = getByPath(spec.binding) || spec.defaultValue || "";
  return (
    <div className="a2ui-field">
      <label>
        {spec.label}
        {spec.required && <span className="req">*</span>}
      </label>
      <select
        value={current}
        onChange={(e) => setByPath(spec.binding, e.target.value)}
      >
        <option value="" disabled>請選擇…</option>
        {spec.options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

// ── Rating ────────────────────────────────────────────────

function RatingComp({ spec, getByPath, setByPath }) {
  const max = spec.maxStars || 5;
  const current = parseInt(getByPath(spec.binding) || "5", 10);
  return (
    <div className="a2ui-field">
      <label>
        {spec.label}
        {spec.required && <span className="req">*</span>}
      </label>
      <div className="a2ui-rating">
        {Array.from({ length: max }, (_, i) => (
          <button
            key={i}
            type="button"
            className={i < current ? "active" : ""}
            onClick={() => setByPath(spec.binding, String(i + 1))}
          >
            {i < current ? "★" : "☆"}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Button ────────────────────────────────────────────────

function ButtonComp({ spec, onAction, submitted }) {
  return (
    <button
      type="button"
      className={`a2ui-btn ${spec.variant || ""}`}
      disabled={submitted}
      onClick={() => onAction(spec.action.name, spec.action.context || [])}
    >
      {submitted ? "已送出" : spec.label}
    </button>
  );
}

// ── Card ──────────────────────────────────────────────────

function CardComp({ spec }) {
  return (
    <div className="a2ui-card">
      {(spec.children || []).map((child, i) => (
        <p key={i}>{child.text}</p>
      ))}
    </div>
  );
}
