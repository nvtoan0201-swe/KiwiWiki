// KiwiWiki design-system primitives, recreated from the design handoff bundle
// (components/core + components/research). Styling lives in the kw-* classes
// shipped in styles/components.css; these components only compose classnames.

import { icons } from "lucide-react";
import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { useId } from "react";

// ---------- Icon ----------

function pascal(name: string): string {
  return name
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
}

export interface IconProps {
  name: string;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

/** Lucide line icon at the brand stroke (1.75). */
export function Icon({ name, size = 18, strokeWidth = 1.75, className }: IconProps) {
  const Glyph = icons[pascal(name) as keyof typeof icons];
  if (!Glyph) return null;
  return <Glyph size={size} strokeWidth={strokeWidth} className={className} aria-hidden="true" />;
}

// ---------- Button ----------

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  iconLeft?: string;
  iconRight?: string;
  block?: boolean;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  iconLeft,
  iconRight,
  block = false,
  type = "button",
  className = "",
  ...rest
}: ButtonProps) {
  const cls = [
    "kw-btn",
    `kw-btn--${variant}`,
    `kw-btn--${size}`,
    block ? "kw-btn--block" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type={type} className={cls} {...rest}>
      {iconLeft && <Icon name={iconLeft} size={size === "lg" ? 18 : 15} />}
      {children}
      {iconRight && <Icon name={iconRight} size={size === "lg" ? 18 : 15} />}
    </button>
  );
}

// ---------- IconButton ----------

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: string;
  label: string;
  variant?: "plain" | "outline" | "solid";
  size?: "sm" | "md" | "lg";
}

export function IconButton({
  icon,
  label,
  variant = "plain",
  size = "md",
  className = "",
  ...rest
}: IconButtonProps) {
  const cls = [
    "kw-iconbtn",
    `kw-iconbtn--${size}`,
    variant !== "plain" ? `kw-iconbtn--${variant}` : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type="button" className={cls} aria-label={label} title={label} {...rest}>
      <Icon name={icon} size={size === "sm" ? 16 : 18} />
    </button>
  );
}

// ---------- Badge ----------

export type BadgeTone = "neutral" | "accent" | "positive" | "warning" | "danger" | "info" | "solid";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  icon?: string;
  dot?: boolean;
}

export function Badge({
  children,
  tone = "neutral",
  icon,
  dot = false,
  className = "",
  ...rest
}: BadgeProps) {
  const cls = ["kw-badge", `kw-badge--${tone}`, className].filter(Boolean).join(" ");
  return (
    <span className={cls} {...rest}>
      {dot && <span className="kw-badge__dot" />}
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

// ---------- Tag ----------

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  onRemove?: () => void;
}

export function Tag({ children, onRemove, className = "", ...rest }: TagProps) {
  return (
    <span className={["kw-tag", className].filter(Boolean).join(" ")} {...rest}>
      {children}
      {onRemove && (
        <span className="kw-tag__x" role="button" aria-label="Remove" onClick={onRemove}>
          <Icon name="x" size={13} />
        </span>
      )}
    </span>
  );
}

// ---------- Card ----------

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "flat" | "raised";
  interactive?: boolean;
  pad?: boolean;
}

export function Card({
  children,
  variant = "default",
  interactive = false,
  pad = false,
  className = "",
  ...rest
}: CardProps) {
  const cls = [
    "kw-card",
    variant !== "default" ? `kw-card--${variant}` : "",
    interactive ? "kw-card--interactive" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} {...rest}>
      {pad ? <div className="kw-card__pad">{children}</div> : children}
    </div>
  );
}

// ---------- Tabs ----------

