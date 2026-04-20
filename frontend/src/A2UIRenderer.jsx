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

function polarToCartesian(cx, cy, radius, angle) {
  const radians = (angle - 90) * (Math.PI / 180);
  return {
    x: cx + radius * Math.cos(radians),
    y: cy + radius * Math.sin(radians),
  };
}

function describeDonutSlice(cx, cy, outerRadius, innerRadius, startAngle, endAngle) {
  const outerStart = polarToCartesian(cx, cy, outerRadius, startAngle);
  const outerEnd = polarToCartesian(cx, cy, outerRadius, endAngle);
  const innerEnd = polarToCartesian(cx, cy, innerRadius, endAngle);
  const innerStart = polarToCartesian(cx, cy, innerRadius, startAngle);
  const largeArcFlag = endAngle - startAngle > 180 ? 1 : 0;

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

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
  const subtitle = spec.subtitle || (spec.dataModel ? "請填寫以下資訊" : "");

  return (
    <div className="a2ui-surface">
      {titleComp && (
        <>
          <div className="a2ui-surface-title">{titleComp.component.text}</div>
          {subtitle && <div className="a2ui-surface-subtitle">{subtitle}</div>}
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
    case "BarChart":   return <BarChartComp spec={comp.component} />;
    case "PieChart":   return <PieChartComp spec={comp.component} />;
    case "StackedBarChart": return <StackedBarChartComp spec={comp.component} />;
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

function BarChartComp({ spec }) {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xKey = spec.xKey || "label";
  const yKey = spec.yKey || "value";
  const maxValue = data.length > 0 ? Math.max(...data.map((item) => Number(item[yKey]) || 0), 1) : 1;

  return (
    <div className="a2ui-chart">
      {spec.title && <div className="a2ui-chart-title">{spec.title}</div>}
      {spec.description && <p className="a2ui-chart-description">{spec.description}</p>}
      {data.length === 0 ? (
        <div className="a2ui-chart-empty">{spec.emptyText || "目前沒有可顯示的圖表資料"}</div>
      ) : (
        <div className="a2ui-chart-bars">
          {data.map((item, index) => {
            const label = String(item[xKey] ?? "");
            const value = Number(item[yKey]) || 0;
            const width = `${Math.max((value / maxValue) * 100, 4)}%`;
            return (
              <div className="a2ui-chart-row" key={`${label}-${index}`}>
                <div className="a2ui-chart-label" title={label}>{label}</div>
                <div className="a2ui-chart-track">
                  <div className="a2ui-chart-bar" style={{ width }} />
                  <span className="a2ui-chart-value">{value}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PieChartComp({ spec }) {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const labelKey = spec.labelKey || "label";
  const valueKey = spec.valueKey || "value";
  const palette = ["#2A6AB5", "#4D89CD", "#74A9E0", "#F2B544", "#E07A5F", "#7C9A67", "#8C6BB1", "#59A5D8"];
  const total = data.reduce((sum, item) => sum + (Number(item[valueKey]) || 0), 0);
  const [activeIndex, setActiveIndex] = useState(-1);

  if (data.length === 0 || total <= 0) {
    return (
      <div className="a2ui-chart">
        {spec.title && <div className="a2ui-chart-title">{spec.title}</div>}
        {spec.description && <p className="a2ui-chart-description">{spec.description}</p>}
        <div className="a2ui-chart-empty">{spec.emptyText || "目前沒有可顯示的圖表資料"}</div>
      </div>
    );
  }

  let cumulative = 0;
  const segments = data.map((item, index) => {
    const value = Number(item[valueKey]) || 0;
    const percentage = value / total;
    const start = cumulative;
    cumulative += percentage;
    return {
      label: String(item[labelKey] ?? ""),
      value,
      percent: percentage,
      color: palette[index % palette.length],
      start,
      end: cumulative,
    };
  });

  const gradient = segments
    .map((segment) => {
      const start = (segment.start * 100).toFixed(2);
      const end = (segment.end * 100).toFixed(2);
      return `${segment.color} ${start}% ${end}%`;
    })
    .join(", ");

  const activeSegment = activeIndex >= 0 ? segments[activeIndex] : null;
  const chartSize = 240;
  const center = chartSize / 2;
  const outerRadius = 120;
  const innerRadius = 56;

  return (
    <div className="a2ui-chart">
      {spec.title && <div className="a2ui-chart-title">{spec.title}</div>}
      {spec.description && <p className="a2ui-chart-description">{spec.description}</p>}
      <div className="a2ui-pie-layout">
        <div className="a2ui-pie-wrap">
          <div
            className={`a2ui-pie-chart${activeSegment ? " is-hovering" : ""}`}
            style={{ background: `conic-gradient(${gradient})` }}
            aria-label={spec.title || "pie chart"}
          >
            <svg className="a2ui-pie-hitmap" viewBox={`0 0 ${chartSize} ${chartSize}`} aria-hidden="true">
            {segments.map((segment, index) => (
              <path
                key={segment.label}
                className={`a2ui-pie-hit${activeIndex === index ? " is-active" : ""}`}
                d={describeDonutSlice(
                  center,
                  center,
                  outerRadius,
                  innerRadius,
                  segment.start * 360,
                  segment.end * 360,
                )}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseLeave={() => setActiveIndex(-1)}
                onFocus={() => setActiveIndex(index)}
                onBlur={() => setActiveIndex(-1)}
              />
            ))}
            </svg>
            <div className="a2ui-pie-center">
              <div className="a2ui-pie-total-label">
                {activeSegment ? activeSegment.label : "總次數"}
              </div>
              <div className="a2ui-pie-total-value">
                {activeSegment ? activeSegment.value : total}
              </div>
              <div className="a2ui-pie-total-subvalue">
                {activeSegment ? `${(activeSegment.percent * 100).toFixed(1)}%` : `${segments.length} 個 user_id`}
              </div>
            </div>
          </div>
        </div>
        <div className="a2ui-pie-legend">
          {segments.map((segment, index) => (
            <button
              type="button"
              className={`a2ui-pie-legend-row${activeIndex === index ? " is-active" : ""}`}
              key={segment.label}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseLeave={() => setActiveIndex(-1)}
              onFocus={() => setActiveIndex(index)}
              onBlur={() => setActiveIndex(-1)}
            >
              <div className="a2ui-pie-legend-label">
                <span
                  className="a2ui-pie-legend-swatch"
                  style={{ backgroundColor: segment.color }}
                />
                <span title={segment.label}>{segment.label}</span>
              </div>
              <div className="a2ui-pie-legend-metrics">
                <span>{segment.value} 次</span>
                <span>{(segment.percent * 100).toFixed(1)}%</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function StackedBarChartComp({ spec }) {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const xKey = spec.xKey || "label";
  const series = Array.isArray(spec.series) ? spec.series : [];
  const palette = ["#2A6AB5", "#4D89CD", "#74A9E0", "#F2B544", "#E07A5F", "#7C9A67", "#8C6BB1"];
  const totals = data.map((item) =>
    series.reduce((sum, key) => sum + (Number(item[key]) || 0), 0)
  );
  const maxTotal = totals.length > 0 ? Math.max(...totals, 1) : 1;

  return (
    <div className="a2ui-chart">
      {spec.title && <div className="a2ui-chart-title">{spec.title}</div>}
      {spec.description && <p className="a2ui-chart-description">{spec.description}</p>}
      {data.length === 0 ? (
        <div className="a2ui-chart-empty">{spec.emptyText || "目前沒有可顯示的圖表資料"}</div>
      ) : (
        <>
          <div className="a2ui-stacked-legend">
            {series.map((key, index) => (
              <div className="a2ui-stacked-legend-item" key={key}>
                <span
                  className="a2ui-stacked-legend-swatch"
                  style={{ backgroundColor: palette[index % palette.length] }}
                />
                <span>{key}</span>
              </div>
            ))}
          </div>
          <div className="a2ui-chart-bars">
            {data.map((item, index) => {
              const label = String(item[xKey] ?? "");
              const total = series.reduce((sum, key) => sum + (Number(item[key]) || 0), 0);
              return (
                <div className="a2ui-chart-row" key={`${label}-${index}`}>
                  <div className="a2ui-chart-label" title={label}>{label}</div>
                  <div className="a2ui-chart-track">
                    <div
                      className="a2ui-stacked-chart-bar"
                      style={{ width: `${Math.max((total / maxTotal) * 100, 4)}%` }}
                    >
                      {series.map((key, seriesIndex) => {
                        const value = Number(item[key]) || 0;
                        if (value <= 0 || total <= 0) return null;
                        return (
                          <div
                            key={key}
                            className="a2ui-stacked-chart-segment"
                            title={`${key}: ${value}`}
                            style={{
                              width: `${(value / total) * 100}%`,
                              backgroundColor: palette[seriesIndex % palette.length],
                            }}
                          />
                        );
                      })}
                    </div>
                    <span className="a2ui-chart-value">{total}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
