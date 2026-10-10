import { Link } from "react-router-dom";

const VARIANT = { primary: "", secondary: "pill-secondary", danger: "pill-danger" };

/** The capsule button. Pass `to` for a router link, `href` for a plain link. */
export default function Button({ variant = "primary", size = "md", to, href, className = "", busy, disabled, children, ...rest }) {
  const cls = `pill ${VARIANT[variant]} ${size === "lg" ? "pill-lg" : ""} ${className}`;
  if (to) return <Link to={to} className={cls} {...rest}>{children}</Link>;
  if (href) return <a href={href} className={cls} {...rest}>{children}</a>;
  return (
    <button type="button" className={cls} {...rest} disabled={busy || disabled} aria-busy={busy || undefined}>
      {busy && <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-navy/30 border-t-navy" />}
      {children}
    </button>
  );
}