export interface TabItem {
  id: string;
  label: string;
  icon?: string;
  count?: number;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ items, value, onChange, className = "" }: TabsProps) {
  return (
    <div className={["kw-tabs", className].filter(Boolean).join(" ")} role="tablist">
      {items.map((it) => {
        const active = it.id === value;
        return (
          <button
            key={it.id}
            role="tab"
            aria-selected={active}
            className={`kw-tab${active ? " kw-tab--active" : ""}`}
            onClick={() => onChange(it.id)}
          >
            {it.icon && <Icon name={it.icon} size={15} />}
            {it.label}
            {it.count != null && <span className="kw-tab__count">{it.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

// ---------- Input / Textarea ----------

interface FieldChrome {
  label?: string;
  hint?: string;
  error?: string;
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement>, FieldChrome {
  icon?: string;
}

export function Input({ label, hint, error, icon, id, className = "", ...rest }: InputProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const inputCls = ["kw-input", error ? "kw-input--error" : "", className]
    .filter(Boolean)
    .join(" ");
  const control = icon ? (
    <span className="kw-inputwrap">
      <span className="kw-inputwrap__icon">
        <Icon name={icon} size={16} />
      </span>
      <input id={fieldId} className={inputCls} {...rest} />
    </span>
  ) : (
    <input id={fieldId} className={inputCls} {...rest} />
  );
  return (
    <div className="kw-field">
      {label && (
        <label className="kw-field__label" htmlFor={fieldId}>
          {label}
        </label>
      )}
      {control}
      {(hint || error) && (
        <span className={`kw-field__hint${error ? " kw-field__hint--error" : ""}`}>
          {error || hint}
        </span>
      )}
    </div>
  );
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement>, FieldChrome {}

export function Textarea({
  label,
  hint,
  error,
  id,
  rows = 3,
  className = "",
  ...rest
}: TextareaProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const cls = ["kw-input", error ? "kw-input--error" : "", className].filter(Boolean).join(" ");
  return (
    <div className="kw-field">
      {label && (
        <label className="kw-field__label" htmlFor={fieldId}>
          {label}
        </label>
      )}
      <textarea id={fieldId} className={cls} rows={rows} {...rest} />
      {(hint || error) && (
        <span className={`kw-field__hint${error ? " kw-field__hint--error" : ""}`}>
          {error || hint}
        </span>
      )}
    </div>
  );
}

// ---------- Select ----------

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement>, FieldChrome {
  options?: SelectOption[];
}

export function Select({
  label,
  hint,
  options,
  id,
  className = "",
  children,
  ...rest
}: SelectProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <div className="kw-field">
      {label && (
        <label className="kw-field__label" htmlFor={fieldId}>
          {label}
        </label>
      )}
      <span className="kw-selectwrap">
        <select
          id={fieldId}
          className={["kw-input", "kw-select", className].filter(Boolean).join(" ")}
          {...rest}
        >
          {options
            ? options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))
            : children}
        </select>
        <span className="kw-selectwrap__chev">
          <Icon name="chevron-down" size={16} />
        </span>
      </span>
      {hint && <span className="kw-field__hint">{hint}</span>}
    </div>
  );
}

// ---------- Checkbox / Radio / Switch ----------

export interface CheckboxProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
}

export function Checkbox({ label, className = "", ...rest }: CheckboxProps) {
  return (
    <label className={["kw-check", className].filter(Boolean).join(" ")}>
      <input type="checkbox" {...rest} />
      <span className="kw-check__box">
        <Icon name="check" size={13} />
      </span>
      {label && <span className="kw-check__label">{label}</span>}
    </label>
  );
}

export interface RadioProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
}

export function Radio({ label, className = "", ...rest }: RadioProps) {
  return (
    <label className={["kw-check", className].filter(Boolean).join(" ")}>
      <input type="radio" {...rest} />
      <span className="kw-check__box kw-check__box--radio">
        <span className="kw-check__dot" />
      </span>
      {label && <span className="kw-check__label">{label}</span>}
    </label>
  );
}

export interface SwitchProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
}

export function Switch({ label, className = "", ...rest }: SwitchProps) {
  return (
    <label className={["kw-switch", className].filter(Boolean).join(" ")}>
      <input type="checkbox" role="switch" {...rest} />
      <span className="kw-switch__track">
        <span className="kw-switch__thumb" />
      </span>
      {label && <span className="kw-switch__label">{label}</span>}
    </label>
  );
}

// ---------- Research primitives ----------

export interface SourceChipProps extends HTMLAttributes<HTMLSpanElement> {
  n: ReactNode;
}

/** Inline citation marker — the "[4]" that opens a provenance trace. */
export function SourceChip({ n, className = "", ...rest }: SourceChipProps) {
  return (
    <span className={["kw-source", className].filter(Boolean).join(" ")} {...rest}>
      <span className="kw-source__n">{n}</span>
    </span>
  );
}

export interface CitationProps {
  index?: ReactNode;
  title: string;
  source?: string | null;
  meta?: string | null;
  href?: string | null;
  onClick?: () => void;
}

export function Citation({ index, title, source, meta, href, onClick }: CitationProps) {
  return (
    <div className="kw-cite" onClick={onClick} style={onClick ? { cursor: "pointer" } : undefined}>
      {index != null && <span className="kw-cite__idx">{index}</span>}
      <div className="kw-cite__body">
        {href ? (
          <a
            className="kw-cite__title"
            href={href}
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: "none" }}
          >
            {title}
          </a>
        ) : (
          <p className="kw-cite__title">{title}</p>
        )}
        <div className="kw-cite__meta">
          {source && <span className="kw-cite__src">{source}</span>}
          {source && meta ? " · " : ""}
          {meta}
        </div>
      </div>
    </div>
  );
}

const CALLOUT_ICONS: Record<string, string> = {
  note: "sticky-note",
  insight: "sparkles",
  warning: "alert-triangle",
};

export interface CalloutProps extends HTMLAttributes<HTMLDivElement> {
  tone?: "note" | "insight" | "warning";
  title?: string;
  icon?: string;
  children: ReactNode;
}

export function Callout({
  tone = "note",
  title,
  icon,
  children,
  className = "",
  ...rest
}: CalloutProps) {
  return (
    <div
      className={["kw-callout", `kw-callout--${tone}`, className].filter(Boolean).join(" ")}
      {...rest}
    >
      <span className="kw-callout__icon">
        <Icon name={icon ?? CALLOUT_ICONS[tone]} size={18} />
      </span>
      <div>
        {title && <p className="kw-callout__title">{title}</p>}
        <div className="kw-callout__text">{children}</div>
      </div>
    </div>
  );
}

export interface ConfidenceMeterProps {
  value: number;
  showLabel?: boolean;
  label?: string;
}

/** Small bar expressing a 0..1 score (credibility, relevance). */
export function ConfidenceMeter({ value, showLabel = true, label }: ConfidenceMeterProps) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const level = pct >= 75 ? "high" : pct >= 45 ? "med" : "low";
  return (
    <span className={`kw-conf kw-conf--${level}`}>
      <span className="kw-conf__track">
        <span className="kw-conf__fill" style={{ width: `${pct}%` }} />
      </span>
      {showLabel && <span className="kw-conf__val">{label ?? `${pct}%`}</span>}
    </span>
  );
}
