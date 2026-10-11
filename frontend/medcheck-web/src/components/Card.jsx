export default function Card({ as: Tag = "div", className = "", children, ...rest }) {
  return <Tag className={`card p-5 sm:p-6 ${className}`} {...rest}>{children}</Tag>;
}
